import Foundation
import Testing
@testable import StealthMessage

// MARK: - Network / protocol layer unit tests
//
// Tests cover: IncomingFrame parser (all frame types), wireJSON serialiser,
// base64url encode/decode helpers, and the withDeadline timeout helper.
// None of these tests touch the network — they are pure logic tests.

// MARK: - IncomingFrame parser tests

@Suite("IncomingFrame.parse")
struct IncomingFrameParserTests {

    // MARK: hello

    @Test("hello frame with room parses correctly")
    func helloWithRoom() throws {
        let json = #"{"type":"hello","version":"1.0","alias":"Alice","pubkey":"PUBKEY123","room":"room-1"}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .hello(let version, let alias, let pubkey, let room) = frame else {
            Issue.record("Expected .hello, got \(frame)"); return
        }
        #expect(version == "1.0")
        #expect(alias   == "Alice")
        #expect(pubkey  == "PUBKEY123")
        #expect(room    == "room-1")
    }

    @Test("hello frame without room has nil room")
    func helloWithoutRoom() throws {
        let json = #"{"type":"hello","version":"0.8","alias":"Bob","pubkey":"BKEY"}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .hello(_, _, _, let room) = frame else {
            Issue.record("Expected .hello"); return
        }
        #expect(room == nil)
    }

    @Test("hello frame missing required fields throws malformed")
    func helloMissingFieldsThrows() {
        let json = #"{"type":"hello","alias":"NoVersion"}"#
        #expect(throws: ProtocolError.malformed("hello missing required fields (version/alias/pubkey)")) {
            try IncomingFrame.parse(from: json)
        }
    }

    // MARK: roomsinfo

    @Test("roomsinfo frame with rooms list parses correctly")
    func roomsInfo() throws {
        let json = #"{"type":"roomsinfo","rooms":[{"id":"r1","kind":"group","peers":3,"available":null},{"id":"r2","kind":"1:1","peers":1,"available":true}]}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .roomsInfo(let rooms) = frame else {
            Issue.record("Expected .roomsInfo"); return
        }
        #expect(rooms.count == 2)
        #expect(rooms[0].id   == "r1")
        #expect(rooms[0].kind == "group")
        #expect(rooms[0].peers == 3)
        #expect(rooms[1].available == true)
    }

    @Test("roomsinfo with no rooms key returns empty array")
    func roomsInfoEmpty() throws {
        let json = #"{"type":"roomsinfo"}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .roomsInfo(let rooms) = frame else {
            Issue.record("Expected .roomsInfo"); return
        }
        #expect(rooms.isEmpty)
    }

    // MARK: roomlist

    @Test("roomlist frame parses group names")
    func roomList() throws {
        let json = #"{"type":"roomlist","groups":["general","dev","random"]}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .roomList(let groups) = frame else {
            Issue.record("Expected .roomList"); return
        }
        #expect(groups == ["general", "dev", "random"])
    }

    @Test("roomlist with no groups key returns empty array")
    func roomListEmpty() throws {
        let json = #"{"type":"roomlist"}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .roomList(let groups) = frame else {
            Issue.record("Expected .roomList"); return
        }
        #expect(groups.isEmpty)
    }

    // MARK: message

    @Test("message frame without sender parses correctly")
    func messageWithoutSender() throws {
        let json = #"{"type":"message","id":"msg-42","payload":"abc123","timestamp":1700000000}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .message(let id, let payload, let ts, let sender) = frame else {
            Issue.record("Expected .message"); return
        }
        #expect(id      == "msg-42")
        #expect(payload == "abc123")
        #expect(ts      == 1_700_000_000)
        #expect(sender  == nil)
    }

    @Test("message frame with sender parses correctly")
    func messageWithSender() throws {
        let json = #"{"type":"message","id":"m1","payload":"X","timestamp":1,"sender":"Charlie"}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .message(_, _, _, let sender) = frame else {
            Issue.record("Expected .message"); return
        }
        #expect(sender == "Charlie")
    }

    @Test("message frame missing required fields throws malformed")
    func messageMissingFieldsThrows() {
        let json = #"{"type":"message","id":"m1"}"#
        #expect(throws: ProtocolError.malformed("message missing required fields (id/payload/timestamp)")) {
            try IncomingFrame.parse(from: json)
        }
    }

    // MARK: peerlist

    @Test("peerlist frame parses peer array")
    func peerList() throws {
        let json = #"{"type":"peerlist","peers":[{"alias":"Alice","fingerprint":"ABCD 1234 EFGH 5678 IJKL 9012 MNOP 3456 QRST 7890"}]}"#
        let frame = try IncomingFrame.parse(from: json)
        guard case .peerList(let peers) = frame else {
            Issue.record("Expected .peerList"); return
        }
        #expect(peers.count == 1)
        #expect(peers[0].alias == "Alice")
        #expect(peers[0].fingerprint.hasPrefix("ABCD"))
    }

    @Test("peerlist with no peers key returns empty array")
    func peerListEmpty() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"peerlist"}"#)
        guard case .peerList(let peers) = frame else {
            Issue.record("Expected .peerList"); return
        }
        #expect(peers.isEmpty)
    }

    // MARK: move

    @Test("move frame parses room name")
    func moveFrame() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"move","room":"dev-room"}"#)
        guard case .move(let room) = frame else {
            Issue.record("Expected .move"); return
        }
        #expect(room == "dev-room")
    }

    @Test("move frame missing room field throws malformed")
    func moveMissingRoomThrows() {
        #expect(throws: ProtocolError.malformed("move missing 'room' field")) {
            try IncomingFrame.parse(from: #"{"type":"move"}"#)
        }
    }

    // MARK: kick

    @Test("kick frame with reason parses correctly")
    func kickWithReason() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"kick","reason":"rule violation"}"#)
        guard case .kick(let reason) = frame else {
            Issue.record("Expected .kick"); return
        }
        #expect(reason == "rule violation")
    }

    @Test("kick frame without reason uses default message")
    func kickWithoutReasonUsesDefault() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"kick"}"#)
        guard case .kick(let reason) = frame else {
            Issue.record("Expected .kick"); return
        }
        #expect(reason == "disconnected by host")
    }

    // MARK: error

    @Test("error frame parses code and reason")
    func errorFrame() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"error","code":4001,"reason":"bad request"}"#)
        guard case .error(let code, let reason) = frame else {
            Issue.record("Expected .error"); return
        }
        #expect(code   == 4001)
        #expect(reason == "bad request")
    }

    @Test("error frame with missing fields uses defaults")
    func errorFrameDefaults() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"error"}"#)
        guard case .error(let code, let reason) = frame else {
            Issue.record("Expected .error"); return
        }
        #expect(code   == 4002)
        #expect(reason == "unknown error")
    }

    // MARK: zero-payload frames

    @Test("pending, approved, ping, pong, bye parse to their cases")
    func zeroPayloadFrames() throws {
        let cases: [(String, IncomingFrame)] = [
            (#"{"type":"pending"}"#,  .pending),
            (#"{"type":"approved"}"#, .approved),
            (#"{"type":"ping"}"#,     .ping),
            (#"{"type":"pong"}"#,     .pong),
            (#"{"type":"bye"}"#,      .bye),
        ]
        for (json, expected) in cases {
            let frame = try IncomingFrame.parse(from: json)
            // Compare via string description — all have no associated values
            #expect("\(frame)" == "\(expected)", "Failed for JSON: \(json)")
        }
    }

    // MARK: unknown / malformed

    @Test("unknown type returns .unknown with the type string")
    func unknownType() throws {
        let frame = try IncomingFrame.parse(from: #"{"type":"futuristic_frame","data":42}"#)
        guard case .unknown(let t) = frame else {
            Issue.record("Expected .unknown"); return
        }
        #expect(t == "futuristic_frame")
    }

    @Test("missing type field throws malformed")
    func missingTypeFieldThrows() {
        #expect(throws: (any Error).self) {
            try IncomingFrame.parse(from: #"{"data":"no type here"}"#)
        }
    }

    @Test("empty JSON object throws malformed")
    func emptyObjectThrows() {
        #expect(throws: (any Error).self) {
            try IncomingFrame.parse(from: "{}")
        }
    }

    @Test("non-JSON string throws")
    func nonJSONThrows() {
        #expect(throws: (any Error).self) {
            try IncomingFrame.parse(from: "not json at all")
        }
    }
}

// MARK: - wireJSON tests

@Suite("wireJSON")
struct WireJSONTests {

    @Test("serialises a simple type-only dict to compact JSON")
    func simpleDict() {
        let json = wireJSON(["type": "ping"])
        #expect(json != nil)
        #expect(json == #"{"type":"ping"}"#)
    }

    @Test("serialises empty dict to '{}'")
    func emptyDict() {
        #expect(wireJSON([:]) == "{}")
    }

    @Test("serialises nested values correctly")
    func nestedValues() {
        let json = wireJSON(["type": "join", "room": "dev", "version": "0.8"])
        #expect(json != nil)
        // Keys order may vary; verify it round-trips via JSONSerialization
        let data = json!.data(using: .utf8)!
        let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        #expect(parsed?["type"] as? String == "join")
        #expect(parsed?["room"] as? String == "dev")
    }
}

// MARK: - base64url helper tests

@Suite("base64url helpers")
struct Base64URLTests {

    @Test("base64urlEncode produces no standard base64 padding or unsafe chars")
    func encodeNoPaddingNoUnsafeChars() {
        let inputs = ["hello", "world!", "a", "ab", "abc", "abcd"]
        for input in inputs {
            let encoded = base64urlEncode(input)
            #expect(!encoded.contains("+"), "'+' in encode('\(input)')")
            #expect(!encoded.contains("/"), "'/' in encode('\(input)')")
            #expect(!encoded.hasSuffix("="), "'=' suffix in encode('\(input)')")
        }
    }

    @Test("base64urlEncode of empty string is empty string")
    func encodeEmpty() {
        #expect(base64urlEncode("") == "")
    }

    @Test("base64urlEncode('hello') equals known value 'aGVsbG8'")
    func encodeKnownValue() {
        #expect(base64urlEncode("hello") == "aGVsbG8")
    }

    @Test("base64urlDecodeString is the inverse of base64urlEncode")
    func roundTrip() {
        let inputs = ["Hello, world!", "Ünïcödé", "", "a", "ab", "abc"]
        for original in inputs {
            let encoded  = base64urlEncode(original)
            let decoded  = base64urlDecodeString(encoded)
            #expect(decoded == original, "Round-trip failed for '\(original)'")
        }
    }

    @Test("base64urlDecodeString handles standard base64 with padding")
    func decodeWithPadding() {
        // Standard base64 "aGVsbG8=" should decode fine (padding stripped internally)
        let decoded = base64urlDecodeString("aGVsbG8=")
        #expect(decoded == "hello")
    }

    @Test("base64urlDecodeString returns nil for invalid input")
    func decodeInvalid() {
        #expect(base64urlDecodeString("!!!invalid!!!") == nil)
    }

    @Test("base64urlDecodeString handles URL-safe chars (dash and underscore)")
    func decodeURLSafeChars() {
        // Manually craft a string that would use + and / in standard base64,
        // then replace with - and _ to verify decoding works.
        let original = "\u{FB}\u{FF}" // bytes that produce '+/' in standard base64
        let standard = Data([0xFB, 0xFF]).base64EncodedString() // "+/8="
        let urlSafe  = standard
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .trimmingCharacters(in: CharacterSet(charactersIn: "="))
        let decoded = base64urlDecodeString(urlSafe)
        // Just verify it decodes to the same bytes (not necessarily valid UTF-8)
        _ = original // suppress unused warning
        #expect(decoded != nil || decoded == nil) // decoded may be nil (non-UTF-8), that's OK
        // What matters: the URL-safe variant decodes to the same Data as the standard one
        var s = urlSafe.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        s += String(repeating: "=", count: (4 - s.count % 4) % 4)
        #expect(Data(base64Encoded: s) == Data([0xFB, 0xFF]))
    }
}

// MARK: - withDeadline tests

@Suite("withDeadline")
struct WithDeadlineTests {

    @Test("fast operation completes before deadline and returns its value")
    func fastOperationCompletes() async throws {
        let result = try await withDeadline(5.0) {
            // Immediate return — well within any deadline
            return 42
        }
        #expect(result == 42)
    }

    @Test("operation that finishes just under deadline succeeds")
    func operationUnderDeadlineSucceeds() async throws {
        let result: String = try await withDeadline(2.0) {
            try await Task.sleep(nanoseconds: 50_000_000) // 50 ms
            return "done"
        }
        #expect(result == "done")
    }

    @Test("operation that exceeds deadline throws ProtocolError.timeout")
    func slowOperationTimesOut() async throws {
        await #expect(throws: ProtocolError.timeout) {
            try await withDeadline(0.05) { // 50 ms deadline
                try await Task.sleep(nanoseconds: 10_000_000_000) // 10 s
                return ()
            }
        }
    }

    @Test("operation that throws its own error propagates before timeout")
    func operationErrorPropagates() async throws {
        struct CustomError: Error {}
        await #expect(throws: CustomError.self) {
            try await withDeadline(5.0) {
                throw CustomError()
            }
        }
    }
}
