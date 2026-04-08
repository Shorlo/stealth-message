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
| macOS      | Swift 5.9+ / SwiftUI | `macos/`     | In development|
| Windows 11 | C# 12 / WinUI 3      | `windows/`   | Pending       |
| Linux      | Python 3.10+ / GTK4  | `linux/`     | Pending       |

All clients implement the same protocol (`docs/protocol.md`) and can communicate with
each other regardless of platform.

---

## Quick start (CLI)

```bash
cd cli
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m stealth_cli
```

On first run the setup wizard starts: choose an alias and a passphrase.
An RSA-4096 key pair is generated and your fingerprint is shown.

**Host:**
```bash
python -m stealth_cli --host               # default port 8765
python -m stealth_cli --host --rooms a,b   # multiple rooms
```

**Join:**
```bash
python -m stealth_cli --join ALICE_IP:8765 --room a
# ws:// prefix is added automatically if omitted
```

**Full manual:**
```bash
python -m stealth_cli --manual
```

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
