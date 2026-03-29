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

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console

from stealth_cli import config
from stealth_cli.crypto.keys import load_private_key
from stealth_cli.ui.chat import run_chat
from stealth_cli.ui.setup import run_setup

console = Console()
logger = logging.getLogger(__name__)

_STYLE = Style.from_dict({"prompt": "bold cyan"})

DEFAULT_PORT = 8765


# --------------------------------------------------------------------------- #
# CLI argument parsing                                                          #
# --------------------------------------------------------------------------- #


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stealth-cli",
        description="End-to-end encrypted PGP chat — no server, no accounts.",
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
    if args.host is not None:
        mode = "host"
        port = args.host
        uri = None
    elif args.join is not None:
        mode = "join"
        port = DEFAULT_PORT
        uri = args.join
    else:
        mode, port, uri = await _prompt_mode()

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


async def _prompt_mode() -> tuple[str, int, str | None]:
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
            return "host", port, None

        if choice in ("j", "join"):
            uri: str = await session.prompt_async(
                HTML("<prompt>Server URI (ws://host:port): </prompt>"),
            )
            return "join", DEFAULT_PORT, uri.strip()

        console.print("[red]Please enter 'h' or 'j'.[/red]")


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
