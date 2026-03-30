"""Chat screen — rich output + prompt_toolkit input, host and join modes.

The screen coordinates Rich's live output and prompt_toolkit's async input
so that incoming messages do not break the user's input line.

Room model
----------
The host can run multiple isolated 1-on-1 rooms simultaneously (e.g. one with
Pepe and another with Juan).  Each room admits exactly one peer.  The host
types in the *active room*; ``/switch <room>`` changes the target.  Incoming
messages from all rooms appear in the shared stream, tagged with ``[room]`` in
multi-room mode.

Host mode (--host):
    Starts a StealthServer on the given port.  One or more room names can be
    specified; the server accepts connections only to those rooms.

Join mode (--join <ws://...>):
    Connects a StealthClient to the given URI with the specified room.

Usage (called by __main__.py)::

    # single-room (backward-compatible)
    await run_chat(mode="host", alias=alias, armored_private=priv,
                   passphrase=passphrase, port=8765)

    # multi-room host
    await run_chat(mode="host", alias=alias, armored_private=priv,
                   passphrase=passphrase, port=8765, rooms=["pepe", "juan"])

    # join a specific room
    await run_chat(mode="join", alias=alias, armored_private=priv,
                   passphrase=passphrase, uri="ws://192.168.1.5:8765",
                   room="pepe")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

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
# Room state                                                                    #
# --------------------------------------------------------------------------- #


@dataclass
class RoomState:
    """Runtime state for one chat room."""

    room_id: str
    peer_alias: Optional[str] = None
    peer_fingerprint: Optional[str] = None
    connected: bool = False


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
    rooms: Optional[list[str]] = None,
    room: str = "default",
) -> None:
    """Launch the interactive chat screen.

    Args:
        mode:           ``"host"`` or ``"join"``.
        alias:          Local user's display alias.
        armored_private: ASCII-armored private key (protected with passphrase).
        passphrase:     Passphrase for the private key.
        port:           TCP port to listen on (host mode only).
        uri:            WebSocket URI to connect to (join mode only).
        rooms:          Room names to create (host mode).  ``None`` → single
                        room ``"default"``.
        room:           Room to connect to (join mode).
    """
    screen = ChatScreen(
        alias=alias,
        armored_private=armored_private,
        passphrase=passphrase,
        room_ids=rooms or [room],
    )

    if mode == "host":
        await screen.run_host(port=port)
    else:
        if uri is None:
            raise ValueError("uri is required in join mode")
        await screen.run_join(uri=uri, room_id=room)


# --------------------------------------------------------------------------- #
# ChatScreen                                                                    #
# --------------------------------------------------------------------------- #


class ChatScreen:
    """Manages the Rich + prompt_toolkit UI for one chat session."""

    def __init__(
        self,
        *,
        alias: str,
        armored_private: str,
        passphrase: str,
        room_ids: Optional[list[str]] = None,
    ) -> None:
        self._alias = alias
        self._armored_private = armored_private
        self._passphrase = passphrase

        self._room_ids: list[str] = room_ids if room_ids else ["default"]
        self._multi_room: bool = len(self._room_ids) > 1
        self._active_room: str = self._room_ids[0]

        self._room_states: dict[str, RoomState] = {
            r: RoomState(room_id=r) for r in self._room_ids
        }
        # Async send functions keyed by room_id.
        self._send_fns: dict[str, Callable[..., object]] = {}

        self._stop_event = asyncio.Event()
        self._print_queue: asyncio.Queue[Optional[Text]] = asyncio.Queue()

    # ------------------------------------------------------------------ #
    # Host mode                                                            #
    # ------------------------------------------------------------------ #

    async def run_host(self, *, port: int) -> None:
        """Start a server and enter the chat loop."""
        server = StealthServer(
            self._alias,
            self._armored_private,
            self._passphrase,
            rooms=self._room_ids if self._multi_room else None,
        )

        async def on_connected(peer_alias: str, fingerprint: str, room_id: str) -> None:
            state = self._room_states.get(room_id)
            if state:
                state.peer_alias = peer_alias
                state.peer_fingerprint = fingerprint
                state.connected = True
            await self._print_queue.put(
                Text.assemble(
                    ("  ✓ ", "bold green"),
                    (f"[{room_id}]  " if self._multi_room else "", "cyan dim"),
                    (peer_alias, "bold magenta"),
                    (" connected", ""),
                )
            )
            await self._print_queue.put(
                Text.assemble(
                    ("    Fingerprint: ", "dim"),
                    (fingerprint, "yellow"),
                )
            )
            if self._multi_room:
                await self._print_queue.put(
                    Text(
                        f"    [dim]Type /switch {room_id} to chat in this room[/dim]"
                        if room_id != self._active_room
                        else "    [dim]This is your active room.[/dim]",
                        style="",
                        no_wrap=False,
                    )
                )
            await self._print_queue.put(
                Text("[dim]  Verify fingerprint out-of-band before trusting.[/dim]")
            )

        async def on_message(
            peer_alias: str, plaintext: str, room_id: str
        ) -> None:
            await self._enqueue_incoming(peer_alias, plaintext, room_id)

        async def on_disconnected(peer_alias: str, room_id: str) -> None:
            state = self._room_states.get(room_id)
            if state:
                state.connected = False
                state.peer_alias = None
                state.peer_fingerprint = None
            await self._print_queue.put(
                Text.assemble(
                    ("  ✗ ", "bold red"),
                    (f"[{room_id}]  " if self._multi_room else "", "cyan dim"),
                    (f"{peer_alias} disconnected", "dim"),
                )
            )
            # In single-room mode, stop the loop when the peer leaves.
            if not self._multi_room:
                self._stop_event.set()

        server.on_peer_connected = on_connected
        server.on_message = on_message
        server.on_peer_disconnected = on_disconnected

        # Build send closures for every room before entering the loop.
        def _make_send(rid: str) -> Callable[[str], object]:
            async def _send(text: str) -> None:
                await server.send_to_room(rid, text)

            return _send

        for rid in self._room_ids:
            self._send_fns[rid] = _make_send(rid)

        await server.start(host="0.0.0.0", port=port)

        _print_header()
        console.print(f"[cyan]Hosting on port[/cyan] [bold]{server.port}[/bold]")
        if self._multi_room:
            rooms_fmt = "  ".join(f"[cyan]{r}[/cyan]" for r in self._room_ids)
            console.print(f"[bold]Rooms:[/bold]  {rooms_fmt}")
            console.print(
                "[dim]Share: [/dim][bold]ws://YOUR_IP:"
                f"{server.port}[/bold][dim]  (give peer the room name)[/dim]"
            )
            _print_help(multi_room=True)
        else:
            console.print("[dim]Waiting for a peer to connect…[/dim]")
        console.print(Rule(style="dim"))
        console.print()

        try:
            await self._input_loop()
        finally:
            await server.stop()

    # ------------------------------------------------------------------ #
    # Join mode                                                            #
    # ------------------------------------------------------------------ #

    async def run_join(self, *, uri: str, room_id: str = "default") -> None:
        """Connect to a server and enter the chat loop."""
        client = StealthClient(
            self._alias,
            self._armored_private,
            self._passphrase,
        )

        async def on_message(plaintext: str) -> None:
            state = self._room_states.get(room_id)
            peer_alias = (state.peer_alias if state else None) or "peer"
            await self._enqueue_incoming(peer_alias, plaintext, room_id)

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
        if self._multi_room or room_id != "default":
            console.print(f"[cyan]Room:[/cyan] [bold]{room_id}[/bold]")

        await client.connect(uri, room_id=room_id)

        state = self._room_states.get(room_id)
        if state:
            state.peer_alias = client.peer_alias
            state.peer_fingerprint = client.peer_fingerprint
            state.connected = True

        self._send_fns[room_id] = client.send_message

        _print_connected_banner(
            client.peer_alias,
            client.peer_fingerprint,
            room_id if (self._multi_room or room_id != "default") else None,
        )

        try:
            await self._input_loop()
        finally:
            await client.disconnect()

    # ------------------------------------------------------------------ #
    # Shared input loop                                                    #
    # ------------------------------------------------------------------ #

    async def _input_loop(self) -> None:
        """Read user input and send it; print queued incoming messages."""
        session: PromptSession[str] = PromptSession(style=_STYLE)

        with patch_stdout(raw=True):
            printer = asyncio.create_task(self._printer_task())

            try:
                while not self._stop_event.is_set():
                    prompt_label = (
                        f"[{self._alias}@{self._active_room}] "
                        if self._multi_room
                        else f"[{self._alias}] "
                    )
                    prompt_task = asyncio.create_task(
                        session.prompt_async(
                            HTML(f"<prompt>{prompt_label}</prompt>"),
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

                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass

                    if stop_task in done:
                        break

                    try:
                        text: str = prompt_task.result()
                    except (EOFError, KeyboardInterrupt, asyncio.CancelledError, Exception):
                        break

                    text = text.strip()
                    if not text:
                        continue

                    if text.lower() in ("/quit", "/exit", "/q"):
                        break

                    if text.lower() == "/fp":
                        state = self._room_states.get(self._active_room)
                        _print_fingerprint(
                            state.peer_alias if state else None,
                            state.peer_fingerprint if state else None,
                        )
                        continue

                    if text.lower() == "/help":
                        _print_help(multi_room=self._multi_room)
                        continue

                    if text.lower() == "/rooms" and self._multi_room:
                        _print_rooms(self._room_states, self._active_room)
                        continue

                    if self._multi_room and (
                        text.lower().startswith("/switch ")
                        or text.lower().startswith("/s ")
                    ):
                        parts = text.split(None, 1)
                        target = parts[1].strip() if len(parts) > 1 else ""
                        if target in self._room_states:
                            self._active_room = target
                            state = self._room_states[target]
                            status = (
                                f"[bold magenta]{state.peer_alias}[/bold magenta] connected"
                                if state.connected
                                else "[dim]no peer yet[/dim]"
                            )
                            console.print(
                                f"[cyan]Active room:[/cyan] [bold]{target}[/bold]  {status}"
                            )
                        else:
                            console.print(
                                f"[red]Room not found:[/red] {target!r}  "
                                f"(available: {', '.join(self._room_states)})"
                            )
                        continue

                    # Send to the active room.
                    send_fn = self._send_fns.get(self._active_room)
                    state = self._room_states.get(self._active_room)
                    if send_fn is None or not (state and state.connected):
                        console.print(
                            f"[yellow]No peer connected in room "
                            f"'{self._active_room}'. Waiting…[/yellow]"
                        )
                        continue

                    try:
                        await send_fn(text)  # type: ignore[arg-type]
                        _print_outgoing(
                            self._alias,
                            text,
                            self._active_room if self._multi_room else None,
                        )
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

    async def _enqueue_incoming(
        self, peer_alias: str, plaintext: str, room_id: Optional[str] = None
    ) -> None:
        parts: list[tuple[str, str]] = [
            (_now(), "dim"),
            ("  ", ""),
        ]
        if self._multi_room and room_id:
            parts.append((f"[{room_id}]  ", "cyan dim"))
        parts.extend(
            [
                (f"{peer_alias}", "bold magenta"),
                (" › ", "dim"),
                (plaintext, "white"),
            ]
        )
        await self._print_queue.put(Text.assemble(*parts))


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


def _print_connected_banner(
    peer_alias: Optional[str],
    fingerprint: Optional[str],
    room_id: Optional[str] = None,
) -> None:
    parts: list[tuple[str, str]] = [("  ✓ ", "bold green"), ("Connected to ", "")]
    if room_id:
        parts.append((f"[{room_id}]  ", "cyan dim"))
    parts.append((peer_alias or "peer", "bold magenta"))
    console.print(Text.assemble(*parts))
    console.print(
        Text.assemble(
            ("    Fingerprint: ", "dim"),
            (fingerprint or "unknown", "yellow"),
        )
    )
    console.print("[dim]  Verify fingerprint out-of-band before trusting.[/dim]")
    console.print()
    _print_help(multi_room=room_id is not None)
    console.print(Rule(style="dim"))
    console.print()


def _print_outgoing(
    alias: str, text: str, room_id: Optional[str] = None
) -> None:
    parts: list[tuple[str, str]] = [
        (_now(), "dim"),
        ("  ", ""),
    ]
    if room_id:
        parts.append((f"[{room_id}]  ", "cyan dim"))
    parts.extend(
        [
            (f"{alias}", "bold green"),
            (" › ", "dim"),
            (text, "bright_white"),
        ]
    )
    console.print(Text.assemble(*parts))


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


def _print_rooms(
    room_states: dict[str, RoomState], active_room: str
) -> None:
    console.print()
    for room_id, state in room_states.items():
        marker = "▶" if room_id == active_room else " "
        if state.connected:
            status = Text.assemble(
                (f"{marker} ", "bold cyan"),
                (room_id, "bold" if room_id == active_room else ""),
                ("  ✓ ", "green"),
                (state.peer_alias or "", "magenta"),
            )
        else:
            status = Text.assemble(
                (f"{marker} ", "bold cyan"),
                (room_id, "bold" if room_id == active_room else ""),
                ("  [dim]waiting for peer…[/dim]", ""),
            )
        console.print(status)
    console.print()


def _print_help(*, multi_room: bool = False) -> None:
    base = "[dim]  /fp[/dim]   fingerprint   [dim]/quit[/dim]  exit"
    if multi_room:
        base += (
            "   [dim]/rooms[/dim]  list rooms"
            "   [dim]/switch <room>[/dim]  change room"
        )
    console.print(base)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
