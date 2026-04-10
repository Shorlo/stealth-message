# stealth-message Architecture

## Overview

`stealth-message` is an end-to-end encrypted PGP chat application.
There is no central server: one participant acts as **host** (starts the WebSocket
server) and the others connect directly to it.

```
┌─────────────┐        WebSocket + PGP        ┌─────────────┐
│  Client A   │◄─────────────────────────────►│  Client B   │
│  (host)     │                               │  (join)     │
└─────────────┘                               └─────────────┘
```

In group rooms, the host acts as a relay between peers:

```
┌──────────┐   encrypted(B)  ┌──────────┐  encrypted(C)  ┌──────────┐
│ Client B  │────────────────►│  Host A  │───────────────►│ Client C │
└──────────┘                 └──────────┘                 └──────────┘
                                   │
                           re-encrypts individually
                           for each recipient —
                           sees plaintext during relay
```

No third-party relay. Encrypted messages only pass through the participants' own machines.

---

## Monorepo structure

```
stealth-message/
├── docs/
│   └── protocol.md       ← SOURCE OF TRUTH for the protocol (v0.8)
├── cli/                  ← Terminal client (Python 3.10+)  ← REFERENCE IMPLEMENTATION
├── macos/                ← Native macOS app (Swift 5.9+ / SwiftUI)  ← functional
├── windows/              ← Native Windows 11 app (C# 12 / WinUI 3)  ← pending
└── linux/                ← Native Linux app, GTK4 (Python 3.10+)    ← pending
```

**Key principle:** no shared code between platforms. The contract is `docs/protocol.md`.
If two different clients can chat with each other, the protocol is correctly implemented
in both.

---

## Implementation status

### CLI (`cli/`) — Reference implementation — Functional — v0.1.7

| Module | File | Status |
|--------|------|--------|
| Entry point / flags | `__main__.py` | Complete |
| Configuration and persistence | `config.py` | Complete |
| Key generation | `crypto/keys.py` | Complete |
| Encrypt / decrypt | `crypto/messages.py` | Complete |
| WebSocket server | `network/server.py` | Complete |
| WebSocket client | `network/client.py` | Complete |
| Chat interface | `ui/chat.py` | Complete |
| Setup wizard | `ui/setup.py` | Complete |
| Test suite | `tests/` | 64 tests, all passing |

Chat commands:

| Command | Who | Description |
|---------|-----|-------------|
| `/fp` | all | Show current peer's PGP fingerprint |
| `/rooms` | all | List all known rooms and their status |
| `/switch <room>` | all | Change active room |
| `/help` | all | Show available commands |
| `/quit` / `/exit` / `/q` | all | Close session cleanly |
| `/new <room>` | host | Create a new 1-on-1 room at runtime |
| `/group <room>` | host | Convert a room to group mode |
| `/move <alias> <room>` | host | Move a peer to another room (pre-approved) |
| `/allow <alias>` | host | Approve a pending join request |
| `/deny <alias>` | host | Deny a pending join request |
| `/pending` | host | List pending join requests |
| `/disconnect [alias]` | host | Force-disconnect a peer |

Executable flags:

| Flag | Description |
|------|-------------|
| `--host [PORT]` | Host mode, default port 8765 |
| `--rooms ROOMS` | Comma-separated room names (host mode) |
| `--join URI` | Join mode, `ws://` added automatically |
| `--room ROOM` | Room to join (join mode, default: "default") |
| `--reset` | Delete saved identity and run setup wizard |
| `--manual` | Full user manual |
| `--debug` | Verbose debug logging |

### macOS (`macos/`) — Functional — v1.0.0

| Module | File | Status |
|--------|------|--------|
| PGP key management | `Crypto/PGPKeyManager.swift` | Implemented |
| Keychain store | `Crypto/KeychainStore.swift` | Implemented |
| Crypto errors | `Crypto/CryptoError.swift` | Implemented |
| Protocol message types | `Network/Message.swift` | Implemented |
| WebSocket client | `Network/StealthClient.swift` | Implemented |
| WebSocket server | `Network/StealthServer.swift` | Implemented |
| Main ViewModel | `UI/AppViewModel.swift` | Implemented |
| Setup screen | `UI/SetupView.swift` | Implemented |
| Unlock screen | `UI/UnlockView.swift` | Implemented |
| Hub / identity | `UI/HubView.swift` | Implemented |
| Host screen | `UI/HostView.swift` | Implemented |
| Join screen | `UI/JoinView.swift` | Implemented |
| App lifecycle / graceful shutdown | `StealthMessageApp.swift` | Implemented |

External dependencies:
- **ObjectivePGP 0.99.4** — RSA-4096 + AES-256 encryption and signing
- Keychain Services (system framework)
- Network.framework (`NWListener` / `NWProtocolWebSocket`)
- URLSession (`URLSessionWebSocketTask`) — client side

### Windows (`windows/`) and Linux (`linux/`) — Pending

Not yet started. Must implement the full `docs/protocol.md` and the same crypto
behaviour as the CLI.

---

## Layers

All sub-projects follow the same layer separation:

```
┌──────────────────────┐
│         UI           │  Presentation (SwiftUI, WinUI 3, GTK4, rich/prompt_toolkit)
├──────────────────────┤
│  ViewModel /         │  Presentation logic, session state
│  Controller          │
├──────────────────────┤
│       Crypto         │  PGP encrypt/decrypt, key management
├──────────────────────┤
│       Network        │  WebSocket, protocol message handling
├──────────────────────┤
│      Security        │  OS key store (Keychain / DPAPI / libsecret)
└──────────────────────┘
```

Dependencies flow downward: UI → ViewModel → Crypto/Network → Security.
Never upward. `Crypto` and `Network` have no knowledge of the UI.

---

## Protocol (v0.8)

Transport layer: **WebSocket** (RFC 6455)
Message format: **JSON** (UTF-8)
Content encryption: **OpenPGP** (RFC 4880)

### Room discovery flow (before joining)

```
Client                         Host
   │                             │
   │── { type: "listrooms" } ───►│
   │                             │
   │◄── { type: "roomsinfo",     │   room list with type and
   │      rooms: [...] }         │   availability (no peer names)
   │                             │
   │   [connection closed]       │
   │                             │
   │   [user picks a room]       │
```

### 1-on-1 session flow

```
Client (join)                  Host
      │                             │
      │── WebSocket connect ────────►│
      │── { type: "hello",          │  exchange public keys
      │     version, room,          │  and protocol version
      │     pubkey, alias }         │
      │                             │
      │◄── { type: "hello",         │
      │      pubkey, alias }        │
      │◄── { type: "roomlist",      │  list of group rooms
      │      groups: [...] }        │  on this server
      │                             │
      │  [users verify fingerprints out-of-band]
      │                             │
      │── { type: "message",        │  messages encrypted with
      │     id, payload,            │  the host's public key,
      │     timestamp }      ───────►│  signed with own private key
      │◄── { type: "message", ──────│
      │      ... }                  │
      │                             │
      │── { type: "bye" } ─────────►│  clean disconnect
```

### Group room join flow

When a second peer tries to enter a group room:

```
Client C                      Host A                    Client B
     │                             │                         │
     │── hello (room: "team") ────►│                         │
     │◄── hello ───────────────────│                         │
     │◄── pending ─────────────────│                         │
     │                             │── on_join_request ─────►│ (host UI)
     │                             │◄── /allow C ────────────│
     │◄── approved ────────────────│                         │
     │◄── peerlist ────────────────│                         │
     │                             │                         │
     │── message ─────────────────►│── re-encrypt for B ────►│
     │◄── message (sender: B) ─────│◄── message ─────────────│
```

### Host-initiated disconnect (kick)

The host can expel a peer at any time:

```
Host                           Client
  │                                │
  │── { type: "kick",              │
  │     reason: "..." } ──────────►│
  │                                │  [client closes connection]
  │   [host closes its end]        │
```

See `docs/protocol.md` for the complete specification of all message types,
required fields, error codes, and security considerations.

---

## Room model

### 1-on-1 rooms

- Admit exactly **one peer** at a time.
- A second peer receives error `4006` (room occupied).
- The host can have multiple 1-on-1 rooms active in parallel.
- The host uses `/switch <room>` to alternate between conversations.

### Group rooms

- Admit **multiple peers** with explicit host approval.
- The host converts a room with `/group <room>`.
- New peers receive `pending` until the host runs `/allow <alias>`.
- The host can move peers between rooms with `/move <alias> <room>` (pre-approved).
- Messages are re-encrypted by the host for each recipient in the room.
- After every join/leave, the server sends `peerlist` to all peers in the room.

### Room discovery

- Peers receive the server's group room list after connecting (`roomlist`).
- Before joining, they can query all rooms and their status (`listrooms`).
- The list never exposes connected peer names — only counts.

---

## PGP key model

```
Each user has:
  - 1 PGP key pair (public + private)  RSA-4096
  - The private key NEVER leaves the device
  - The public key is exchanged during the handshake

To encrypt a message to B:
  encrypt(plaintext, pubkey_B) + sign(plaintext, privkey_A)  →  Sign-then-Encrypt

To decrypt a message from A:
  decrypt(payload, privkey_B) + verify_signature(payload, pubkey_A)
  → Discard if signature invalid; never display unverified content
```

Secure private key storage uses each OS's native mechanism:

| Platform | Mechanism |
|----------|-----------|
| macOS    | Keychain Services |
| Windows  | DPAPI |
| Linux    | libsecret (SecretService DBus) |
| CLI      | `0600` file in config directory (`platformdirs`) |

The passphrase protects the private key on disk and is only held in memory
during the active session. Never written to disk.

### Identity reset

Each client must provide a way to delete the keypair and generate a new one:

- **CLI:** `python -m stealth_cli --reset`
- **macOS:** "Reset identity" button on the unlock screen and in the hub

The reset deletes keys from disk/Keychain and any saved config, then launches
the setup wizard. The previous fingerprint is invalidated; peers must re-verify
the new one out-of-band.

---

## Design decisions

### No central server
**Decision:** direct peer-to-peer model (one acts as host).
**Reason:** eliminates metadata leakage risk from a relay server.
**Consequence:** the host needs an accessible IP/port. Tailscale or port
forwarding can be used for internet connections.

### No shared code between platforms
**Decision:** each platform implements the protocol with its own native stack.
**Reason:** avoids cross-platform dependencies that would complicate the build
and distribution.
**Consequence:** protocol logic must be perfectly specified in `docs/protocol.md`
to guarantee interoperability.

### PGP over ad-hoc solutions
**Decision:** OpenPGP (RFC 4880) with established libraries (pgpy, ObjectivePGP).
**Reason:** open standard, audited, with support on all target platforms.
**Consequence:** PGP libraries differ per platform; interoperability depends on
following the standard, not the library.

### Out-of-band identity verification
**Decision:** no PKI or key directory. Verification is manual.
**Reason:** any centralised key server is a point of failure and trust.
**Consequence:** users must compare fingerprints over an independent channel
(in person, by phone) before trusting a conversation.

### Group rooms with host relay
**Decision:** in group rooms the host re-encrypts and forwards messages.
**Reason:** peers do not have each other's public keys — only the host's.
**Consequence:** the host sees plaintext during relay. This is documented and
inherent to the trust model without a key server.

### Graceful shutdown
**Decision:** send `bye` to all peers before closing the app.
**Reason:** peers should not experience a silent connection drop.
**Consequence:** app termination may take one network round-trip; `applicationShouldTerminate`
(macOS) defers termination until the async shutdown completes.
