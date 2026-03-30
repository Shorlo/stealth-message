# linux/CLAUDE.md — stealth-message Linux

Native Linux GTK4 client. **Not yet implemented** — directory contains only this file.
Implement `docs/protocol.md` exactly. Use `cli/` as the reference for crypto behaviour,
room model, and wire format. The Python stack is identical — crypto and network modules
can be shared or symlinked from `cli/stealth_cli/`.

---

## Target stack

| Concern        | Choice                                                |
|----------------|-------------------------------------------------------|
| Language       | Python 3.10+                                          |
| UI             | GTK4 via `PyGObject`                                  |
| Event loop     | `asyncio` integrated with GTK via `gbulb`             |
| PGP            | `pgpy` — same as CLI, no duplication                  |
| WebSocket      | `asyncio` + `websockets` — same as CLI                |
| Secret storage | `libsecret` (SecretService DBus) via `PyGObject`      |
| Config paths   | `platformdirs`                                        |
| Distribution   | `.deb`, Flatpak, or AppImage                          |

---

## Sharing code with cli/

`crypto/` and `network/` modules are identical to `cli/stealth_cli/crypto/` and
`cli/stealth_cli/network/`. Options (decide when implementing):

1. **Symlinks** — `linux/stealth_gtk/crypto → ../cli/stealth_cli/crypto` (fast, dev-friendly)
2. **Shared internal package** — extract `stealth_core/` at monorepo root when complexity warrants it

Do not copy-paste. One implementation, one place.

---

## What to implement

Follow `docs/protocol.md` exactly. Crypto and network behaviour is identical to `cli/`.
See `cli/CLAUDE.md` for all patterns (key unlock, sign-then-encrypt, group room flow,
`sender` field handling, `listrooms` before join, etc.).

**UI layer (GTK4):**
- Show room list (kind + peer count, no peer names) before joining.
- Show fingerprint prominently after connect for out-of-band verification.
- `Gtk.Entry.set_visibility(False)` for passphrase fields. Clear with `set_text("")` on close.
- GTK signals for widget communication — no global state.
- All I/O via `asyncio`. Never block the GTK main thread.

---

## Constraints

- `gbulb.install(gtk=True)` before `Gtk.Application.run()` — integrates asyncio with GTK loop.
- Same Python conventions as CLI: PEP 8, `black`, `ruff`, `mypy`, type hints.
- Secret storage: `libsecret` via `secret_password_store_sync`. Fallback to `0600` file
  at `platformdirs.user_config_dir("stealth-message")/keys/` if libsecret unavailable.
- GTK Application ID: `com.stealthmessage.app` (reverse DNS).
- Flatpak manifest must declare `org.freedesktop.secrets` permission for libsecret.
- Tests: test `crypto/` and `network/` in isolation — do not instantiate GTK windows in tests.

---

## System dependencies (Ubuntu/Debian)

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libsecret-1-dev
pip install gbulb
```

Supported: Ubuntu 22.04+, Debian 12+, Elementary OS 7+.
