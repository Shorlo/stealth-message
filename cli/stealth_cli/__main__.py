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
            room_str: str = await session.prompt_async(
                HTML("<prompt>Room [default]: </prompt>"),
            )
            room = room_str.strip() or "default"
            return "join", DEFAULT_PORT, uri.strip(), None, room

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

Two people communicate directly, machine to machine, over a WebSocket
connection. Every message is encrypted with the recipient's PGP public key
and signed with the sender's private key before leaving the machine.
No server ever sees the content.

One participant acts as **host** (starts the server) and the other **joins**.
Both roles send and receive messages equally once connected.

---

## First use

The first time you run the program, a setup wizard starts automatically:

```
python -m stealth_cli
```

The wizard asks for:

- **Alias** — your display name, visible to the other participant (max 64 chars).
- **Passphrase** — protects your private key on disk (min 8 chars, asked twice).

An RSA-4096 key pair is then generated and saved to disk:

- **macOS:** `~/Library/Application Support/stealth-message/`
- **Linux / WSL:** `~/.config/stealth-message/`

Your **fingerprint** is shown at the end. Share it with your peer over an
independent channel (in person, by phone) so they can verify your identity.

---

## Starting a session

### Alice — host mode

```
python -m stealth_cli --host           # default port 8765
python -m stealth_cli --host 9000      # custom port
```

Alice's terminal shows her public IP and port to give to Bob.

### Bob — join mode

```
python -m stealth_cli --join ws://ALICE_IP:8765
```

### Interactive mode (no flags)

```
python -m stealth_cli
```

The program asks whether to host or join and prompts for the address.

---

## Connecting over the internet

The host needs a publicly reachable IP. Two options:

**Option A — Port forwarding (no third-party software)**

1. Find your public IP:
   `curl ifconfig.me`
2. In your router: NAT → Port Forwarding → TCP port 8765 → your local IP.
3. Give Bob: `ws://YOUR_PUBLIC_IP:8765`
4. Close the port forwarding rule when you finish.

> If port forwarding does not work, your ISP may use CG-NAT.
> Check: compare the WAN IP shown in your router with `curl ifconfig.me`.
> If they differ, contact your ISP and request a dedicated public IP.

**Option B — Tailscale (no port forwarding)**

Tailscale creates a private WireGuard tunnel directly between the two
machines. No router configuration needed.

1. Both install Tailscale (free for personal use).
2. Alice shares her device with Bob from the Tailscale web console
   ("Share node" — Bob only sees Alice's machine, not her whole network).
3. Run `tailscale status` to see each other's `100.x.x.x` addresses.
4. Alice: `python -m stealth_cli --host`
5. Bob: `python -m stealth_cli --join ws://ALICE_TAILSCALE_IP:8765`
6. Revoke the share when done.

> With Tailscale, messages travel encrypted by WireGuard AND by PGP —
> two independent layers. Even if WireGuard were compromised, the PGP
> content remains unreadable.

---

## Chat commands

| Command | Action |
|---------|--------|
| `/fp`   | Show the peer's PGP fingerprint |
| `/help` | Show available commands |
| `/quit` or `/exit` or `/q` | Close the session cleanly |
| `Ctrl+C` | Also closes the session |

---

## Identity verification

After connecting, both sides see the peer's alias and fingerprint:

```
  ✓ Connected to Bob
    Fingerprint: B2C3 D4E5 F678 90AB CDEF 1234 5678 90AB CDEF 1234
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
| `--join URI` | Join a session at ws://host:port |
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
