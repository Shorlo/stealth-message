import Foundation

// MARK: - Protocol errors

/// Errors produced by the network / protocol layer.
enum ProtocolError: Error, LocalizedError {
    case malformed(String)
    case versionMismatch(String)
    case roomFull
    case roomNotFound(String)
    case joinDenied(String)
    case handshakeTimeout
    case timeout
    case server(code: Int, reason: String)
    case notConnected

    var errorDescription: String? {
        switch self {
        case .malformed(let r):        return "Malformed message: \(r)"
        case .versionMismatch(let v):  return "Protocol version mismatch: \(v)"
        case .roomFull:                return "Room is already occupied (4006)"
        case .roomNotFound(let r):     return "Room not found: \(r)"
        case .joinDenied(let r):       return "Join request denied: \(r)"
        case .handshakeTimeout:        return "Handshake timed out (4005)"
        case .timeout:                 return "Operation timed out"
        case .server(let c, let r):    return "Server error \(c): \(r)"
        case .notConnected:            return "Not connected"
        }
    }
}

// MARK: - Wire value types (Codable)

/// One entry in a `roomsinfo` response.
struct WireRoomInfo: Codable, Sendable {
    let id: String
    let kind: String       // "1:1" or "group"
    let peers: Int
    let available: Bool?   // only present for "1:1" rooms
}

/// One entry in a `peerlist` frame.
struct WirePeerInfo: Codable, Sendable {
    let alias: String
    let fingerprint: String
}

// MARK: - Incoming frame discriminated union

/// All frame types the protocol can receive (protocol.md §9).
/// Unknown `type` values are silently ignored per spec (forward compatibility).
enum IncomingFrame: Sendable {
    case hello(version: String, alias: String, pubkey: String, room: String?)
    case roomsInfo(rooms: [WireRoomInfo])
    case roomList(groups: [String])
    case message(id: String, payload: String, timestamp: Int64, sender: String?)
    case peerList(peers: [WirePeerInfo])
    case move(room: String)
    case pending
    case approved
    case ping
    case pong
    case bye
    case error(code: Int, reason: String)
    case unknown(String)
}

extension IncomingFrame {
    /// Parses one UTF-8 JSON frame from the wire.
    nonisolated static func parse(from text: String) throws -> IncomingFrame {
        guard let data = text.data(using: .utf8) else {
            throw ProtocolError.malformed("frame is not valid UTF-8")
        }
        let d = JSONDecoder()
        struct T: Decodable { let type: String? }
        let probe = try? d.decode(T.self, from: data)

        switch probe?.type {
        case "hello":
            struct P: Decodable { let version: String?; let alias: String?; let pubkey: String?; let room: String? }
            let p = (try? d.decode(P.self, from: data)) ?? P(version: nil, alias: nil, pubkey: nil, room: nil)
            guard let v = p.version, let a = p.alias, let k = p.pubkey else {
                throw ProtocolError.malformed("hello missing required fields (version/alias/pubkey)")
            }
            return .hello(version: v, alias: a, pubkey: k, room: p.room)

        case "roomsinfo":
            struct P: Decodable { let rooms: [WireRoomInfo]? }
            return .roomsInfo(rooms: (try? d.decode(P.self, from: data))?.rooms ?? [])

        case "roomlist":
            struct P: Decodable { let groups: [String]? }
            return .roomList(groups: (try? d.decode(P.self, from: data))?.groups ?? [])

        case "message":
            struct P: Decodable { let id: String?; let payload: String?; let timestamp: Int64?; let sender: String? }
            let p = (try? d.decode(P.self, from: data)) ?? P(id: nil, payload: nil, timestamp: nil, sender: nil)
            guard let id = p.id, let payload = p.payload, let ts = p.timestamp else {
                throw ProtocolError.malformed("message missing required fields (id/payload/timestamp)")
            }
            return .message(id: id, payload: payload, timestamp: ts, sender: p.sender)

        case "peerlist":
            struct P: Decodable { let peers: [WirePeerInfo]? }
            return .peerList(peers: (try? d.decode(P.self, from: data))?.peers ?? [])

        case "move":
            struct P: Decodable { let room: String? }
            guard let room = (try? d.decode(P.self, from: data))?.room else {
                throw ProtocolError.malformed("move missing 'room' field")
            }
            return .move(room: room)

        case "error":
            struct P: Decodable { let code: Int?; let reason: String? }
            let p = try? d.decode(P.self, from: data)
            return .error(code: p?.code ?? 4002, reason: p?.reason ?? "unknown error")

        case "pending":  return .pending
        case "approved": return .approved
        case "ping":     return .ping
        case "pong":     return .pong
        case "bye":      return .bye

        case let t?:     return .unknown(t)
        case nil:        throw ProtocolError.malformed("missing 'type' field")
        }
    }
}

// MARK: - JSON encoding helper

/// Serialises a dictionary to a compact JSON UTF-8 string. Returns nil on failure.
nonisolated func wireJSON(_ dict: [String: Any]) -> String? {
    guard let data = try? JSONSerialization.data(withJSONObject: dict),
          let text = String(data: data, encoding: .utf8) else { return nil }
    return text
}

// MARK: - Timeout helper

/// Runs `operation` with a wall-clock deadline.
/// Throws `ProtocolError.timeout` if the deadline is exceeded.
nonisolated func withDeadline<T: Sendable>(
    _ seconds: TimeInterval,
    _ operation: @Sendable @escaping () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await operation() }
        group.addTask {
            try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            throw ProtocolError.timeout
        }
        defer { group.cancelAll() }
        return try await group.next()!
    }
}

// MARK: - Base64url helpers (protocol.md §2, §4, §10)

/// Encodes a UTF-8 string as base64url without padding.
nonisolated func base64urlEncode(_ string: String) -> String {
    Data(string.utf8)
        .base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .trimmingCharacters(in: CharacterSet(charactersIn: "="))
}

/// Decodes a base64url string (with or without padding) to a UTF-8 string.
nonisolated func base64urlDecodeString(_ b64: String) -> String? {
    var s = b64.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    s += String(repeating: "=", count: (4 - s.count % 4) % 4)
    guard let data = Data(base64Encoded: s) else { return nil }
    return String(data: data, encoding: .utf8)
}
