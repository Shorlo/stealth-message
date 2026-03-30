# windows/CLAUDE.md — stealth-message Windows

Native Windows 11 client. **Not yet implemented** — directory contains only this file.
Implement `docs/protocol.md` exactly. Use `cli/` as the reference for crypto behaviour,
room model, and wire format.

---

## Target stack

| Concern        | Choice                                                      |
|----------------|-------------------------------------------------------------|
| Language       | C# 12 + .NET 8                                              |
| UI             | WinUI 3 (Windows App SDK) — Fluent Design                  |
| Concurrency    | `async/await` + `Task` — no `Thread` or `BackgroundWorker` |
| PGP            | PgpCore (NuGet, wraps BouncyCastle)                        |
| WebSocket      | `System.Net.WebSockets.ClientWebSocket` (native .NET)      |
| Secret storage | DPAPI (`ProtectedData.Protect`, scope `CurrentUser`)       |
| Tests          | xUnit                                                       |
| Min target     | Windows 10 22H2 / Windows 11                               |
| Distribution   | MSIX                                                        |

---

## What to implement

Follow `docs/protocol.md` exactly. Key behaviours derived from `cli/`:

**Crypto (`Crypto/` layer):**
- RSA-4096 keypair generation via PgpCore. Encrypt private key with DPAPI before writing
  to `%APPDATA%\stealth-message\keys\`. Scope: `CurrentUser`.
- Wire encoding: sign-then-encrypt → ASCII-armored → Base64 URL-safe (same as CLI).
- `Encrypt(plaintext, recipientPubKey, senderPrivKey) → string`
- `Decrypt(payload, recipientPrivKey, senderPubKey) → string` — throw on invalid signature.
- Fingerprint display: 40 hex chars in groups of 4, space-separated.

**Network (`Network/` layer):**
- Implement all message types from `docs/protocol.md`.
- `listrooms` / `roomsinfo` before handshake — no auth, close after response.
- Group room join: handle `pending` frame after hello; block until `approved` or `error`.
- `sender` field in forwarded group messages — use it as display name, not the host alias.
- `ClientWebSocket` is not thread-safe for concurrent sends — use a `SemaphoreSlim(1,1)`
  around all send calls.

**UI:**
- MVVM strict: no business logic in code-behind (`.xaml.cs`). Only ViewModel wiring.
- Dispatcher in WinUI 3 is `DispatcherQueue`, not `Dispatcher`.
  Update UI from background: `dispatcherQueue.TryEnqueue(() => { ... })`.
- `PasswordBox` for passphrase — never `TextBox`.
- Show room list (kind + peer count, no peer names) before joining.
- Show fingerprint prominently after connect for out-of-band verification.

---

## Constraints

- Nullable reference types enabled (`<Nullable>enable</Nullable>`). No `!` without reason.
- Never `.Result` or `.Wait()` on tasks — deadlocks the UI thread.
- Passphrase kept as `SecureString` in memory; `Dispose()` on session end.
- Tests project must be plain `net8.0`, not WinUI — only test Core logic, no app lifecycle.
- Logging via `ILogger<T>` (Microsoft.Extensions.Logging). No `Console.WriteLine`.
