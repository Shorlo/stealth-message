import Foundation
import os

/// WebSocket client implementing stealth-message protocol.md §1–§7.
///
/// Mirrors `cli/stealth_cli/network/client.py`.
///
/// Usage:
/// ```swift
/// let client = StealthClient(alias: "Bob", armoredPrivkey: priv,
///                            armoredPubkey: pub, passphrase: pass)
/// client.onMessage = { plaintext, sender in … }
/// try await client.connect(to: url, roomID: "lobby")
/// try await client.send("Hello!")
/// ```
actor StealthClient {

    // MARK: - Protocol constants

    private static let protocolVersion    = "1"
    private static let handshakeTimeout  : TimeInterval = 10
    private static let pongTimeout       : TimeInterval = 10
    private static let joinRequestTimeout: TimeInterval = 65
    private static let pingInterval      : TimeInterval = 30

    private let log = Logger(subsystem: "StealthMessage", category: "StealthClient")

    // MARK: - Identity

    private let alias: String
    private let armoredPrivkey: String
    private let armoredPubkey: String
    private let passphrase: String
    private let crypto = PGPKeyManager()

    // MARK: - Peer state (populated after handshake)

    private(set) var peerAlias: String?
    private(set) var peerArmoredPubkey: String?
    private(set) var peerFingerprint: String?
    private(set) var roomID: String = "default"

    // MARK: - Connection state

    private var wsTask: URLSessionWebSocketTask?
    private var receiveLoopTask: Task<Void, Never>?
    private var pingLoopTask: Task<Void, Never>?

    /// One-shot stream signalled when a pong arrives (used by `ping()`).
    private var pongStreamContinuation: AsyncStream<Void>.Continuation?

    // MARK: - Callbacks

    /// `(plaintext, sender?)` — sender is nil for 1:1, peer alias in group relay.
    var onMessage    : (@Sendable (String, String?) async -> Void)?
    var onDisconnected: (@Sendable () async -> Void)?
    /// Called when the server places this client in a pending state (group room).
    var onPending    : (@Sendable () async -> Void)?
    /// Called when the host approves entry into a group room.
    var onApproved   : (@Sendable () async -> Void)?
    /// Called when the server asks this client to move to a different room.
    var onMove       : (@Sendable (String) async -> Void)?
    /// Called with the updated list of group room names on this server.
    var onRoomList   : (@Sendable ([String]) async -> Void)?
    /// Called with the updated list of other peers in the current group room.
    var onPeerList   : (@Sendable ([WirePeerInfo]) async -> Void)?
    /// `(reason)` — called when the host forcibly disconnects this client (kick).
    var onKicked     : (@Sendable (String) async -> Void)?

    // MARK: - Callback configuration

    /// Batch-assigns all event callbacks in a single actor hop.
    /// Call this before `connect(to:roomID:)` from any async context.
    func configure(
        onMessage:    (@Sendable (String, String?) async -> Void)? = nil,
        onDisconnected: (@Sendable () async -> Void)? = nil,
        onPending:    (@Sendable () async -> Void)? = nil,
        onApproved:   (@Sendable () async -> Void)? = nil,
        onMove:       (@Sendable (String) async -> Void)? = nil,
        onRoomList:   (@Sendable ([String]) async -> Void)? = nil,
        onPeerList:   (@Sendable ([WirePeerInfo]) async -> Void)? = nil,
        onKicked:     (@Sendable (String) async -> Void)? = nil
    ) {
        if let cb = onMessage     { self.onMessage     = cb }
        if let cb = onDisconnected { self.onDisconnected = cb }
        if let cb = onPending     { self.onPending     = cb }
        if let cb = onApproved    { self.onApproved    = cb }
        if let cb = onMove        { self.onMove        = cb }
        if let cb = onRoomList    { self.onRoomList    = cb }
        if let cb = onPeerList    { self.onPeerList    = cb }
        if let cb = onKicked      { self.onKicked      = cb }
    }

    // MARK: - Init

    init(alias: String, armoredPrivkey: String, armoredPubkey: String, passphrase: String) {
        self.alias         = String(alias.prefix(64))
        self.armoredPrivkey = armoredPrivkey
        self.armoredPubkey  = armoredPubkey
        self.passphrase     = passphrase
    }

    // MARK: - Public API

    /// Connects to a StealthServer, performs the handshake, and for group rooms
    /// blocks until the host approves or the join times out.
    func connect(to url: URL, roomID: String = "default") async throws {
        self.roomID = String(roomID.prefix(64)).isEmpty ? "default" : String(roomID.prefix(64))

        let session = URLSession(configuration: .ephemeral)
        let ws = session.webSocketTask(with: url)
        self.wsTask = ws
        ws.resume()

        do {
            try await withDeadline(Self.handshakeTimeout) {
                try await self.doHandshake(ws: ws)
            }
        } catch {
            ws.cancel(with: .goingAway, reason: nil)
            self.wsTask = nil
            throw error
        }

        receiveLoopTask = Task { await self.receiveLoop() }
        pingLoopTask    = Task { await self.pingLoop() }
    }

    /// Sends a `bye` frame and closes the connection cleanly.
    func disconnect() async {
        pingLoopTask?.cancel()
        receiveLoopTask?.cancel()
        if let ws = wsTask {
            if let frame = wireJSON(["type": "bye"]) {
                try? await ws.send(.string(frame))
            }
            ws.cancel(with: .normalClosure, reason: nil)
        }
        wsTask = nil
    }

    /// Encrypts `plaintext` for the connected peer and sends a `message` frame.
    func send(_ plaintext: String) async throws {
        guard let ws = wsTask, let recipientPubkey = peerArmoredPubkey else {
            throw ProtocolError.notConnected
        }
        let payload = try await crypto.encrypt(
            plaintext: plaintext,
            recipientArmoredPubkey: recipientPubkey,
            senderArmoredPrivkey: armoredPrivkey,
            passphrase: passphrase
        )
        let frame: [String: Any] = [
            "type":      "message",
            "id":        UUID().uuidString,
            "payload":   payload,
            "timestamp": Int64(Date().timeIntervalSince1970 * 1000)
        ]
        guard let text = wireJSON(frame) else {
            throw ProtocolError.malformed("cannot serialise message frame")
        }
        try await ws.send(.string(text))
    }

    /// Sends a protocol `ping` and returns the round-trip time in milliseconds.
    func ping() async throws -> Double {
        guard let ws = wsTask else { throw ProtocolError.notConnected }

        let start = Date()
        var streamCont: AsyncStream<Void>.Continuation!
        let stream = AsyncStream<Void> { streamCont = $0 }
        pongStreamContinuation = streamCont

        guard let frame = wireJSON(["type": "ping"]) else {
            throw ProtocolError.malformed("cannot serialise ping")
        }
        try await ws.send(.string(frame))

        try await withDeadline(Self.pongTimeout) {
            for await _ in stream { break }
        }
        return -start.timeIntervalSinceNow * 1000.0
    }

    // MARK: - Room discovery (no auth required, protocol.md §1)

    /// Queries available rooms from a StealthServer without joining.
    static func queryRooms(url: URL, timeout: TimeInterval = 5) async -> [WireRoomInfo] {
        do {
            return try await withDeadline(timeout) {
                let ws = URLSession(configuration: .ephemeral).webSocketTask(with: url)
                ws.resume()
                defer { ws.cancel(with: .normalClosure, reason: nil) }

                guard let frame = wireJSON(["type": "listrooms"]) else { return [] }
                try await ws.send(.string(frame))

                let raw = try await receiveTextStatic(from: ws)
                guard case .roomsInfo(let rooms) = try IncomingFrame.parse(from: raw) else {
                    return []
                }
                return rooms
            }
        } catch {
            return []
        }
    }

    // MARK: - Handshake

    private func doHandshake(ws: URLSessionWebSocketTask) async throws {
        // Send client hello (protocol §2).
        let hello: [String: Any] = [
            "type":    "hello",
            "version": Self.protocolVersion,
            "room":    roomID,
            "alias":   alias,
            "pubkey":  base64urlEncode(armoredPubkey)
        ]
        guard let helloText = wireJSON(hello) else {
            throw ProtocolError.malformed("cannot serialise hello frame")
        }
        try await ws.send(.string(helloText))

        // Receive server hello.
        let raw   = try await receiveText(from: ws)
        let frame = try IncomingFrame.parse(from: raw)

        switch frame {
        case .error(let code, let reason):
            throw mapServerError(code: code, reason: reason)

        case .hello(let version, let peerAlias, let peerPubkeyB64, _):
            guard version == Self.protocolVersion else {
                throw ProtocolError.versionMismatch(version)
            }
            guard let decoded = base64urlDecodeString(peerPubkeyB64), !decoded.isEmpty else {
                throw ProtocolError.malformed("invalid pubkey encoding in server hello")
            }
            self.peerAlias         = String(peerAlias.prefix(64))
            self.peerArmoredPubkey = decoded
            self.peerFingerprint   = try await crypto.fingerprint(armoredPublic: decoded)

        default:
            throw ProtocolError.malformed("expected 'hello', got unexpected frame type")
        }

        // Peek for a possible `pending` frame (group rooms only).
        // 0.5 s timeout — if nothing arrives this is a normal 1:1 room.
        let peeked = try? await withDeadline(0.5) { try await self.receiveText(from: ws) }

        if let raw2 = peeked,
           let peekedFrame = try? IncomingFrame.parse(from: raw2),
           case .pending = peekedFrame {
            await onPending?()
            // Wait for host approval (65 s — slightly more than server's 60 s).
            try await withDeadline(Self.joinRequestTimeout) {
                try await self.waitForApproval(ws: ws)
            }
        }
    }

    /// Loops receiving frames until `approved` or `error` arrives.
    private func waitForApproval(ws: URLSessionWebSocketTask) async throws {
        while true {
            let raw   = try await receiveText(from: ws)
            let frame = try IncomingFrame.parse(from: raw)
            switch frame {
            case .approved:
                await onApproved?()
                return
            case .error(let code, let reason):
                throw mapServerError(code: code, reason: reason)
            default:
                continue   // ignore other frames (e.g. roomlist) during approval wait
            }
        }
    }

    // MARK: - Receive loop

    private func receiveLoop() async {
        guard let ws = wsTask else { return }
        defer {
            Task { await self.onDisconnected?() }
        }
        while !Task.isCancelled {
            do {
                let raw = try await receiveText(from: ws)
                await dispatch(raw: raw)
            } catch {
                break
            }
        }
    }

    private func dispatch(raw: String) async {
        do {
            let frame = try IncomingFrame.parse(from: raw)
            switch frame {
            case .message(let id, let payload, _, let sender):
                _ = id  // deduplication tracked by caller if needed
                await handleChat(payload: payload, sender: sender)

            case .ping:
                await safeSend(["type": "pong"])

            case .pong:
                pongStreamContinuation?.yield(())
                pongStreamContinuation?.finish()
                pongStreamContinuation = nil

            case .kick(let reason):
                // Host forcibly disconnected us — display reason then close (protocol §5).
                await onKicked?(reason)
                wsTask?.cancel(with: .normalClosure, reason: nil)
                wsTask = nil
                receiveLoopTask?.cancel()
                pingLoopTask?.cancel()
                return

            case .bye:
                wsTask?.cancel(with: .normalClosure, reason: nil)
                wsTask = nil

            case .pending:
                await onPending?()

            case .approved:
                await onApproved?()

            case .move(let room):
                await onMove?(room)

            case .roomList(let groups):
                await onRoomList?(groups)

            case .peerList(let peers):
                await onPeerList?(peers)

            case .error(let code, let reason):
                log.warning("Server error: code=\(code) reason=\(reason)")

            case .unknown(let t):
                log.debug("Ignoring unknown frame type '\(t)'")

            default:
                break
            }
        } catch {
            await safeSendError(code: 4002, reason: "invalid JSON")
        }
    }

    private func handleChat(payload: String, sender: String?) async {
        guard let senderPubkey = peerArmoredPubkey else { return }
        do {
            let plaintext = try await crypto.decrypt(
                payload: payload,
                recipientArmoredPrivkey: armoredPrivkey,
                senderArmoredPubkey: senderPubkey,
                passphrase: passphrase
            )
            await onMessage?(plaintext, sender)
        } catch CryptoError.signatureInvalid {
            await safeSendError(code: 4003, reason: "PGP signature invalid")
        } catch {
            await safeSendError(code: 4004, reason: "decryption failed")
        }
    }

    // MARK: - Keepalive loop

    private func pingLoop() async {
        while !Task.isCancelled {
            do {
                try await Task.sleep(nanoseconds: UInt64(Self.pingInterval * 1_000_000_000))
                _ = try await ping()
            } catch {
                break
            }
        }
    }

    // MARK: - Utilities

    private func receiveText(from ws: URLSessionWebSocketTask) async throws -> String {
        let msg = try await ws.receive()
        switch msg {
        case .string(let text): return text
        case .data(let data):
            guard let text = String(data: data, encoding: .utf8) else {
                throw ProtocolError.malformed("non-UTF-8 data frame")
            }
            return text
        @unknown default:
            throw ProtocolError.malformed("unknown WebSocket message type")
        }
    }

    /// Static version for use in static `queryRooms` (no actor isolation needed).
    private static func receiveTextStatic(from ws: URLSessionWebSocketTask) async throws -> String {
        let msg = try await ws.receive()
        switch msg {
        case .string(let text): return text
        case .data(let data):
            guard let text = String(data: data, encoding: .utf8) else {
                throw ProtocolError.malformed("non-UTF-8 data frame")
            }
            return text
        @unknown default:
            throw ProtocolError.malformed("unknown WebSocket message type")
        }
    }

    private func safeSend(_ dict: [String: Any]) async {
        guard let ws = wsTask, let text = wireJSON(dict) else { return }
        try? await ws.send(.string(text))
    }

    private func safeSendError(code: Int, reason: String) async {
        await safeSend(["type": "error", "code": code, "reason": reason])
    }

    private func mapServerError(code: Int, reason: String) -> ProtocolError {
        switch code {
        case 4006: return .roomFull
        case 4007: return .roomNotFound(reason)
        case 4008: return .joinDenied(reason)
        default:   return .server(code: code, reason: reason)
        }
    }
}
