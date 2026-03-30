# stealth-message — Wire Protocol v0.5

**This document is the cross-platform contract.**
All clients (CLI, macOS, Windows, Linux) must implement it exactly.
If code and spec conflict, fix the code. To change the protocol, update this file first.

---

## Transport

- **WebSocket** (RFC 6455), text frames, UTF-8.
- All frames are JSON objects with a mandatory `"type"` field.
- Unknown `type` values must be silently ignored (forward compatibility).
- Handshake timeout: **10 seconds**. Close with 4005 if exceeded.

---

## 1. Room discovery (before handshake)

A client may query available rooms without authenticating.

**Client → Server:**
```json
{ "type": "listrooms" }
```

**Server → Client:**
```json
{
  "type": "roomsinfo",
  "rooms": [
    { "id": "lobby",  "kind": "1:1",   "peers": 0, "available": true  },
    { "id": "work",   "kind": "1:1",   "peers": 1, "available": false },
    { "id": "team",   "kind": "group", "peers": 2 }
  ]
}
```

- `kind`: `"1:1"` or `"group"`.
- `peers`: number of currently connected peers (not counting the host).
- `available`: present only for `"1:1"` rooms. `true` if no peer is connected.
- **Peer names are never disclosed** — counts only.
- Server closes the connection after sending `roomsinfo`.
- `ws://` prefix must be accepted; client should auto-add it if missing.

---

## 2. Handshake

After the discovery phase (or directly on connect), the client sends `hello` first.

**Client → Server:**
```json
{
  "type": "hello",
  "version": "1",
  "room": "lobby",
  "alias": "Bob",
  "pubkey": "<ASCII-armored RSA-4096 public key, Base64 URL-safe encoded>"
}
```

- `room`: target room name (max 64 chars). Defaults to `"default"` if omitted.
- `pubkey`: `base64url(ascii_armor_bytes)`. Padding `==` appended on decode.
- `alias`: display name only — no cryptographic value (max 64 chars).

**Server → Client:**
```json
{
  "type": "hello",
  "version": "1",
  "alias": "Alice",
  "pubkey": "<server ASCII-armored public key, Base64 URL-safe encoded>"
}
```

Server does not echo the `room` field.

**Immediately after hello, server sends:**
```json
{ "type": "roomlist", "groups": ["team", "open-chat"] }
```
List of all group room names on this server. Sent on connect and whenever a room
is converted to group mode. Client updates its local room list accordingly.

**Handshake rules:**
- Close with 4001 if `version != "1"`.
- Close with 4002 if required fields are missing or pubkey is malformed.
- Close with 4006 if room is a 1:1 room already occupied.
- Close with 4007 if server has a fixed room list and the requested room is not in it.
- Handshake must complete within 10 seconds or close with 4005.

---

## 3. Group room join flow

When a peer connects to a group room that already has occupants and is not pre-approved:

**Server → Client (immediately after hello exchange):**
```json
{ "type": "pending" }
```

Client blocks until receiving `approved` or `error` (max 60 s server / 65 s client timeout).

**Server → Client (host approves):**
```json
{ "type": "approved" }
```

**Server → Client (host denies or timeout):**
```json
{ "type": "error", "code": 4008, "reason": "join request denied by host" }
```

Pre-approved peers (moved by host with `/move`) skip the pending state entirely.

---

## 4. Chat messages

```json
{
  "type": "message",
  "id": "<UUID v4>",
  "payload": "<Base64 URL-safe encoded ASCII-armored OpenPGP message>",
  "timestamp": 1712000000000
}
```

- `id`: UUID v4, for deduplication.
- `payload`: `base64url(ascii_armor(pgp_message))`.
- `timestamp`: Unix ms (UTC) at send time.
- `sender` (optional): present only in group room relay messages. Contains the
  originating peer's alias. Receivers must use this as the display name — not the
  host's alias.

**Encryption pipeline (sender):**
1. Plaintext (UTF-8 string)
2. Sign with sender's private key
3. Encrypt with recipient's public key (from handshake)
4. ASCII-armor the result
5. Base64 URL-safe encode → `payload`

**Decryption pipeline (receiver):**
1. Base64 URL-safe decode (append `==` padding)
2. Decrypt with own private key
3. Verify signature with sender's public key (from handshake, or `sender` alias lookup)
4. Discard and warn if signature invalid — never display unverified content.

**Group room relay:**
The host decrypts the incoming message (sees plaintext), then re-encrypts it
individually for each other peer in the room and forwards it with `"sender": "<alias>"`.
This is inherent to the model — the host is a trusted relay in group rooms.

---

## 5. Peer movement

Host sends to a connected peer:
```json
{ "type": "move", "room": "team" }
```

Client must disconnect from current room and reconnect to `room`. The host
pre-approves the move so no `pending` state is triggered.

---

## 6. Keep-alive

```json
{ "type": "ping" }
```
```json
{ "type": "pong" }
```

- Recommended interval: 30 seconds.
- Close connection if no `pong` within 10 seconds.
- Implementations disable the WebSocket library's built-in ping and use this instead.

---

## 7. Clean disconnect

```json
{ "type": "bye" }
```

Send before closing intentionally. The receiver closes its end after receiving `bye`.

---

## 8. Errors

```json
{ "type": "error", "code": 4006, "reason": "room is already occupied" }
```

| Code | Meaning                                              | Session continues? |
|------|------------------------------------------------------|--------------------|
| 4001 | Incompatible protocol version                        | No — close         |
| 4002 | Malformed message (invalid JSON or missing fields)   | Yes                |
| 4003 | PGP signature invalid                                | Yes                |
| 4004 | Decryption failed                                    | Yes                |
| 4005 | Handshake timeout                                    | No — close         |
| 4006 | Room full (1:1 room already has a peer)              | No — close         |
| 4007 | Room not found on this server                        | No — close         |
| 4008 | Join request denied or timed out (group room)        | No — close         |

---

## 9. Message type reference

| type      | direction          | required fields                              |
|-----------|--------------------|----------------------------------------------|
| listrooms | client → server    | —                                            |
| roomsinfo | server → client    | rooms                                        |
| hello     | both               | version, alias, pubkey (+ room client only)  |
| roomlist  | server → client    | groups                                       |
| message   | both               | id, payload, timestamp (+ sender in relay)   |
| pending   | server → client    | —                                            |
| approved  | server → client    | —                                            |
| move      | server → client    | room                                         |
| ping      | both               | —                                            |
| pong      | both               | —                                            |
| bye       | both               | —                                            |
| error     | both               | code, reason                                 |

---

## 10. Crypto parameters

| Parameter        | Value                              |
|------------------|------------------------------------|
| Key algorithm    | RSA-4096                           |
| Symmetric cipher | AES-256 (via OpenPGP)              |
| Signing          | SHA-256 digest                     |
| Wire encoding    | Base64 URL-safe (RFC 4648 §5)      |
| Standard         | OpenPGP (RFC 4880)                 |
| Fingerprint fmt  | 40 hex chars, groups of 4, spaces  |

---

## 11. Security properties

| Property              | Guarantee                                                  |
|-----------------------|------------------------------------------------------------|
| Message confidentiality | Only the recipient can decrypt                          |
| Message authenticity  | Every message signed; invalid signatures discarded         |
| Room isolation        | Peers in different rooms cannot see each other's messages  |
| Room discovery        | Counts only — connected peer names never disclosed         |
| Group room relay      | Host sees plaintext during re-encryption (trust the host)  |
| Private key           | Never leaves the device; passphrase never written to disk  |
| Identity              | PGP key — no accounts, no email, no phone number          |
| Forward secrecy       | Not implemented (planned v2)                               |

---

## Version history

| Version | Date    | Changes                                                                 |
|---------|---------|-------------------------------------------------------------------------|
| 0.1     | 2026-03 | Initial draft — hello, message, ping/pong, bye, error                  |
| 0.2     | 2026-03 | Room system — `room` field in hello, errors 4006/4007, 1 peer per room |
| 0.3     | 2026-03 | Group rooms — pending/approved/move messages, error 4008, host approval |
| 0.4     | 2026-03 | Room list push — `roomlist` message sent after connect and on group conversion |
| 0.5     | 2026-03 | Pre-join discovery — `listrooms`/`roomsinfo`; `sender` field in group relay; ws:// auto-prefix |
