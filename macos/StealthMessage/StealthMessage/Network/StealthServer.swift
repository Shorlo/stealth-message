import Foundation
import Network
import os

// MARK: - Per-connection state

/// State associated with one connected peer.
struct PeerSession: Sendable {
    let id: UUID
    let connection: NWConnection
    let alias: String
    let armoredPubkey: String
    let fingerprint: String
    let roomID: String
}

// MARK: - Server

/// WebSocket host implementing stealth-message protocol.md §1–§7.
///
/// Mirrors `cli/stealth_cli/network/server.py`.
///
/// Usage:
/// ```swift
/// let server = StealthServer(alias: "Alice", armoredPrivkey: priv,
///                            armoredPubkey: pub, passphrase: pass,
///                            rooms: ["lobby"], groupRooms: ["team"])
/// server.onJoinRequest = { alias, fp, room in … }
/// let port = try await server.start(on: 8765)
/// ```
actor StealthServer {

    // MARK: - Protocol constants

    private static let protocolVersion  = "1"
    private static let handshakeTimeout : TimeInterval = 10
    private static let joinRequestTimeout: TimeInterval = 60

    private let log = Logger(subsystem: "StealthMessage", category: "StealthServer")

    // MARK: - Identity

    private let alias: String
    private let armoredPrivkey: String
    private let armoredPubkey: String
    private let passphrase: String
    private let crypto = PGPKeyManager()

    // MARK: - Room state

    /// room_id → connected peers (max 1 for 1:1, N for group).
    private var rooms: [String: [PeerSession]] = [:]
    /// Allowed room names. nil = accept any name.
    private var allowedRooms: Set<String>?
    /// Rooms that allow multiple peers (with host approval).
    private var groupRooms: Set<String>
    /// alias → target_room_id for host-initiated moves (bypasses approval).
    private var preApproved: [String: String] = [:]
    /// session.id → approval continuation (true = approved, false = denied).
    private var pendingApprovals: [UUID: CheckedContinuation<Bool, Never>] = [:]

    // MARK: - Listener state

    private var listener: NWListener?
    private(set) var port: UInt16 = 0

    // MARK: - Callbacks

    /// `(alias, fingerprint, roomID)` — fired when a peer completes the handshake.
    var onPeerConnected   : (@Sendable (String, String, String) async -> Void)?
    /// `(alias, plaintext, roomID)` — fired when a decrypted message arrives.
    var onMessage         : (@Sendable (String, String, String) async -> Void)?
    /// `(alias, roomID)` — fired when a peer disconnects.
    var onPeerDisconnected: (@Sendable (String, String) async -> Void)?
    /// `(alias, fingerprint, roomID)` — fired for group room join requests.
    var onJoinRequest     : (@Sendable (String, String, String) async -> Void)?

    // MARK: - Init

    init(
        alias: String,
        armoredPrivkey: String,
        armoredPubkey: String,
        passphrase: String,
        rooms: [String]? = nil,
        groupRooms: [String]? = nil
    ) {
        self.alias          = String(alias.prefix(64))
        self.armoredPrivkey = armoredPrivkey
        self.armoredPubkey  = armoredPubkey
        self.passphrase     = passphrase
        self.allowedRooms   = rooms.map(Set.init)
        self.groupRooms     = Set(groupRooms ?? [])
    }

    // MARK: - Callback configuration

    /// Batch-assigns all event callbacks in a single actor hop.
    /// Call this before `start(on:)` from any async context.
    func configure(
        onPeerConnected:    (@Sendable (String, String, String) async -> Void)? = nil,
        onMessage:         (@Sendable (String, String, String) async -> Void)? = nil,
        onPeerDisconnected: (@Sendable (String, String) async -> Void)? = nil,
        onJoinRequest:     (@Sendable (String, String, String) async -> Void)? = nil
    ) {
        if let cb = onPeerConnected    { self.onPeerConnected    = cb }
        if let cb = onMessage          { self.onMessage          = cb }
        if let cb = onPeerDisconnected { self.onPeerDisconnected = cb }
        if let cb = onJoinRequest      { self.onJoinRequest      = cb }
    }

    // MARK: - Lifecycle

    /// Starts the server on the given port (0 = OS-assigned).
    /// Returns the actual port in use.
    @discardableResult
    func start(on port: UInt16 = 0) async throws -> UInt16 {
        let wsOpts = NWProtocolWebSocket.Options()
        wsOpts.autoReplyPing = false
        let params = NWParameters.tcp
        params.defaultProtocolStack.applicationProtocols.insert(wsOpts, at: 0)

        let nwPort = port == 0 ? NWEndpoint.Port.any : NWEndpoint.Port(rawValue: port)!
        let nwListener = try NWListener(using: params, on: nwPort)

        nwListener.newConnectionHandler = { [weak self] connection in
            guard let self else { return }
            Task { await self.handleConnection(connection) }
        }

        // AsyncThrowingStream avoids storing a continuation in a class property,
        // which prevents @MainActor inference issues (SE-0316 / Swift 5.9).
        let (startStream, startCont) = AsyncThrowingStream<Void, Error>.makeStream()
        nwListener.stateUpdateHandler = { state in
            switch state {
            case .ready:
                startCont.yield(())
                startCont.finish()
            case .failed(let error):
                startCont.finish(throwing: error)
            case .cancelled:
                startCont.finish(throwing: ProtocolError.malformed("listener cancelled before ready"))
            default:
                break
            }
        }
        nwListener.start(queue: .global(qos: .userInitiated))
        // Wait for the first element (ready) or throw on failure.
        for try await _ in startStream { break }

        self.listener = nwListener
        self.port = nwListener.port?.rawValue ?? port
        log.info("Server listening on port \(self.port)")
        return self.port
    }

    /// Stops the server and closes all active connections.
    /// Sends a `bye` frame to every connected peer before cancelling so clients
    /// know the server shut down intentionally (not a network drop).
    func stop() {
        let byeFrame = wireJSON(["type": "bye"]) ?? "{}"
        for peers in rooms.values {
            for peer in peers {
                sendTextSync(byeFrame, to: peer.connection)
                peer.connection.cancel()
            }
        }
        rooms.removeAll()
        for cont in pendingApprovals.values { cont.resume(returning: false) }
        pendingApprovals.removeAll()
        listener?.cancel()
        listener = nil
        log.info("Server stopped")
    }

    // MARK: - Public room management

    /// Returns all currently known room IDs (allowed + occupied) with their kind.
    var allRoomInfos: [(id: String, isGroup: Bool, peerCount: Int)] {
        let ids = Set(allowedRooms ?? []).union(Set(rooms.keys))
        return ids.sorted().map { id in
            (id: id, isGroup: groupRooms.contains(id), peerCount: rooms[id]?.count ?? 0)
        }
    }

    /// Adds a room (or converts existing) at runtime.
    func addRoom(_ id: String, group: Bool = false) {
        let rid = String(id.prefix(64))
        allowedRooms?.insert(rid)
        if group { makeGroupRoom(rid) }
    }

    /// Converts a room to group mode (multiple peers, host approval).
    func makeGroupRoom(_ id: String) {
        groupRooms.insert(id)
        allowedRooms?.insert(id)
        broadcastRoomList()
    }

    // MARK: - Peer approval

    /// Pending peers waiting for host approval — keyed by session UUID.
    private var pendingSessionInfo: [UUID: (alias: String, fingerprint: String, roomID: String)] = [:]

    /// List of `(alias, fingerprint, roomID)` currently awaiting approval.
    var pendingJoinRequests: [(alias: String, fingerprint: String, roomID: String)] {
        Array(pendingSessionInfo.values)
    }

    /// Approves a pending join request by peer alias.
    func approveJoin(alias: String) throws {
        guard let (id, _) = pendingApprovals.first(where: { pendingSessionInfo[$0.key]?.alias == alias }) else {
            throw ProtocolError.malformed("No pending join request from '\(alias)'")
        }
        pendingApprovals[id]?.resume(returning: true)
        pendingApprovals.removeValue(forKey: id)
        pendingSessionInfo.removeValue(forKey: id)
    }

    /// Denies a pending join request by peer alias.
    func denyJoin(alias: String) throws {
        guard let (id, _) = pendingApprovals.first(where: { pendingSessionInfo[$0.key]?.alias == alias }) else {
            throw ProtocolError.malformed("No pending join request from '\(alias)'")
        }
        pendingApprovals[id]?.resume(returning: false)
        pendingApprovals.removeValue(forKey: id)
        pendingSessionInfo.removeValue(forKey: id)
    }

    // MARK: - Peer movement

    /// Sends a `kick` frame to the peer and closes the connection (protocol §5).
    func kickPeer(alias: String) throws {
        guard let peer = findPeer(alias: alias) else {
            throw ProtocolError.malformed("No connected peer with alias '\(alias)'")
        }
        let frame = wireJSON(["type": "kick", "reason": "disconnected by host"]) ?? "{}"
        sendTextSync(frame, to: peer.connection)
        // Brief delay to let the frame flush before cancelling.
        peer.connection.cancel()
        // Remove from rooms immediately — onPeerDisconnected fires when NWConnection closes.
        for key in rooms.keys {
            rooms[key]?.removeAll { $0.alias == alias }
        }
    }

    /// Sends a `move` frame to a peer and pre-approves them for `targetRoom`.
    func movePeer(alias: String, to targetRoom: String) async throws {
        let rid = String(targetRoom.prefix(64))
        guard let peer = findPeer(alias: alias) else {
            throw ProtocolError.malformed("No connected peer with alias '\(alias)'")
        }
        // If target room already has peers, convert to group.
        if !(rooms[rid]?.isEmpty ?? true) { makeGroupRoom(rid) }
        allowedRooms?.insert(rid)
        preApproved[alias] = rid
        guard let frame = wireJSON(["type": "move", "room": rid]) else { return }
        sendTextSync(frame, to: peer.connection)
    }

    // MARK: - Broadcast helpers

    /// Encrypts `plaintext` and sends it to every peer across all rooms.
    func broadcast(_ plaintext: String) async {
        for peers in rooms.values.map({ Array($0) }) {
            for peer in peers { await sendMessage(plaintext, to: peer) }
        }
    }

    /// Encrypts `plaintext` and sends it to all peers in the given room.
    func sendToRoom(_ roomID: String, plaintext: String) async throws {
        guard let peers = rooms[roomID], !peers.isEmpty else {
            throw ProtocolError.malformed("No peers in room '\(roomID)'")
        }
        for peer in peers { await sendMessage(plaintext, to: peer) }
    }

    /// Encrypts `plaintext` and sends it to the peer with the given alias.
    func sendTo(alias: String, plaintext: String) async throws {
        guard let peer = findPeer(alias: alias) else {
            throw ProtocolError.malformed("No connected peer with alias '\(alias)'")
        }
        await sendMessage(plaintext, to: peer)
    }

    // MARK: - Connection handler

    private func handleConnection(_ connection: NWConnection) async {
        connection.start(queue: .global(qos: .userInitiated))

        // Wait for the first frame within HANDSHAKE_TIMEOUT.
        let firstRaw: String
        do {
            firstRaw = try await withDeadline(Self.handshakeTimeout) {
                try await self.receiveFrame(from: connection)
            }
        } catch {
            await safeSend(["type": "error", "code": 4005, "reason": "handshake timeout"], to: connection)
            connection.cancel()
            return
        }

        guard let firstMsg = try? IncomingFrame.parse(from: firstRaw) else {
            await safeSend(["type": "error", "code": 4002, "reason": "invalid JSON"], to: connection)
            connection.cancel()
            return
        }

        // Handle lightweight room-discovery query (no auth required, protocol §1).
        if case .unknown(let t) = firstMsg, t == "listrooms" {
            await handleListRooms(connection: connection)
            return
        }
        // Also handle if it parsed as a correctly typed listrooms (unknown since we don't have a case for it)
        // Actually 'listrooms' has no extra fields so check the raw JSON directly
        if let data = firstRaw.data(using: .utf8),
           let obj  = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           obj["type"] as? String == "listrooms" {
            await handleListRooms(connection: connection)
            return
        }

        // Perform full handshake.
        let peer: PeerSession
        do {
            peer = try await withDeadline(Self.handshakeTimeout) {
                try await self.doHandshake(connection: connection, firstFrame: firstMsg)
            }
        } catch let pe as ProtocolError {
            let (code, reason) = protocolErrorToWire(pe)
            await safeSend(["type": "error", "code": code, "reason": reason], to: connection)
            connection.cancel()
            return
        } catch {
            await safeSend(["type": "error", "code": 4002, "reason": "handshake error"], to: connection)
            connection.cancel()
            return
        }

        // If this peer is joining a group room that requires approval, wait here
        // (outside the handshake timeout — host has the full JOIN_REQUEST_TIMEOUT).
        if groupRooms.contains(peer.roomID) && preApproved[peer.alias] != peer.roomID {
            let approved = await waitForApproval(peer: peer)
            if !approved {
                await safeSend(["type": "error", "code": 4008, "reason": "join request denied by host"], to: connection)
                connection.cancel()
                return
            }
            // Send approved frame.
            await safeSend(["type": "approved"], to: connection)
        }
        // Consume pre-approval if used.
        preApproved.removeValue(forKey: peer.alias)

        // Add peer to room.
        rooms[peer.roomID, default: []].append(peer)
        log.info("Peer connected: \(peer.alias)  fp=\(peer.fingerprint)  room=\(peer.roomID)")

        // Send current group room list to the newly connected peer.
        await sendRoomList(to: peer)

        // In group rooms, broadcast updated peer list to all peers.
        if groupRooms.contains(peer.roomID) {
            await broadcastPeerList(roomID: peer.roomID)
        }

        await onPeerConnected?(peer.alias, peer.fingerprint, peer.roomID)

        // Main receive loop.
        while true {
            do {
                let raw = try await receiveFrame(from: connection)
                await dispatchPeer(peer: peer, raw: raw)
            } catch {
                break
            }
        }

        // Cleanup on disconnect.
        rooms[peer.roomID]?.removeAll { $0.id == peer.id }
        if rooms[peer.roomID]?.isEmpty == true { rooms.removeValue(forKey: peer.roomID) }
        log.info("Peer disconnected: \(peer.alias)  room=\(peer.roomID)")

        if groupRooms.contains(peer.roomID) {
            await broadcastPeerList(roomID: peer.roomID)
        }
        await onPeerDisconnected?(peer.alias, peer.roomID)
    }

    // MARK: - Handshake

    private func doHandshake(connection: NWConnection, firstFrame: IncomingFrame) async throws -> PeerSession {
        // The firstFrame must be a hello.
        guard case .hello(let version, let peerAlias, let peerPubkeyB64, let roomOpt) = firstFrame else {
            throw ProtocolError.malformed("expected 'hello', got different frame type")
        }
        guard version == Self.protocolVersion else {
            throw ProtocolError.versionMismatch(version)
        }
        guard !peerAlias.isEmpty, !peerPubkeyB64.isEmpty else {
            throw ProtocolError.malformed("hello missing required fields")
        }

        let roomID = String((roomOpt ?? "default").prefix(64)).isEmpty ? "default" : String((roomOpt ?? "default").prefix(64))

        if let allowed = allowedRooms, !allowed.contains(roomID) {
            throw ProtocolError.roomNotFound(roomID)
        }

        guard let peerArmored = base64urlDecodeString(peerPubkeyB64), !peerArmored.isEmpty else {
            throw ProtocolError.malformed("invalid pubkey encoding in hello")
        }

        let peerFP: String
        do {
            peerFP = try await crypto.fingerprint(armoredPublic: peerArmored)
        } catch {
            throw ProtocolError.malformed("invalid pubkey in hello")
        }

        let existing    = rooms[roomID] ?? []
        let isGroup     = groupRooms.contains(roomID)
        let isPreApproved = preApproved[peerAlias] == roomID

        // 1:1 room already occupied → reject.
        if !existing.isEmpty && !isGroup && !isPreApproved {
            throw ProtocolError.roomFull
        }

        // Send server hello.
        let helloFrame: [String: Any] = [
            "type":    "hello",
            "version": Self.protocolVersion,
            "alias":   alias,
            "pubkey":  base64urlEncode(armoredPubkey)
        ]
        guard let helloText = wireJSON(helloFrame) else {
            throw ProtocolError.malformed("cannot serialise server hello")
        }
        try await sendFrame(helloText, to: connection)

        let peer = PeerSession(
            id: UUID(),
            connection: connection,
            alias: String(peerAlias.prefix(64)),
            armoredPubkey: peerArmored,
            fingerprint: peerFP,
            roomID: roomID
        )

        // For group rooms (not pre-approved), send `pending` and trigger host callback.
        if isGroup && !isPreApproved {
            guard let pendingText = wireJSON(["type": "pending"]) else { return peer }
            try await sendFrame(pendingText, to: connection)
            await onJoinRequest?(peer.alias, peer.fingerprint, peer.roomID)
        }

        return peer
    }

    // MARK: - Group room approval

    private func waitForApproval(peer: PeerSession) async -> Bool {
        await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            self.pendingApprovals[peer.id] = cont
            self.pendingSessionInfo[peer.id] = (alias: peer.alias, fingerprint: peer.fingerprint, roomID: peer.roomID)
        }
    }

    // MARK: - Message dispatch (per peer)

    private func dispatchPeer(peer: PeerSession, raw: String) async {
        guard let frame = try? IncomingFrame.parse(from: raw) else {
            await safeSend(["type": "error", "code": 4002, "reason": "invalid JSON"], to: peer.connection)
            return
        }

        switch frame {
        case .message(_, let payload, _, _):
            await handleChat(from: peer, payload: payload)

        case .ping:
            await safeSend(["type": "pong"], to: peer.connection)

        case .pong:
            break  // keepalive response — no action needed

        case .bye:
            peer.connection.cancel()

        case .error(let code, let reason):
            log.warning("Error from peer \(peer.alias): code=\(code) reason=\(reason)")

        default:
            log.debug("Ignoring frame type from peer \(peer.alias)")
        }
    }

    private func handleChat(from peer: PeerSession, payload: String) async {
        // Decrypt the message to get plaintext.
        let plaintext: String
        do {
            plaintext = try await crypto.decrypt(
                payload: payload,
                recipientArmoredPrivkey: armoredPrivkey,
                senderArmoredPubkey: peer.armoredPubkey,
                passphrase: passphrase
            )
        } catch CryptoError.signatureInvalid {
            await safeSend(["type": "error", "code": 4003, "reason": "PGP signature invalid"], to: peer.connection)
            return
        } catch {
            log.debug("Decryption error from \(peer.alias): \(error)")
            await safeSend(["type": "error", "code": 4004, "reason": "decryption failed"], to: peer.connection)
            return
        }

        await onMessage?(peer.alias, plaintext, peer.roomID)

        // In group rooms, re-encrypt and forward to all other peers (protocol §4).
        if groupRooms.contains(peer.roomID) {
            let others = (rooms[peer.roomID] ?? []).filter { $0.id != peer.id }
            for other in others {
                await sendMessage(plaintext, to: other, sender: peer.alias)
            }
        }
    }

    // MARK: - Room discovery handler

    private func handleListRooms(connection: NWConnection) async {
        let info = roomsInfo()
        guard let frame = wireJSON(["type": "roomsinfo", "rooms": info]) else {
            connection.cancel()
            return
        }
        try? await sendFrame(frame, to: connection)
        connection.cancel()
    }

    private func roomsInfo() -> [[String: Any]] {
        let allRooms = Set(allowedRooms ?? []).union(Set(rooms.keys))
        return allRooms.sorted().map { roomID -> [String: Any] in
            let isGroup = groupRooms.contains(roomID)
            let count   = rooms[roomID]?.count ?? 0
            if isGroup {
                return ["id": roomID, "kind": "group", "peers": count]
            } else {
                return ["id": roomID, "kind": "1:1", "peers": count, "available": count == 0]
            }
        }
    }

    // MARK: - Peer list broadcast (protocol §3 — after approval and on every join/leave)

    private func broadcastPeerList(roomID: String) async {
        guard let peersInRoom = rooms[roomID] else { return }
        for peer in peersInRoom {
            let others = peersInRoom
                .filter { $0.id != peer.id }
                .map { ["alias": $0.alias, "fingerprint": $0.fingerprint] }
            guard let frame = wireJSON(["type": "peerlist", "peers": others]) else { continue }
            await safeSend(frame, to: peer.connection)
        }
    }

    // MARK: - Room list push (protocol §2 — after handshake and on group room conversion)

    private func sendRoomList(to peer: PeerSession) async {
        guard let frame = wireJSON(["type": "roomlist", "groups": Array(groupRooms).sorted()]) else { return }
        await safeSend(frame, to: peer.connection)
    }

    private func broadcastRoomList() {
        let frame = wireJSON(["type": "roomlist", "groups": Array(groupRooms).sorted()]) ?? "{}"
        for peers in rooms.values {
            for peer in peers {
                sendTextSync(frame, to: peer.connection)
            }
        }
    }

    // MARK: - Encrypted message helpers

    private func sendMessage(_ plaintext: String, to peer: PeerSession, sender: String? = nil) async {
        let payload: String
        do {
            payload = try await crypto.encrypt(
                plaintext: plaintext,
                recipientArmoredPubkey: peer.armoredPubkey,
                senderArmoredPrivkey: armoredPrivkey,
                passphrase: passphrase
            )
        } catch {
            log.error("Encryption failed for \(peer.alias): \(error)")
            return
        }
        var frame: [String: Any] = [
            "type":      "message",
            "id":        UUID().uuidString,
            "payload":   payload,
            "timestamp": Int64(Date().timeIntervalSince1970 * 1000)
        ]
        if let sender { frame["sender"] = sender }
        guard let text = wireJSON(frame) else { return }
        await safeSend(text, to: peer.connection)
    }

    // MARK: - Frame I/O (NWConnection)

    /// Awaits one text WebSocket frame from `connection`.
    private func receiveFrame(from connection: NWConnection) async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            connection.receiveMessage { data, context, _, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let data,
                      let context,
                      let meta = context.protocolMetadata(definition: NWProtocolWebSocket.definition)
                                        as? NWProtocolWebSocket.Metadata,
                      meta.opcode == .text,
                      let text = String(data: data, encoding: .utf8)
                else {
                    continuation.resume(throwing: ProtocolError.malformed("non-text WebSocket frame"))
                    return
                }
                continuation.resume(returning: text)
            }
        }
    }

    /// Sends a text WebSocket frame. Awaits completion.
    private func sendFrame(_ text: String, to connection: NWConnection) async throws {
        let data = Data(text.utf8)
        let meta = NWProtocolWebSocket.Metadata(opcode: .text)
        let ctx  = NWConnection.ContentContext(identifier: "text", metadata: [meta])
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            connection.send(content: data, contentContext: ctx, isComplete: true,
                            completion: .contentProcessed { error in
                if let error { cont.resume(throwing: error) } else { cont.resume() }
            })
        }
    }

    /// Fire-and-forget text send (sync, no await — for use in non-async contexts).
    @discardableResult
    private func sendTextSync(_ text: String, to connection: NWConnection) -> Bool {
        let data = Data(text.utf8)
        let meta = NWProtocolWebSocket.Metadata(opcode: .text)
        let ctx  = NWConnection.ContentContext(identifier: "text", metadata: [meta])
        connection.send(content: data, contentContext: ctx, isComplete: true, completion: .idempotent)
        return true
    }

    /// Encodes a dict as JSON and sends it; ignores errors.
    private func safeSend(_ dict: [String: Any], to connection: NWConnection) async {
        guard let text = wireJSON(dict) else { return }
        try? await sendFrame(text, to: connection)
    }

    /// Overload accepting a pre-encoded string.
    private func safeSend(_ text: String, to connection: NWConnection) async {
        try? await sendFrame(text, to: connection)
    }

    // MARK: - Lookup helpers

    private func findPeer(alias: String) -> PeerSession? {
        for peers in rooms.values {
            if let peer = peers.first(where: { $0.alias == alias }) { return peer }
        }
        return nil
    }

    private func protocolErrorToWire(_ error: ProtocolError) -> (Int, String) {
        switch error {
        case .versionMismatch:   return (4001, "incompatible protocol version")
        case .malformed(let r): return (4002, r)
        case .handshakeTimeout:  return (4005, "handshake timeout")
        case .roomFull:          return (4006, "room is already occupied")
        case .roomNotFound(let r): return (4007, "room '\(r)' not found on this server")
        case .joinDenied(let r): return (4008, r)
        default:                 return (4002, error.localizedDescription)
        }
    }
}
