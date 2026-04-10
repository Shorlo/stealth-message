# stealth-message

End-to-end encrypted PGP chat. No central servers. No accounts. No content metadata.

---

## What it is

`stealth-message` lets two or more people communicate privately using OpenPGP encryption
(RFC 4880). Messages never pass through a relay server: one participant acts as **host**
(starts a WebSocket server) and the others connect directly to it.

**What the server cannot see — because it does not exist.**

---

## Features

- End-to-end encryption RSA-4096 + AES-256: only the recipient can decrypt.
- Digital signature on every message: sender identity cryptographically verifiable.
- No central server: direct peer-to-peer model (host + peers).
- No accounts or registration: identity is the PGP key.
- Private keys stored with `0600` permissions or in Keychain; passphrase only in memory.
- **1-on-1 rooms** — exactly one peer per room; access denied if occupied.
- **Group rooms** — multiple peers with explicit host approval.
- Room discovery before connecting (`listrooms` / `roomsinfo`).
- Hot peer movement between rooms (`/move`).
- Host-initiated peer disconnect (`kick` / `/disconnect`).
- Identity reset: wipes the keypair and generates a new one (`--reset` / UI button).
- Graceful shutdown: sends `bye` to all peers when the app closes.
- Four native clients interoperating through a common protocol (v0.8).

---

## Available clients

| Platform   | Technology           | Directory    | Status        |
|------------|----------------------|--------------|---------------|
| Terminal   | Python 3.10+         | `cli/`       | Functional    |
| macOS      | Swift 5.9+ / SwiftUI | `macos/`     | Functional    |
| Windows 11 | C# 12 / WinUI 3      | `windows/`   | Pending       |
| Linux      | Python 3.10+ / GTK4  | `linux/`     | Pending       |

All clients implement the same protocol (`docs/protocol.md`) and can communicate with
each other regardless of platform.

---

## CLI client (`cli/`)

### Installation

```bash
pip install stealth-message-cli
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://syberiancode.com/stealth-message/install.ps1 | iex"
```

Requires Python 3.10 or later. Published on [PyPI](https://pypi.org/project/stealth-message-cli/) as `stealth-message-cli 0.1.7`.

### First run

```bash
stealth-cli
```

A setup wizard starts automatically and asks for:

- **Alias** — your display name, visible to peers (max 64 characters).
- **Passphrase** — protects your private key on disk (min 8 characters).

An RSA-4096 key pair is generated and saved. Your **fingerprint** is shown at
the end — share it with peers over an independent channel (phone, in person)
so they can verify your identity.

### Starting a session

**Host** — one participant starts the server:

```bash
stealth-cli --host               # port 8765 (default)
stealth-cli --host 9000          # custom port
stealth-cli --host --rooms a,b,c # pre-create named rooms
```

**Join** — everyone else connects to the host:

```bash
stealth-cli --join ALICE_IP:8765
stealth-cli --join ALICE_IP:8765 --room a
# ws:// prefix is added automatically if omitted
```

**Interactive mode** (no flags) — the program walks you through host/join
selection, shows available rooms fetched from the server, and asks which one
to join.

### Room types

**1-on-1 rooms** — admit exactly one peer. A second connection attempt gets
error 4006 (room occupied). The host can manage multiple 1-on-1 rooms in
parallel and switch between them with `/switch`.

**Group rooms** — admit multiple peers with host approval. Convert any room
to group mode at runtime:

```
[Alice@lobby] /group team
[Alice@lobby] /move Bob team    # invite Bob — no approval prompt
```

### Room names

Room names can contain any characters, including spaces (up to 64 chars).
On the command line, quote names that contain spaces:

```bash
stealth-cli --host --rooms "sala 1","sala 2"
stealth-cli --join ALICE_IP:8765 --room "sala 1"
```

Inside the chat, quotes are not needed — everything after the command is
the room name:

```
/switch sala 1
/new sala 1
```

### Chat commands

| Command | Who | Action |
|---------|-----|--------|
| `/switch <room>` | all | Change active room |
| `/rooms` | all | List all known rooms and their status |
| `/fp` | all | Show the current peer's PGP fingerprint |
| `/help` | all | Show available commands |
| `/quit` | all | Close the session cleanly |
| `/new <room>` | host | Create a new 1-on-1 room at runtime |
| `/group <room>` | host | Convert a room to group mode |
| `/move <alias> <room>` | host | Move a peer to a different room |
| `/allow <alias>` | host | Approve a pending join request |
| `/deny <alias>` | host | Deny a pending join request |
| `/disconnect [alias]` | host | Force-disconnect a peer |

### Identity reset

```bash
stealth-cli --reset
```

Wipes the stored key pair and config and immediately runs the setup wizard
so you can choose a new alias and generate a fresh key in one step.

### Full manual

```bash
stealth-cli --manual
```

---

## macOS client (`macos/`)

Native SwiftUI app for macOS 13 (Ventura) and later.

### Requirements

- macOS 13.0+
- Xcode 15+
- Swift 5.9+

The project uses [ObjectivePGP](https://github.com/krzyzanowskim/ObjectivePGP)
(v0.99.4) via Swift Package Manager for all PGP operations, and
`URLSessionWebSocketTask` for WebSocket — no external networking dependencies.
Private keys are stored in the Keychain
(`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`), never on disk.

### Opening the project

```bash
open macos/StealthMessage/StealthMessage.xcodeproj
```

Xcode resolves the SPM dependency automatically on first open.

### Current status

| Component | Status |
|-----------|--------|
| `Crypto/` — PGPKeyManager, KeychainStore | Done |
| `Network/` — StealthServer, StealthClient, wire types | Done |
| `UI/` — ViewModels, Views, setup wizard, chat | Done |
| Tests — CryptoTests, NetworkTests | Done |

All layers are complete and interoperable with the CLI.

---

## Connecting over the internet

To connect outside the local network there are two options:

**Port forwarding** — open port 8765 on your router and share your public IP with peers.
If your ISP uses CG-NAT (the WAN IP shown in your router differs from `curl ifconfig.me`),
this option will not work.

**Tailscale (recommended)** — creates a WireGuard tunnel between devices without any
router configuration. Install Tailscale on all machines, use `tailscale status` to see
the `100.x.x.x` addresses, and connect using those.

See the "Connecting over the internet" section of the manual (`--manual`) for step-by-step
instructions.

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full description of the system, the layers
of each sub-project, and design decisions.

The communication protocol is specified in [docs/protocol.md](docs/protocol.md).
This document is the source of truth: if code and protocol conflict, the protocol wins.

---

## Security

See [SECURITY.md](SECURITY.md) for the full security policy and the vulnerability
reporting process.

**Do not open public issues to report security vulnerabilities.**

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution guide, code standards,
and pull request process.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the project history.

---

## License

Copyright © 2026 Javier Sainz de Baranda y Goñi.

This program is [free software](https://www.gnu.org/philosophy/free-sw.html): you can
redistribute it and/or modify it under the terms of the
[GNU General Public License](https://www.gnu.org/licenses/gpl-3.0.html) as published by
the [Free Software Foundation](https://www.fsf.org), either version 3 of the License,
or (at your option) any later version.

**This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.** See the GNU General Public License for more details.

You should have received a [copy](LICENSE) of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.

For projects where the terms of the GNU General Public License prevent the use of this
software or require unwanted publication of the source code of commercial products, you
may [apply for a special license](mailto:info@syberiancode.com?subject=stealth-message).
