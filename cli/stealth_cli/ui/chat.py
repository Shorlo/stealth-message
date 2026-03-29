"""Chat screen — rich output + prompt_toolkit input, host and join modes.

The screen coordinates Rich's live output and prompt_toolkit's async input
so that incoming messages do not break the user's input line.

Host mode (--host):
    Starts a StealthServer on the given port and waits for a peer to connect.

Join mode (--join <ws://...>):
    Connects a StealthClient to the given URI.

Usage (called by __main__.py)::

    await run_chat(mode="host", alias=alias, armored_private=priv,
                   passphrase=passphrase, port=8765)

    await run_chat(mode="join", alias=alias, armored_private=priv,
                   passphrase=passphrase, uri="ws://192.168.1.5:8765")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from stealth_cli.crypto.keys import get_fingerprint
from stealth_cli.network.client import StealthClient
from stealth_cli.network.server import StealthServer

logger = logging.getLogger(__name__)

console = Console(highlight=False)

_STYLE = Style.from_dict(
    {
        "prompt": "bold green",
        "label": "ansigreen",
    }
)

ChatMode = Literal["host", "join"]

# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #


async def run_chat(
    *,
    mode: ChatMode,
    alias: str,
    armored_private: str,
    passphrase: str,
    port: int = 8765,
    uri: Optional[str] = None,
) -> None:
    """Launch the interactive chat screen.

    Args:
        mode:           ``"host"`` or ``"join"``.
        alias:          Local user's display alias.
        armored_private: ASCII-armored private key (protected with passphrase).
        passphrase:     Passphrase for the private key.
        port:           TCP port to listen on (host mode only).
        uri:            WebSocket URI to connect to (join mode only).
    """
    screen = ChatScreen(alias=alias, armored_private=armored_private, passphrase=passphrase)

    if mode == "host":
        await screen.run_host(port=port)
    else:
        if uri is None:
            raise ValueError("uri is required in join mode")
        await screen.run_join(uri=uri)


# --------------------------------------------------------------------------- #
# ChatScreen                                                                    #
# --------------------------------------------------------------------------- #


class ChatScreen:
    """Manages the Rich + prompt_toolkit UI for one chat session."""

    def __init__(self, *, alias: str, armored_private: str, passphrase: str) -> None:
        self._alias = alias
        self._armored_private = armored_private
        self._passphrase = passphrase

        self._peer_alias: Optional[str] = None
        self._peer_fingerprint: Optional[str] = None
        self._stop_event = asyncio.Event()

        # Queues keep the output thread-safe when Rich prints from async callbacks.
        self._print_queue: asyncio.Queue[Optional[Text]] = asyncio.Queue()

    # ------------------------------------------------------------------ #
    # Host mode                                                            #
    # ------------------------------------------------------------------ #

    async def run_host(self, *, port: int) -> None:
        """Start a server, wait for one peer, then enter the chat loop."""
        server = StealthServer(
            self._alias,
            self._armored_private,
            self._passphrase,
        )

        peer_connected_event = asyncio.Event()

        async def on_connected(peer_alias: str, fingerprint: str) -> None:
            self._peer_alias = peer_alias
            self._peer_fingerprint = fingerprint
            peer_connected_event.set()

        async def on_message(peer_alias: str, plaintext: str) -> None:
            await self._enqueue_incoming(peer_alias, plaintext)

        async def on_disconnected(peer_alias: str) -> None:
            await self._print_queue.put(
                Text.assemble(
                    ("  ✗ ", "bold red"),
                    (f"{peer_alias} disconnected", "dim"),
                )
            )
            self._stop_event.set()

        server.on_peer_connected = on_connected
        server.on_message = on_message
        server.on_peer_disconnected = on_disconnected

        await server.start(host="0.0.0.0", port=port)

        _print_header()
        console.print(f"[cyan]Hosting on port[/cyan] [bold]{server.port}[/bold]")
        console.print("[dim]Waiting for a peer to connect…[/dim]")
        console.print()

        await peer_connected_event.wait()
        self._print_connected_banner()

        try:
            await self._input_loop(send_fn=lambda text: server.broadcast(text))
        finally:
            await server.stop()

    # ------------------------------------------------------------------ #
    # Join mode                                                            #
    # ------------------------------------------------------------------ #

    async def run_join(self, *, uri: str) -> None:
        """Connect to a server and enter the chat loop."""
        client = StealthClient(
            self._alias,
            self._armored_private,
            self._passphrase,
        )

        async def on_message(plaintext: str) -> None:
            assert self._peer_alias is not None
            await self._enqueue_incoming(self._peer_alias, plaintext)

        async def on_disconnected() -> None:
            await self._print_queue.put(
                Text.assemble(
                    ("  ✗ ", "bold red"),
                    ("Connection closed by server", "dim"),
                )
            )
            self._stop_event.set()

        client.on_message = on_message
        client.on_disconnected = on_disconnected

        _print_header()
        console.print(f"[cyan]Connecting to[/cyan] [bold]{uri}[/bold]")

        await client.connect(uri)

        self._peer_alias = client.peer_alias
        self._peer_fingerprint = client.peer_fingerprint

        self._print_connected_banner()

        try:
            await self._input_loop(send_fn=client.send_message)
        finally:
            await client.disconnect()

    # ------------------------------------------------------------------ #
    # Shared input loop                                                    #
    # ------------------------------------------------------------------ #

    async def _input_loop(self, send_fn) -> None:  # type: ignore[type-arg]
        """Read user input and send it; print queued incoming messages.

        The prompt runs as a persistent task. When the stop event fires
        (peer disconnected) the prompt task is cancelled cleanly so the
        terminal is never left in a broken state.
        """
        session: PromptSession[str] = PromptSession(style=_STYLE)

        # patch_stdout makes Rich's console.print() work while prompt_toolkit
        # holds the input line — incoming messages appear above the prompt.
        with patch_stdout(raw=True):
            printer = asyncio.create_task(self._printer_task())

            try:
                while not self._stop_event.is_set():
                    # Create one prompt task and one stop-watcher task.
                    # We wait for whichever completes first — this avoids
                    # cancelling and restarting the prompt every 0.2 s.
                    prompt_task = asyncio.create_task(
                        session.prompt_async(
                            HTML(f"<prompt>[{self._alias}] </prompt>"),
                        )
                    )
                    stop_task = asyncio.create_task(self._stop_event.wait())

                    try:
                        done, pending = await asyncio.wait(
                            {prompt_task, stop_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    except (KeyboardInterrupt, EOFError):
                        prompt_task.cancel()
                        stop_task.cancel()
                        break

                    # Cancel whichever task did not finish.
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass

                    # If the stop event fired, exit the loop.
                    if stop_task in done:
                        break

                    # Retrieve the prompt result.
                    try:
                        text: str = prompt_task.result()
                    except (EOFError, KeyboardInterrupt):
                        break
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        break

                    text = text.strip()
                    if not text:
                        continue

                    if text.lower() in ("/quit", "/exit", "/q"):
                        break

                    if text.lower() == "/fp":
                        _print_fingerprint(self._peer_alias, self._peer_fingerprint)
                        continue

                    if text.lower() == "/help":
                        _print_help()
                        continue

                    try:
                        await send_fn(text)
                        _print_outgoing(self._alias, text)
                    except Exception as exc:
                        console.print(f"[red]Send error:[/red] {exc}")
            finally:
                await self._print_queue.put(None)  # sentinel → printer exits
                await printer

        _print_footer()

    async def _printer_task(self) -> None:
        """Background task: prints incoming messages from the queue."""
        while True:
            item = await self._print_queue.get()
            if item is None:
                break
            console.print(item)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    async def _enqueue_incoming(self, peer_alias: str, plaintext: str) -> None:
        msg = Text.assemble(
            (_now(), "dim"),
            ("  ", ""),
            (f"{peer_alias}", "bold magenta"),
            (" › ", "dim"),
            (plaintext, "white"),
        )
        await self._print_queue.put(msg)

    def _print_connected_banner(self) -> None:
        console.print(
            Text.assemble(
                ("  ✓ ", "bold green"),
                ("Connected to ", ""),
                (self._peer_alias or "peer", "bold magenta"),
            )
        )
        console.print(
            Text.assemble(
                ("    Fingerprint: ", "dim"),
                (self._peer_fingerprint or "unknown", "yellow"),
            )
        )
        console.print("[dim]  Verify fingerprint out-of-band before trusting.[/dim]")
        console.print()
        _print_help()
        console.print(Rule(style="dim"))
        console.print()


# --------------------------------------------------------------------------- #
# Pure output functions                                                         #
# --------------------------------------------------------------------------- #


def _print_header() -> None:
    console.print()
    console.print(Rule("[bold cyan]stealth-message[/bold cyan]", style="cyan"))
    console.print()


def _print_footer() -> None:
    console.print()
    console.print(Rule("[dim]Session ended[/dim]", style="dim"))
    console.print()


def _print_outgoing(alias: str, text: str) -> None:
    console.print(
        Text.assemble(
            (_now(), "dim"),
            ("  ", ""),
            (f"{alias}", "bold green"),
            (" › ", "dim"),
            (text, "bright_white"),
        )
    )


def _print_fingerprint(
    peer_alias: Optional[str], fingerprint: Optional[str]
) -> None:
    console.print(
        Text.assemble(
            ("  Peer: ", "bold"),
            (peer_alias or "unknown", "magenta"),
            ("\n  FP:   ", "bold"),
            (fingerprint or "unknown", "yellow"),
        )
    )


def _print_help() -> None:
    console.print(
        "[dim]  /fp[/dim]   show peer fingerprint   "
        "[dim]/quit[/dim]  exit"
    )


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
