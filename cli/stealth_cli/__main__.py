"""Entry point for stealth-message CLI.

Usage:
    python -m stealth_cli              # auto-detect mode (prompts if needed)
    python -m stealth_cli --host       # host mode on default port 8765
    python -m stealth_cli --host 9000  # host mode on custom port
    python -m stealth_cli --join ws://192.168.1.10:8765

Flow:
    1. First use  → run setup wizard → save keypair → open chat
    2. Known user → ask passphrase   → open chat
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import warnings

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from stealth_cli import config
from stealth_cli.crypto.keys import load_private_key
from stealth_cli.network.client import query_rooms
from stealth_cli.ui.chat import run_chat
from stealth_cli.ui.setup import run_setup

console = Console()
logger = logging.getLogger(__name__)

# Suppress known pgpy warnings that do not affect crypto correctness.
# These are unimplemented features inside pgpy itself (self-sig parsing,
# revocation checks, flags) and a benign compression preference mismatch.
warnings.filterwarnings("ignore", message=".*compression algorithm.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Self-sigs verification.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Revocation checks.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Flags.*checks are not yet implemented.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*TripleDES.*", category=UserWarning)

_STYLE = Style.from_dict({"prompt": "bold cyan"})

DEFAULT_PORT = 8765


# --------------------------------------------------------------------------- #
# CLI argument parsing                                                          #
# --------------------------------------------------------------------------- #


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stealth-cli",
        description="End-to-end encrypted PGP chat — no server, no accounts.",
        epilog="Run with --manual for the full user guide.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--host",
        nargs="?",
        const=DEFAULT_PORT,
        type=int,
        metavar="PORT",
        help=f"Host a chat session on PORT (default: {DEFAULT_PORT})",
    )
    mode.add_argument(
        "--join",
        metavar="URI",
        help="Join a session at ws://HOST:PORT",
    )
    mode.add_argument(
        "--manual",
        action="store_true",
        help="Show the full user manual and exit",
    )

    parser.add_argument(
        "--rooms",
        metavar="ROOMS",
        help=(
            "Comma-separated list of room names to create (host mode only). "
            "Example: --rooms pepe,juan  Each room admits exactly one peer."
        ),
    )
    parser.add_argument(
        "--room",
        metavar="ROOM",
        default="default",
        help="Room to join (join mode only, default: 'default')",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the saved keypair and start the setup wizard to create a new identity",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


# --------------------------------------------------------------------------- #
# Async main                                                                    #
# --------------------------------------------------------------------------- #


async def _async_main() -> int:
    args = _parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if args.manual:
        _print_manual()
        return 0

    # ------------------------------------------------------------------ #
    # Step 0 — --reset: wipe keypair and force the setup wizard.          #
    # ------------------------------------------------------------------ #
    if args.reset:
        if config.is_first_use():
            console.print("[dim]No saved identity found — nothing to reset.[/dim]")
        else:
            config.delete_keypair()
            console.print("[yellow]Identity deleted.[/yellow] Starting setup wizard…\n")

    # ------------------------------------------------------------------ #
    # Step 1 — First use: run the setup wizard.                           #
    # ------------------------------------------------------------------ #
    if config.is_first_use():
        alias, armored_private, passphrase = await run_setup()
    else:
        # ------------------------------------------------------------------ #
        # Step 2 — Known user: load keys and ask for passphrase.             #
        # ------------------------------------------------------------------ #
        alias = config.load_alias() or "unknown"
        armored_private = config.load_armored_private()
        passphrase = await _prompt_passphrase(alias)

        # Validate passphrase eagerly so the user gets immediate feedback.
        if not _validate_passphrase(armored_private, passphrase):
            console.print("[red]Wrong passphrase. Exiting.[/red]")
            return 1

    # ------------------------------------------------------------------ #
    # Step 3 — Determine chat mode from CLI flags or interactive prompt.  #
    # ------------------------------------------------------------------ #
    rooms: list[str] | None = None
    room: str = "default"

    if args.host is not None:
        mode = "host"
        port = args.host
        uri = None
        if args.rooms:
            rooms = [r.strip() for r in args.rooms.split(",") if r.strip()]
    elif args.join is not None:
        mode = "join"
        port = DEFAULT_PORT
        uri = args.join
        if not uri.startswith("ws://") and not uri.startswith("wss://"):
            uri = "ws://" + uri
        room = args.room or "default"
    else:
        mode, port, uri, rooms, room = await _prompt_mode()

    # ------------------------------------------------------------------ #
    # Step 4 — Launch the chat screen.                                    #
    # ------------------------------------------------------------------ #
    try:
        await run_chat(
            mode=mode,        # type: ignore[arg-type]
            alias=alias,
            armored_private=armored_private,
            passphrase=passphrase,
            port=port,
            uri=uri,
            rooms=rooms,
            room=room,
        )
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if args.debug:
            raise
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    return 0


# --------------------------------------------------------------------------- #
# Interactive helpers                                                           #
# --------------------------------------------------------------------------- #


async def _print_room_list(uri: str) -> None:
    """Query the server for room info and print a formatted list."""
    from rich.table import Table

    console.print(f"[dim]Fetching rooms from[/dim] [bold]{uri}[/bold][dim]…[/dim]")
    rooms = await query_rooms(uri)
    if not rooms:
        console.print("[yellow]  Could not retrieve room list (server may not support it).[/yellow]")
        return

    t = Table.grid(padding=(0, 2))
    t.add_column(no_wrap=True)   # room name
    t.add_column(no_wrap=True)   # kind badge
    t.add_column()               # status

    for room in rooms:
        room_id = str(room.get("id", ""))
        kind = str(room.get("kind", "1:1"))
        peers = int(room.get("peers", 0))

        if kind == "group":
            badge = "[yellow]group[/yellow]"
            if peers == 0:
                status = "[dim]empty — host only[/dim]"
            elif peers == 1:
                status = f"[dim]host + {peers} user[/dim]"
            else:
                status = f"[dim]host + {peers} users[/dim]"
        else:
            badge = "[cyan]1:1[/cyan]"
            available = bool(room.get("available", True))
            if available:
                status = "[green]available[/green]"
            else:
                status = "[red]occupied[/red]"

        t.add_row(f"  [bold]{room_id}[/bold]", badge, status)

    console.print()
    console.print("[bold]Available rooms:[/bold]")
    console.print(t)
    console.print()


async def _prompt_passphrase(alias: str) -> str:
    """Ask the user for their passphrase at startup."""
    session: PromptSession[str] = PromptSession(style=_STYLE)
    console.print(f"[cyan]Welcome back,[/cyan] [bold]{alias}[/bold]")
    passphrase: str = await session.prompt_async(
        HTML("<prompt>Passphrase: </prompt>"),
        is_password=True,
    )
    return passphrase


def _validate_passphrase(armored_private: str, passphrase: str) -> bool:
    """Return True if the passphrase successfully unlocks the private key."""
    try:
        load_private_key(armored_private, passphrase)
        return True
    except Exception:
        return False


async def _prompt_mode() -> tuple[str, int, str | None, list[str] | None, str]:
    """Interactively ask whether to host or join."""
    session: PromptSession[str] = PromptSession(style=_STYLE)

    console.print()
    console.print("[bold]What do you want to do?[/bold]")
    console.print("  [cyan]h[/cyan]  Host a new session")
    console.print("  [cyan]j[/cyan]  Join an existing session")
    console.print()

    while True:
        choice: str = await session.prompt_async(
            HTML("<prompt>Choice [h/j]: </prompt>"),
        )
        choice = choice.strip().lower()
        if choice in ("h", "host"):
            port_str: str = await session.prompt_async(
                HTML(f"<prompt>Port [{DEFAULT_PORT}]: </prompt>"),
            )
            port = int(port_str.strip()) if port_str.strip().isdigit() else DEFAULT_PORT

            rooms_str: str = await session.prompt_async(
                HTML("<prompt>Rooms (comma-separated, blank for single): </prompt>"),
            )
            rooms_str = rooms_str.strip()
            rooms: list[str] | None = (
                [r.strip() for r in rooms_str.split(",") if r.strip()]
                if rooms_str
                else None
            )
            return "host", port, None, rooms, "default"

        if choice in ("j", "join"):
            uri: str = await session.prompt_async(
                HTML("<prompt>Server URI (ws://host:port): </prompt>"),
            )
            uri = uri.strip()
            if uri and not uri.startswith("ws://") and not uri.startswith("wss://"):
                uri = "ws://" + uri
            await _print_room_list(uri)
            room_str: str = await session.prompt_async(
                HTML("<prompt>Room [default]: </prompt>"),
            )
            room = room_str.strip() or "default"
            return "join", DEFAULT_PORT, uri, None, room

        console.print("[red]Please enter 'h' or 'j'.[/red]")


# --------------------------------------------------------------------------- #
# Manual                                                                        #
# --------------------------------------------------------------------------- #


def _print_manual() -> None:
    """Print the full user manual with Rich formatting."""
    c = Console()

    # Header
    c.print()
    c.print(
        Panel(
            Text.assemble(
                ("stealth-message", "bold white"),
                " — ",
                ("User Manual", "bold cyan"),
                "\n",
                ("End-to-end encrypted PGP chat. No server. No accounts. No metadata.", "dim"),
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )

    manual = """\
## How it works

Participants communicate directly, machine to machine, over a WebSocket
connection. Every message is encrypted with the recipient's PGP public key
and signed with the sender's private key before leaving the machine.
No server ever sees the content.

One participant acts as **host** (starts the server) and the others **join**.
All roles send and receive messages equally once connected.

---

## First use

The first time you run the program, a setup wizard starts automatically:

```
python -m stealth_cli
```

The wizard asks for:

- **Alias** — your display name, visible to peers (max 64 chars).
- **Passphrase** — protects your private key on disk (min 8 chars, asked twice).

An RSA-4096 key pair is then generated and saved to disk:

- **macOS:** `~/Library/Application Support/stealth-message/`
- **Linux / WSL:** `~/.config/stealth-message/`

Your **fingerprint** is shown at the end. Share it with your peers over an
independent channel (in person, by phone) so they can verify your identity.

---

## Starting a session

### Alice — host mode (single 1-on-1 room)

```
python -m stealth_cli --host           # default port 8765
python -m stealth_cli --host 9000      # custom port
```

### Alice — host mode (multiple rooms)

```
python -m stealth_cli --host --rooms bob,carol,team
```

This creates three independent rooms. Peers connect to a specific room by name.

### Bob — join mode

```
python -m stealth_cli --join ALICE_IP:8765          # ws:// added automatically
python -m stealth_cli --join ALICE_IP:8765 --room bob
```

### Interactive mode (no flags)

```
python -m stealth_cli
```

When joining interactively, after entering the server address the program
fetches and displays the available rooms before asking which one to join:

```
Available rooms:
  lobby   1:1    available
  work    1:1    occupied
  team    group  host + 2 users
```

Room names are shown but connected user names are never disclosed.

---

## Room types

### 1-on-1 rooms (default)

Each room admits exactly **one peer**. A second peer trying to connect gets
error 4006 (room occupied). The host can hold multiple 1-on-1 rooms in parallel
and switch between them with `/switch`.

### Group rooms

Group rooms admit **multiple peers** with host approval:

```
[Alice@room1] /group team      # convert a room to group mode
[Alice@room1] /move Bob team   # invite Bob — pre-approved, no prompt
```

When a new peer tries to join a group room that already has someone:

```
  ⚠  Join request: Carol wants to enter room team
     FP: XXXX XXXX XXXX ...
     /allow Carol  or  /deny Carol
```

- `/allow Carol` → Carol enters the room
- `/deny Carol` → Carol is rejected

In group rooms, messages are forwarded to **all** other peers in the room.
The host re-encrypts each message for each recipient individually.

### Room discovery

After connecting, every peer receives the list of group rooms on the server.
Running `/rooms` shows all known rooms including ones not yet visited:

```
▶ team       ✓ Alice, Bob
  lobby      waiting for peer…
  open-chat  group  /switch to join
```

---

## Connecting over the internet

The host needs a publicly reachable IP. Two options:

**Option A — Port forwarding (no third-party software)**

1. Find your public IP: `curl ifconfig.me`
2. In your router: NAT → Port Forwarding → TCP port 8765 → your local IP.
3. Give peers: `ALICE_PUBLIC_IP:8765`
4. Close the port forwarding rule when you finish.

> If port forwarding does not work, your ISP may use CG-NAT.
> Check: compare the WAN IP shown in your router with `curl ifconfig.me`.
> If they differ, contact your ISP and request a dedicated public IP.

**Option B — Tailscale (no port forwarding)**

Tailscale creates a private WireGuard tunnel directly between machines.
No router configuration needed.

1. All participants install Tailscale (free for personal use).
2. Alice shares her device with peers from the Tailscale web console
   ("Share node" — they only see Alice's machine, not her whole network).
3. Run `tailscale status` to see each other's `100.x.x.x` addresses.
4. Alice: `python -m stealth_cli --host`
5. Others: `python -m stealth_cli --join ALICE_TAILSCALE_IP:8765 --room <name>`
6. Revoke the share when done.

> With Tailscale, messages travel encrypted by WireGuard AND by PGP —
> two independent layers.

---

## Chat commands — all users

| Command | Action |
|---------|--------|
| `/fp` | Show the current peer's PGP fingerprint |
| `/rooms` | List all known rooms and their status |
| `/switch <room>` | Change active room (join mode: reconnects; host mode: changes focus) |
| `/help` | Show available commands |
| `/quit` or `/exit` or `/q` | Close the session cleanly |
| `Ctrl+C` | Also closes the session |

## Chat commands — host only

| Command | Action |
|---------|--------|
| `/new <room>` | Create a new 1-on-1 room at runtime |
| `/group <room>` | Convert a room to group mode (multiple peers) |
| `/move <alias> <room>` | Move a peer to a different room (pre-approved, no prompt) |
| `/allow <alias>` | Approve a pending join request |
| `/deny <alias>` | Deny a pending join request |
| `/pending` | List all pending join requests |

---

## Example: Alice hosts, Bob and Carol join separate 1-on-1 rooms

**Alice (host):**
```
python -m stealth_cli --host --rooms bob,carol
```

**Bob:**
```
python -m stealth_cli --join ALICE_IP:8765 --room bob
```

**Carol:**
```
python -m stealth_cli --join ALICE_IP:8765 --room carol
```

Alice uses `/switch bob` and `/switch carol` to alternate between conversations.
Neither Bob nor Carol can see each other's messages.

---

## Example: Alice hosts a group room with Bob and Carol

**Alice (host):**
```
python -m stealth_cli --host --rooms lobby,team
[Alice@lobby] /group team       # convert team to group mode
[Alice@lobby] /move Bob team    # move Bob — pre-approved
```

**Bob** (already connected to lobby):
```
  ↪ Host is moving you to room team…
  ✓ Switched to room team — connected to Alice
```

**Carol** (joins directly):
```
python -m stealth_cli --join ALICE_IP:8765 --room team
  ⏳ Waiting for host to approve your entry into room team…
```

**Alice approves:**
```
  ⚠  Join request: Carol wants to enter room team
[Alice@team] /allow Carol
```

Now Alice, Bob and Carol are all in room `team`. Any message sent by
any of them reaches all the others.

---

## Identity verification

After connecting, both sides see the peer's alias and fingerprint:

```
  ✓ Connected to Alice  [room: bob]
    Fingerprint: F7B3 E55E EA71 1A09 C6C5 0BB7 BA84 DD16 8A77 AA9A
```

**Always verify the fingerprint over an independent channel before trusting
the conversation.** If the fingerprints match, the connection is authentic.
If they do not, disconnect immediately.

---

## Security model

| Property | Guarantee |
|----------|-----------|
| Message confidentiality | Only the recipient can decrypt (RSA-4096 + AES-256) |
| Message authenticity | Every message is signed; invalid signatures are rejected |
| Group room relay | Host re-encrypts per recipient; host sees plaintext during relay |
| Room isolation | Peers in different rooms cannot read each other's messages |
| Room discovery | Room list shows counts only — connected user names are never disclosed |
| Access control | Group rooms require explicit host approval for each new peer |
| Forward secrecy | Not yet implemented (planned for protocol v2) |
| Private key storage | Disk-encrypted with your passphrase (AES-256) |
| Passphrase | Never written to disk, only held in memory during the session |
| No accounts | Identity is the PGP key — no username, email, or phone number |

---

## Subsequent uses

From the second run onward, the wizard is skipped. The program asks only
for the passphrase:

```
Welcome back, Alice
Passphrase: ****
```

A wrong passphrase exits immediately without loading any data.

---

## Flags reference

| Flag | Description |
|------|-------------|
| `--host [PORT]` | Host a session on PORT (default 8765) |
| `--rooms ROOMS` | Comma-separated room names (host mode) |
| `--join URI` | Join a session at host:port (ws:// added automatically) |
| `--room ROOM` | Room to join (join mode, default: "default") |
| `--manual` | Show this manual |
| `--debug` | Enable verbose debug logging |
| `--help` | Show short usage summary |

---

## Running the tests

```
cd cli
source .venv/bin/activate
pytest tests/ -v
```
"""

    c.print(Padding(Markdown(manual), (0, 2)))
    c.print()


# --------------------------------------------------------------------------- #
# Synchronous entry point                                                       #
# --------------------------------------------------------------------------- #


def main() -> None:
    """Synchronous entry point for the stealth-cli console script."""
    try:
        code = asyncio.run(_async_main())
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
