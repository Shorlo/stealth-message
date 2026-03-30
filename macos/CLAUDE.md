# macos/CLAUDE.md — stealth-message macOS

Native macOS client. **Not yet implemented** — directory contains only this file.
Implement `docs/protocol.md` exactly. Use `cli/` as the reference for crypto behaviour,
room model, and wire format.

---

## Target stack

| Concern        | Choice                                              |
|----------------|-----------------------------------------------------|
| Language       | Swift 5.9+                                          |
| UI             | SwiftUI (AppKit only where SwiftUI cannot reach)    |
| Concurrency    | Swift Concurrency — `async/await` + `Actor`         |
| PGP            | ObjectivePGP (via Swift Package Manager)            |
| WebSocket      | `URLSessionWebSocketTask` (no external deps)        |
| Secret storage | Keychain Services (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`) |
| Tests          | XCTest / Swift Testing                              |
| Min target     | macOS 13.0 (Ventura)                                |

---

## What to implement

Follow `docs/protocol.md` exactly. Key behaviours derived from `cli/`:

**Crypto (`Crypto/` layer):**
- RSA-4096 keypair generation via ObjectivePGP. Store private key in Keychain only.
- Wire encoding: sign-then-encrypt → ASCII-armored → Base64 URL-safe (same as CLI).
- `encrypt(plaintext, recipientPubKey, senderPrivKey) → String`
- `decrypt(payload, recipientPrivKey, senderPubKey) → String` — throw on invalid signature.
- Fingerprint display: 40 hex chars in groups of 4, space-separated.

**Network (`Network/` layer):**
- Implement all message types from `docs/protocol.md` (hello, message, ping/pong, bye,
  error, listrooms, roomsinfo, roomlist, pending, approved, move).
- `listrooms` / `roomsinfo` before handshake — no auth, closes connection after response.
- Group room join: handle `pending` frame after hello; block until `approved` or `error`.
- `sender` field in forwarded group messages — use it as display name, not the host alias.

**UI:**
- MVVM. All business logic in ViewModels (`@MainActor`). Views are pure presentation.
- Show room list (kind + peer count, no peer names) before joining.
- Show fingerprint prominently after connect for out-of-band verification.

---

## Constraints

- No `DispatchQueue.main.async` — use `@MainActor` and `await MainActor.run`.
- No `UserDefaults` for anything security-related.
- No `try!` in production. `try?` only when failure is genuinely irrelevant.
- Passphrase never stored — prompt at launch, hold in memory only for session duration.
- ObjectivePGP is ObjC — wrap it in a Swift `actor` in `PGPKeyManager.swift`;
  no ObjC API should leak past that file.
- Split into two SPM targets: `StealthMessageCore` (testable, no app lifecycle)
  and `StealthMessage` (executable, imports Core).
