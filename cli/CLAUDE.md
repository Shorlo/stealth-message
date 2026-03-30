# cli/CLAUDE.md — stealth-message CLI (reference implementation)

Python terminal client. Fully functional. All other platform clients must implement
the same protocol (`docs/protocol.md`) and replicate the same crypto behaviour.

---

## Stack

| Concern      | Library / tool                          |
|--------------|-----------------------------------------|
| Python       | 3.10+ (tested on 3.12)                  |
| PGP          | `pgpy` — pure Python, no system GnuPG  |
| WebSocket    | `websockets` 16 (asyncio API)           |
| Terminal UI  | `rich` (output) + `prompt_toolkit` (input) |
| Config paths | `platformdirs`                          |
| Packaging    | `pip install -e .` / PyInstaller binary |

---

## Structure

```
cli/
├── pyproject.toml
├── stealth_cli/
│   ├── __main__.py      entry point; arg parsing; interactive mode wizard;
│   │                    _print_room_list() fetches rooms before join prompt;
│   │                    ws:// auto-prefixed if missing
│   ├── config.py        platformdirs paths; save/load keypair (privkey 0600);
│   │                    is_first_use(); passphrase NEVER written to disk
│   ├── exceptions.py    StealthError, SignatureError, ProtocolError(msg, code)
│   ├── crypto/
│   │   ├── keys.py      generate_keypair(alias, passphrase) → (armored_pub, armored_priv)
│   │   │                load_private_key(armored, passphrase) → PGPKey (locked)
│   │   │                get_fingerprint(armored_pub) → "XXXX XXXX …" (groups of 4)
│   │   └── messages.py  encrypt(plaintext, recipient_pub, sender_priv) → str
│   │                    decrypt(payload, recipient_priv, sender_pub) → str
│   │                    raises SignatureError if sig invalid
│   ├── network/
│   │   ├── server.py    StealthServer — WebSocket host; room management;
│   │   │                handles listrooms before handshake; sends roomlist after connect
│   │   └── client.py    StealthClient — WebSocket joiner; approval loop for group rooms;
│   │                    query_rooms(uri) — standalone async fn, no auth required
│   └── ui/
│       ├── chat.py      ChatScreen; _printer_task; _switch_join_room; _update_known_groups;
│       │                all chat commands; Rich table help; ANSI erase before outgoing msg
│       └── setup.py     first-use wizard: alias, passphrase, RSA-4096 keygen, show fp
└── tests/
    ├── test_crypto.py   (21 tests)
    └── test_network.py  (43 tests)   — 64 total, all must pass
```

---

## Key patterns

**Crypto layer:**
- All crypto functions accept/return `str` (ASCII-armored PGP or plaintext). No `bytes` in public API.
- Private key is always locked on disk. Unlock only per-operation: `with privkey.unlock(passphrase): ...`
- Sign-then-encrypt on send. Decrypt-then-verify on receive. Discard on `SignatureError`.

**Network layer:**
- `StealthServer` reads first WebSocket frame manually to detect `listrooms` vs `hello`.
- `_do_handshake(ws, first_msg=...)` accepts the already-parsed first message to avoid double-read.
- Group room join: server sends `pending` after `hello`; client detects it via 0.5 s peek in `_handshake()`; `connect()` blocks in `_approval_loop()` until `approved` or `error`.
- `on_message` callback signature: `async def cb(plaintext: str, sender: str | None) -> None` — `sender` is set only for group room relay messages.
- `on_roomlist` callback: `async def cb(group_rooms: list[str]) -> None`
- Before disconnecting a client during `/switch` or `/move`, null out `on_disconnected` first to prevent `_stop_event` from firing.

**UI layer:**
- `_print_queue: asyncio.Queue[object]` — accepts `Text` or `Table` (Rich renderables).
- `_printer_task` runs as background asyncio task; sentinel `None` signals exit.
- `asyncio.wait({prompt_task, stop_task}, FIRST_COMPLETED)` — prompt never interrupted by incoming messages.
- ANSI erase before printing outgoing: `sys.stdout.write("\x1b[1A\x1b[2K\r")`.
- `_print_help()` uses `Table.grid` — never inline markup strings.
- Layer rule: `crypto/` and `network/` never import from `ui/`.

---

## Commands

```bash
cd cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m stealth_cli                         # interactive
python -m stealth_cli --host [PORT]
python -m stealth_cli --host --rooms a,b,c
python -m stealth_cli --join HOST:PORT [--room NAME]
python -m stealth_cli --manual

pytest tests/ -v                              # must all pass before commit
ruff check . && black . && mypy stealth_cli/
```

---

## Constraints

- `asyncio` for all I/O. No blocking calls in the event loop.
- `logging` for internal diagnostics. No `print()` in library code.
- Type hints required on all public functions. `mypy` must pass.
- Tests use generated keys with a fixed test passphrase — never real credentials.
- Key storage: `platformdirs.user_config_dir("stealth-message")` + `/keys/private.asc` (0600).
- Config: `config.json` with `alias` field only. No passphrase, no secrets.
