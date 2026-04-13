# Windows Client — Implementation Plan
### stealth-message / C# 12 + WinUI 3

---

## Current state analysis

| Reference | Status | Relevance for Windows |
|---|---|---|
| `cli/` Python | Complete reference implementation | Exact protocol, room model, crypto pipeline |
| `macos/` Swift | Second complete implementation | Layered architecture, MVVM, concurrency patterns |
| `windows/` | Only `CLAUDE.md` | Stack defined, constraints clear |
| `docs/protocol.md` | Source of truth v0.8 | 11 frame types, all mandatory |

---

## Project structure

```
windows/
├── StealthMessage.sln
├── StealthMessage/                         ← WinUI 3 app (net8.0-windows)
│   ├── StealthMessage.csproj
│   ├── App.xaml + App.xaml.cs             ← Bootstrap, DI container
│   ├── MainWindow.xaml + .cs              ← Shell: Frame navigation
│   ├── Crypto/
│   │   ├── CryptoException.cs             ← SignatureInvalidException, DecryptionFailedException
│   │   ├── KeyStore.cs                    ← DPAPI wrap/unwrap, %APPDATA% paths, secure delete
│   │   └── PgpManager.cs                  ← RSA-4096 gen, sign-then-encrypt, decrypt-then-verify, fingerprint
│   ├── Network/
│   │   ├── ProtocolException.cs           ← error codes 4001–4008
│   │   ├── WireMessage.cs                 ← sealed records per frame type + JSON parsing + base64url
│   │   ├── StealthClient.cs               ← ClientWebSocket + handshake + ping loop + receive loop
│   │   └── StealthServer.cs               ← HttpListener WebSocket + rooms + listrooms + approvals
│   ├── ViewModels/
│   │   ├── AppViewModel.cs                ← State machine: Setup → Unlock → Hub → Host|Join
│   │   ├── SetupViewModel.cs
│   │   ├── UnlockViewModel.cs
│   │   ├── HubViewModel.cs
│   │   ├── HostViewModel.cs
│   │   └── JoinViewModel.cs
│   ├── Views/
│   │   ├── SetupView.xaml + .cs
│   │   ├── UnlockView.xaml + .cs
│   │   ├── HubView.xaml + .cs
│   │   ├── HostView.xaml + .cs
│   │   └── JoinView.xaml + .cs
│   └── Assets/
└── StealthMessage.Tests/                   ← xUnit, net8.0 pure (no WinUI)
    ├── StealthMessage.Tests.csproj
    ├── Crypto/
    │   ├── PgpManagerTests.cs
    │   └── KeyStoreTests.cs
    └── Network/
        └── WireMessageTests.cs
```

---

## Implementation phases

### Phase 0 — Project scaffolding
- Create `.sln` solution file
- Create WinUI 3 app project with Windows App SDK
- Create xUnit test project targeting `net8.0` (no WinUI dependency)
- Add NuGet packages:
  - `PgpCore` — PGP operations (wraps BouncyCastle)
  - `Microsoft.Extensions.Logging` — structured logging (`ILogger<T>`)
  - `System.Security.Cryptography.ProtectedData` — DPAPI
- Enable `<Nullable>enable</Nullable>` in both projects
- Set minimum target: Windows 10 22H2 (build 19045)

---

### Phase 1 — Crypto layer (no UI/Network dependencies)

**`CryptoException.cs`**
- `SignatureInvalidException` — thrown when PGP signature does not verify; message must be discarded
- `DecryptionFailedException` — wrong key or corrupted payload
- `KeyGenerationException` — failure during RSA-4096 keygen

**`KeyStore.cs`**
- Paths: `%APPDATA%\stealth-message\keys\private.bin`, `config.json`
- `SavePrivateKey(string armoredPrivKey)` → DPAPI `ProtectedData.Protect(bytes, null, CurrentUser)` → write `.bin`
- `LoadPrivateKey()` → read `.bin` → DPAPI `Unprotect` → return armored string
- `DeleteAll()` → overwrite bytes with zeros before deleting (secure wipe)
- `HasIdentity()` → bool — checks whether `private.bin` exists

**`PgpManager.cs`**
- `GenerateKeypair(string alias, SecureString passphrase) → (string armoredPriv, string armoredPub)`
  - RSA-4096 only — reject any other key size
  - Alias embedded in the key UID
- `GetFingerprint(string armoredPub) → string`
  - Format: 40 hex chars grouped by 4 with spaces (`"XXXX XXXX … XXXX"`)
- `Encrypt(string plaintext, string recipientPub, string senderPriv, SecureString passphrase) → string`
  - Pipeline: sign-then-encrypt → ASCII armor → base64url no padding (RFC 4648 §5)
- `Decrypt(string payload, string recipientPriv, string senderPub, SecureString passphrase) → string`
  - Reverse pipeline: base64url decode → unarmor → decrypt → verify signature
  - Throws `SignatureInvalidException` if signature is invalid — **never return plaintext on bad sig**

---

### Phase 2 — Network layer

**`WireMessage.cs`**

Sealed record hierarchy — one type per protocol frame:

```csharp
abstract record WireFrame;
sealed record HelloFrame(string Version, string Room, string Alias, string PubKey)       : WireFrame;
sealed record ServerHelloFrame(string Version, string Alias, string PubKey)              : WireFrame;
sealed record MessageFrame(string Id, string Payload, long Timestamp, string? Sender)   : WireFrame;
sealed record PeerListFrame(IReadOnlyList<PeerInfo> Peers)                              : WireFrame;
sealed record RoomListFrame(IReadOnlyList<string> Groups)                               : WireFrame;
sealed record RoomsInfoFrame(IReadOnlyList<RoomInfo> Rooms)                             : WireFrame;
sealed record PendingFrame                                                               : WireFrame;
sealed record ApprovedFrame                                                              : WireFrame;
sealed record PingFrame                                                                  : WireFrame;
sealed record PongFrame                                                                  : WireFrame;
sealed record ByeFrame                                                                   : WireFrame;
sealed record KickFrame(string Reason)                                                   : WireFrame;
sealed record MoveFrame(string Room)                                                     : WireFrame;
sealed record ErrorFrame(int Code, string Reason)                                        : WireFrame;
```

- `WireFrame.Parse(string json) → WireFrame` — deserialize by `type` field
- `WireFrame.Serialize() → string` — serialize to JSON
- Helpers: `Base64UrlEncode(byte[]) → string`, `Base64UrlDecode(string) → byte[]` (no padding)

**`ProtocolException.cs`**
```csharp
public class ProtocolException(int code, string reason) : Exception(reason)
{
    public int Code { get; } = code;

    public const int VersionMismatch  = 4001;
    public const int Malformed        = 4002;
    public const int RoomFull         = 4006;
    public const int RoomNotFound     = 4007;
    public const int JoinDenied       = 4008;
}
```

**`StealthClient.cs`**
- `private readonly SemaphoreSlim _sendLock = new(1, 1)` — **every send must acquire this lock**
- `ConnectAsync(Uri serverUri, string roomId, string alias, string armoredPub) → Task`
  - Open WebSocket, send `hello`, receive server hello (timeout 10s → error 4001/4002)
  - If `pending` frame arrives: block until `approved` or `error 4008` (client timeout 65s)
  - Start `_receiveLoop` and `_pingLoop` as background Tasks
- `SendMessageAsync(string encryptedPayload) → Task`
  - Build `MessageFrame`, serialize, send under `_sendLock`
- `DisconnectAsync() → Task` — send `bye`, close WebSocket cleanly
- `QueryRoomsAsync(Uri serverUri) → Task<IReadOnlyList<RoomInfo>>`
  - Connect, send `listrooms`, receive `roomsinfo`, server closes — no auth required
- Callbacks: `OnMessage`, `OnPeerList`, `OnRoomList`, `OnKicked`, `OnMoved`, `OnDisconnected`
- `_pingLoop`: every 30s send `ping`; if no `pong` within 10s → close connection

**`StealthServer.cs`**
- `HttpListener` + `AcceptWebSocketAsync()` — no external WebSocket library
- **Pre-handshake:** read first frame; if `listrooms` → respond `roomsinfo` → close without authenticating
- Room management: `Dictionary<string, Room>` where `Room` has `Kind` (OneToOne / Group) and peer list
- `OneToOne`: max 1 peer → error 4006 if already occupied
- `Group`: every peer requires host approval (including the first one)
- Callback for UI: `OnJoinRequest(string alias, string fingerprint) → Task<bool>` (true = approve)
- `MoveAsync(string alias, string targetRoom) → Task` — sends `move` to peer, pre-approves in target room
- `KickAsync(string alias, string reason) → Task` — sends `kick`, closes peer WebSocket
- `BroadcastAsync(string encryptedPayload, string senderAlias) → Task` — relay in group room with `sender` field

---

### Phase 3 — ViewModels (strict MVVM)

**`AppViewModel.cs`** — app state machine

```
┌─────────┐   HasIdentity=false    ┌───────────┐
│  Start  │ ──────────────────────▶│   Setup   │ → generates keypair → Hub
└─────────┘                        └───────────┘
     │
     │ HasIdentity=true
     ▼
┌──────────┐                       ┌──────────┐
│  Unlock  │ ──── passphrase OK ──▶│   Hub    │ ──▶ Host | Join
└──────────┘                       └──────────┘
```

- Exposes `CurrentScreen` (enum) + `CurrentViewModel` (object)
- `NavigateTo(Screen)` callable from all ViewModels
- Holds references to `PgpManager`, `KeyStore` — injected via DI when constructing ViewModels

**`SetupViewModel.cs`**
- Properties: `Alias`, `Passphrase` (SecureString), `ConfirmPassphrase`, `Fingerprint`, `IsGenerating`
- Command: `GenerateCommand` — calls `PgpManager.GenerateKeypair` → `KeyStore.SavePrivateKey` → navigate to Hub
- Validation: alias not empty, passphrase ≥ 8 chars, confirmation matches

**`UnlockViewModel.cs`**
- Properties: `Passphrase` (SecureString), `ErrorMessage`, `IsUnlocking`
- Command: `UnlockCommand` — load private key, attempt verification → navigate to Hub
- Command: `ResetIdentityCommand` — confirmation dialog → `KeyStore.DeleteAll()` → navigate to Setup

**`HubViewModel.cs`**
- Properties: `Fingerprint` (display), `ServerAddress`, `Port`, `RoomId`
- Command: `HostCommand` → navigate to HostView
- Command: `JoinCommand` → navigate to JoinView with server URI
- Command: `DiscoverRoomsCommand` → calls `StealthClient.QueryRoomsAsync(uri)` → populates `AvailableRooms`
- Command: `CopyFingerprintCommand` — copy to clipboard
- `AvailableRooms`: `ObservableCollection<RoomInfo>` (id, kind, peer count — no peer names)

**`HostViewModel.cs`**
- `ObservableCollection<PeerViewModel>` — alias + fingerprint per connected peer
- `ObservableCollection<string>` — chat message log
- `ObservableCollection<PendingPeerViewModel>` — peers awaiting approval
- Commands: `StartServerCommand`, `StopServerCommand`, `ApproveCommand(alias)`, `DenyCommand(alias)`, `KickCommand(alias)`, `MoveCommand(alias, room)`, `SendMessageCommand`
- Receives callbacks from `StealthServer` → `dispatcherQueue.TryEnqueue(...)` to update collections

**`JoinViewModel.cs`**
- Properties: `IsPending`, `IsConnected`, `PeerFingerprint`, `PeerAlias`, `RoomKind`
- `ObservableCollection<PeerViewModel>` — for group rooms
- `ObservableCollection<string>` — chat messages
- Commands: `ConnectCommand`, `DisconnectCommand`, `SendMessageCommand`
- Handles `move` frame: disconnects cleanly and reconnects to the new pre-approved room

---

### Phase 4 — Views (XAML / Fluent Design)

Each `.xaml.cs` contains only ViewModel binding to DataContext — zero logic.

**`SetupView.xaml`**
- `TextBox` for alias
- `PasswordBox` for passphrase + confirm (never `TextBox`)
- "Create identity" button (disabled while form is invalid)
- Progress indicator during keygen (RSA-4096 takes ~1–2s)
- Fingerprint display card with "Copy" button once generated

**`UnlockView.xaml`**
- `PasswordBox` for passphrase
- "Unlock" button
- "Reset identity" link (with confirmation dialog — destructive action)

**`HubView.xaml`**
- Fingerprint in a prominent card with copy button
- Two sections: "Act as Host" | "Connect to room"
- Discovery panel: URI `TextBox` + "Find rooms" button + `ListView` of rooms (kind + peer count, no names)
- Manual room ID `TextBox` if discovery is skipped

**`HostView.xaml`**
- Side panel: room list + connected peers + their fingerprints
- Pending approvals panel with Approve / Deny buttons
- Main chat panel
- Message `TextBox` + Send button
- Host commands (new room, group mode, kick, move) exposed as contextual buttons

**`JoinView.xaml`**
- "Waiting for host approval…" state (spinner) while `IsPending=true`
- Peer fingerprint displayed prominently for out-of-band verification
- Group rooms: side panel with peer list and fingerprints
- Chat panel
- `kick` handled: dialog showing reason, then disconnect
- `move` handled: automatic silent reconnect to target room

---

### Phase 5 — Tests (xUnit, net8.0)

**`PgpManagerTests.cs`**
- Keygen produces RSA-4096 (verify key size)
- Round-trip: `Encrypt` → `Decrypt` returns original plaintext
- Signature invalid: `Decrypt` with wrong sender pubkey throws `SignatureInvalidException`
- Fingerprint format: 40 hex chars, groups of 4, space-separated
- Base64url no padding: payload contains no `+`, `/`, or `=` characters
- Cross-platform compatibility: payload encrypted by CLI (Python/pgpy) must decrypt correctly

**`KeyStoreTests.cs`**
- `SavePrivateKey` + `LoadPrivateKey` → round-trip correct
- `HasIdentity` returns false before saving, true after
- `DeleteAll` → `HasIdentity` returns false again

**`WireMessageTests.cs`**
- Parse each frame type from JSON
- Serialize frames produces correct JSON
- `listrooms` / `roomsinfo` frames parse correctly
- Unknown frame type → typed exception

---

### Phase 6 — MSIX distribution

- Configure `Package.appxmanifest` (name, publisher, capabilities)
- Self-signed certificate for development (equivalent to macOS ad-hoc signing)
- Build script producing a `.msix` ready to install

---

## Implementation order

```
Phase 0 (Scaffolding)
    └─▶ Phase 1 (Crypto) ──▶ Tests Crypto
            └─▶ Phase 2 (Network) ──▶ Tests Network
                    └─▶ Phase 3 (ViewModels)
                            └─▶ Phase 4 (Views)
                                    └─▶ Phase 6 (MSIX)
```

Build each layer bottom-up and test it in isolation before building on top.
The Crypto layer is the most critical — any deviation breaks interoperability with the CLI and macOS clients.

---

## Critical constraints (from `windows/CLAUDE.md`)

| Constraint | Rule |
|---|---|
| Nullable reference types | `<Nullable>enable</Nullable>` — no `!` without justification |
| No blocking calls | Never `.Result` or `.Wait()` on tasks — deadlocks the UI thread |
| Passphrase in memory | `SecureString` only; `Dispose()` at session end; never written to disk |
| WebSocket thread safety | `SemaphoreSlim(1,1)` around all `ClientWebSocket` send calls |
| UI thread updates | `dispatcherQueue.TryEnqueue(...)` — never `Dispatcher` (that is WPF) |
| Password input | `PasswordBox` always — never `TextBox` |
| Logging | `ILogger<T>` — no `Console.WriteLine` |
| Tests isolation | Test project targets `net8.0`, not WinUI — only tests Core logic |

---

## Wire protocol reference (protocol.md v0.8)

### All frame types

| Frame | Direction | Description |
|---|---|---|
| `listrooms` | Client → Server | Room discovery, no auth. Server closes after response |
| `roomsinfo` | Server → Client | List of rooms: id, kind, peers, available? |
| `hello` | Client → Server | Handshake: version, room, alias, pubkey (base64url armored RSA-4096) |
| `hello` | Server → Client | Server identity: version, alias, pubkey |
| `roomlist` | Server → Client | Sent after hello and on group room changes |
| `pending` | Server → Client | Peer must wait for host approval (group rooms) |
| `approved` | Server → Client | Host approved the join request |
| `message` | Bidirectional | Encrypted payload: id (UUIDv4), payload (base64url), timestamp (ms UTC), sender? |
| `peerlist` | Server → Client | All other peers in room: alias + fingerprint |
| `ping` | Either → Either | Keep-alive. Interval: 30s. Response timeout: 10s |
| `pong` | Either → Either | Response to ping |
| `bye` | Either → Either | Clean disconnect intent |
| `kick` | Server → Client | Host forces disconnect. Show reason, close immediately |
| `move` | Server → Client | Host moves peer to another room. Reconnect pre-approved |
| `error` | Server → Client | Protocol error with code and reason |

### Error codes

| Code | Meaning |
|---|---|
| 4001 | Protocol version mismatch |
| 4002 | Malformed hello frame |
| 4006 | Room full (1:1 only) |
| 4007 | Room not found (fixed server) |
| 4008 | Join denied or timed out (group rooms) |

### Crypto pipeline

**Send:**
```
plaintext (UTF-8)
  → PGP literal message
  → SIGN with sender private key (RSA-4096, SHA-256)
  → ENCRYPT with recipient public key (AES-256)
  → ASCII armor
  → Base64 URL-safe encode (RFC 4648 §5 — no padding)
  → JSON "payload" field
```

**Receive:**
```
JSON "payload" field
  → Base64 URL-safe decode (append padding if needed)
  → ASCII unarmor
  → PGP decrypt with recipient private key
  → VERIFY signature with sender public key
  → if signature invalid: throw SignatureInvalidException — DISCARD MESSAGE
  → plaintext (UTF-8)
```

### Timeouts

| Event | Timeout |
|---|---|
| Handshake (hello exchange) | 10s |
| Pending approval (client side) | 65s |
| Pending approval (server side) | 60s |
| Ping response | 10s |
| Ping interval | 30s |

### Fingerprint format

40 hex characters (uppercase or lowercase), grouped by 4, space-separated:

```
A1B2 C3D4 E5F6 7890 A1B2 C3D4 E5F6 7890 A1B2 C3D4
```
