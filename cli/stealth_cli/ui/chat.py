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
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from stealth_cli.exceptions import ProtocolError
from stealth_cli.network.client import StealthClient, query_rooms
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
    peer_alias: Optional[str] = None        # first/only peer (1:1 rooms)
    peer_fingerprint: Optional[str] = None  # first/only peer (1:1 rooms)
    connected: bool = False
    is_group: bool = False
    # True when the server told us this is a group room but we haven't joined it.
    known_group: bool = False
    # Group rooms may have multiple peers.
    peer_aliases: Optional[list[str]] = None
    peer_fingerprints: Optional[dict[str, str]] = None


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
        # Show room UI whenever the user explicitly named a room (even just one).
        self._multi_room: bool = self._room_ids != ["default"]
        self._active_room: str = self._room_ids[0]

        self._room_states: dict[str, RoomState] = {
            r: RoomState(room_id=r) for r in self._room_ids
        }
        # Async send functions keyed by room_id.
        self._send_fns: dict[str, Callable[..., object]] = {}

        self._stop_event = asyncio.Event()
        self._print_queue: asyncio.Queue[object] = asyncio.Queue()
        # Reference to the running server (host mode only) — used by /new command.
        self._server: Optional[StealthServer] = None
        # Join mode: URI and active client — used by /switch command.
        self._join_uri: Optional[str] = None
        self._join_client: Optional[StealthClient] = None

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
                state.connected = True
                state.peer_alias = peer_alias
                state.peer_fingerprint = fingerprint
                if state.peer_aliases is None:
                    state.peer_aliases = []
                if peer_alias not in state.peer_aliases:
                    state.peer_aliases.append(peer_alias)
                if state.peer_fingerprints is None:
                    state.peer_fingerprints = {}
                state.peer_fingerprints[peer_alias] = fingerprint
            await self._print_queue.put(
                Text.assemble(
                    ("  ✓ ", "bold green"),
                    (f"[{room_id}]  " if self._multi_room else "", "cyan dim"),
                    (peer_alias, "bold magenta"),
                    (" connected", ""),
                )
            )
            await self._print_queue.put(
                Text.assemble(("    Fingerprint: ", "dim"), (fingerprint, "yellow"))
            )
            if self._multi_room and room_id != self._active_room:
                await self._print_queue.put(
                    Text.from_markup(
                        f"    [dim]Type /switch {room_id} to chat in this room[/dim]"
                    )
                )
            await self._print_queue.put(
                Text.from_markup("[dim]  Verify fingerprint out-of-band before trusting.[/dim]")
            )

        async def on_message(peer_alias: str, plaintext: str, room_id: str) -> None:
            await self._enqueue_incoming(peer_alias, plaintext, room_id)

        async def on_disconnected(peer_alias: str, room_id: str) -> None:
            state = self._room_states.get(room_id)
            if state and state.peer_aliases:
                state.peer_aliases = [a for a in state.peer_aliases if a != peer_alias]
                if not state.peer_aliases:
                    state.connected = False
            await self._print_queue.put(
                Text.assemble(
                    ("  ✗ ", "bold red"),
                    (f"[{room_id}]  " if self._multi_room else "", "cyan dim"),
                    (f"{peer_alias} disconnected", "dim"),
                )
            )
            if not self._multi_room:
                self._stop_event.set()

        async def on_join_request(peer_alias: str, fingerprint: str, room_id: str) -> None:
            await self._print_queue.put(
                Text.from_markup(
                    f"\n[bold yellow]  ⚠  Join request:[/bold yellow]"
                    f" [bold magenta]{peer_alias}[/bold magenta]"
                    f" wants to enter room [bold cyan]{room_id}[/bold cyan]\n"
                    f"  FP: [yellow]{fingerprint}[/yellow]\n"
                    f"  [dim]/allow {peer_alias}[/dim]  or  "
                    f"[dim]/deny {peer_alias}[/dim]"
                )
            )

        server.on_peer_connected = on_connected
        server.on_message = on_message
        server.on_peer_disconnected = on_disconnected
        server.on_join_request = on_join_request

        def _make_send(rid: str) -> Callable[[str], object]:
            async def _send(text: str) -> None:
                await server.send_to_room(rid, text)
            return _send

        for rid in self._room_ids:
            self._send_fns[rid] = _make_send(rid)

        await server.start(host="0.0.0.0", port=port)
        self._server = server

        _print_header()
        console.print(f"[cyan]Hosting on port[/cyan] [bold]{server.port}[/bold]")
        if self._multi_room:
            rooms_fmt = "  ".join(f"[cyan]{r}[/cyan]" for r in self._room_ids)
            console.print(f"[bold]Rooms:[/bold]  {rooms_fmt}")
        console.print(
            "[dim]Share:[/dim] [bold]ws://YOUR_IP:"
            f"{server.port}[/bold]"
            + ("[dim]  + room name[/dim]" if self._multi_room else "")
        )
        _print_help(multi_room=self._multi_room, is_host=True)
        console.print("[dim]Waiting for peers to connect…[/dim]")
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
        client = self._make_join_client(room_id)

        _print_header()
        console.print(f"[cyan]Connecting to[/cyan] [bold]{uri}[/bold]")
        if self._multi_room or room_id != "default":
            console.print(f"[cyan]Room:[/cyan] [bold]{room_id}[/bold]")

        await client.connect(uri, room_id=room_id)

        self._join_uri = uri
        self._join_client = client
        self._active_room = room_id
        self._multi_room = True  # join mode always shows room UI

        if room_id not in self._room_states:
            self._room_states[room_id] = RoomState(room_id=room_id)
        state = self._room_states[room_id]
        state.peer_alias = client.peer_alias
        state.peer_fingerprint = client.peer_fingerprint
        state.connected = True

        self._send_fns[room_id] = client.send_message

        _print_connected_banner(
            client.peer_alias,
            client.peer_fingerprint,
            room_id,
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

                    cmd_result = await self._dispatch_command(text)
                    if cmd_result is True:
                        break
                    if cmd_result is False:
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

                    # Borrar la línea que dejó prompt_toolkit y reemplazarla
                    # con la versión formateada de _print_outgoing.
                    sys.stdout.write("\x1b[1A\x1b[2K\r")
                    sys.stdout.flush()
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
    # Join-mode room switch                                                #
    # ------------------------------------------------------------------ #

    async def _switch_join_room(self, target: str) -> None:
        """Disconnect from the current room and connect to ``target`` (join mode)."""
        assert self._join_uri is not None

        if not target:
            console.print("[red]Usage:[/red] /switch <room-name>")
            return

        if target == self._active_room:
            console.print(f"[yellow]Already in room '{target}'.[/yellow]")
            return

        # Disconnect current client cleanly.
        # Null out the callback first so the finalizer of _recv_task does not
        # fire on_disconnected (which would set _stop_event and kill the session).
        old_client = self._join_client
        if old_client is not None:
            old_client.on_disconnected = None
            try:
                await old_client.disconnect()
            except Exception:
                pass
            self._join_client = None

        # Clear old room state.
        old_state = self._room_states.get(self._active_room)
        if old_state:
            old_state.connected = False
            old_state.peer_alias = None
            old_state.peer_fingerprint = None
        self._send_fns.pop(self._active_room, None)

        # Try to connect to the new room.
        new_client = self._make_join_client(target)

        console.print(f"[cyan]Switching to room[/cyan] [bold]{target}[/bold]…")

        try:
            await new_client.connect(self._join_uri, room_id=target)
        except ProtocolError as exc:
            if exc.code == 4006:
                console.print(
                    f"[red]Room '{target}' is already occupied.[/red] "
                    "Choose a different room."
                )
            elif exc.code == 4007:
                console.print(
                    f"[red]Room '{target}' does not exist on this server.[/red]"
                )
            else:
                console.print(f"[red]Cannot join room '{target}':[/red] {exc}")
            # Reconnect to the previous room to stay in a consistent state.
            await self._reconnect_to_room(self._active_room)
            return
        except Exception as exc:
            console.print(f"[red]Connection error:[/red] {exc}")
            await self._reconnect_to_room(self._active_room)
            return

        # Success — update state.
        self._join_client = new_client
        self._active_room = target

        if target not in self._room_states:
            self._room_states[target] = RoomState(room_id=target)
        state = self._room_states[target]
        state.peer_alias = new_client.peer_alias
        state.peer_fingerprint = new_client.peer_fingerprint
        state.connected = True

        self._send_fns[target] = new_client.send_message

        console.print(
            Text.assemble(
                ("  ✓ ", "bold green"),
                ("Switched to room ", ""),
                (target, "bold cyan"),
                (" — connected to ", ""),
                (new_client.peer_alias, "bold magenta"),
            )
        )
        console.print(
            Text.assemble(
                ("    Fingerprint: ", "dim"),
                (new_client.peer_fingerprint, "yellow"),
            )
        )

    async def _reconnect_to_room(self, room_id: str) -> None:
        """Re-establish connection to ``room_id`` after a failed switch."""
        assert self._join_uri is not None
        new_client = self._make_join_client(room_id)

        try:
            await new_client.connect(self._join_uri, room_id=room_id)
            self._join_client = new_client
            state = self._room_states.get(room_id)
            if state:
                state.peer_alias = new_client.peer_alias
                state.peer_fingerprint = new_client.peer_fingerprint
                state.connected = True
            self._send_fns[room_id] = new_client.send_message
            console.print(
                f"[dim]Stayed in room [bold]{room_id}[/bold].[/dim]"
            )
        except Exception as exc:
            console.print(f"[red]Could not reconnect to '{room_id}':[/red] {exc}")
            self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    async def _dispatch_command(self, text: str) -> bool | None:
        """Handle a slash command from the input loop.

        Returns:
            True  → quit was requested; caller should break the input loop.
            False → command was handled; caller should continue the loop.
            None  → not a recognized command; caller should proceed to send.
        """
        low = text.lower()

        if low in ("/quit", "/exit", "/q"):
            return True

        if low == "/fp":
            state = self._room_states.get(self._active_room)
            if state and state.peer_fingerprints:
                _print_fingerprints(state.peer_fingerprints)
            else:
                _print_fingerprint(
                    state.peer_alias if state else None,
                    state.peer_fingerprint if state else None,
                )
            return False

        if low == "/help":
            _print_help(
                multi_room=self._multi_room,
                is_host=self._server is not None,
                is_join=self._join_uri is not None,
            )
            return False

        if low == "/rooms":
            if self._join_uri is not None:
                server_rooms = await query_rooms(self._join_uri)
                if server_rooms:
                    _print_rooms_from_server(server_rooms, self._active_room)
                else:
                    _print_rooms(self._room_states, self._active_room)
            else:
                _print_rooms(self._room_states, self._active_room)
            return False

        if self._server is not None and low.startswith("/new "):
            parts = text.split(None, 1)
            new_room = parts[1].strip() if len(parts) > 1 else ""
            if not new_room:
                console.print("[red]Usage:[/red] /new <room-name>")
            elif new_room in self._room_states:
                console.print(f"[yellow]Room '{new_room}' already exists.[/yellow]")
            else:
                self._server.add_room(new_room)
                self._room_states[new_room] = RoomState(room_id=new_room)
                self._room_ids.append(new_room)
                self._send_fns[new_room] = self._make_send_fn(new_room)
                if not self._multi_room:
                    self._multi_room = True
                console.print(
                    f"[green]✓[/green] Room [bold]{new_room}[/bold] created. "
                    f"Use [bold]/switch {new_room}[/bold] to activate it."
                )
            return False

        if low.startswith("/switch ") or low.startswith("/s "):
            parts = text.split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if self._join_uri is not None:
                await self._switch_join_room(target)
            else:
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
            return False

        if self._server is not None:
            if low.startswith("/allow "):
                alias = text.split(None, 1)[1].strip()
                try:
                    self._server.approve_join(alias)
                    console.print(
                        f"[green]✓[/green] Join approved for [bold magenta]{alias}[/bold magenta]"
                    )
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
                return False

            if low.startswith("/deny "):
                alias = text.split(None, 1)[1].strip()
                try:
                    self._server.deny_join(alias)
                    console.print(
                        f"[red]✗[/red] Join denied for [bold magenta]{alias}[/bold magenta]"
                    )
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
                return False

            if low.startswith("/group "):
                room_name = text.split(None, 1)[1].strip()
                if not room_name:
                    console.print("[red]Usage:[/red] /group <room-name>")
                else:
                    self._server.make_group_room(room_name)
                    if room_name not in self._room_states:
                        self._room_states[room_name] = RoomState(
                            room_id=room_name, is_group=True
                        )
                        self._room_ids.append(room_name)
                        self._send_fns[room_name] = self._make_send_fn(room_name)
                    else:
                        self._room_states[room_name].is_group = True
                    if not self._multi_room:
                        self._multi_room = True
                    console.print(
                        f"[green]✓[/green] [bold]{room_name}[/bold] is now a group room. "
                        f"Use [bold]/move <alias> {room_name}[/bold] to invite peers."
                    )
                return False

            if low.startswith("/move "):
                parts = text.split(None, 2)
                if len(parts) < 3:
                    console.print("[red]Usage:[/red] /move <alias> <room>")
                else:
                    m_alias, m_room = parts[1].strip(), parts[2].strip()
                    try:
                        await self._server.move_peer(m_alias, m_room)
                        if m_room not in self._room_states:
                            self._room_states[m_room] = RoomState(
                                room_id=m_room, is_group=True
                            )
                            self._room_ids.append(m_room)
                            self._send_fns[m_room] = self._make_send_fn(m_room)
                            if not self._multi_room:
                                self._multi_room = True
                        console.print(
                            f"[cyan]↪[/cyan] Asking [bold magenta]{m_alias}[/bold magenta]"
                            f" to move to room [bold]{m_room}[/bold]…"
                        )
                    except ValueError as exc:
                        console.print(f"[red]{exc}[/red]")
                return False

            if low == "/pending":
                reqs = self._server.pending_requests
                if not reqs:
                    console.print("[dim]No pending join requests.[/dim]")
                else:
                    for a, fp, r in reqs:
                        console.print(
                            f"  [bold magenta]{a}[/bold magenta]"
                            f" → room [bold cyan]{r}[/bold cyan]"
                            f"  FP: [yellow]{fp}[/yellow]"
                        )
                return False

        return None  # not a recognized command — fall through to send

    def _make_join_client(self, room_id: str) -> StealthClient:
        """Create a StealthClient with all callbacks wired for ``room_id``.

        All three join paths (run_join, _switch_join_room, _reconnect_to_room)
        use this factory so the callback logic lives in exactly one place.
        """
        client = StealthClient(self._alias, self._armored_private, self._passphrase)

        async def on_message(plaintext: str, sender: str | None) -> None:
            state = self._room_states.get(room_id)
            peer_alias = sender or (state.peer_alias if state else None) or "peer"
            await self._enqueue_incoming(peer_alias, plaintext, room_id)

        async def on_disconnected() -> None:
            await self._print_queue.put(
                Text.assemble(("  ✗ ", "bold red"), ("Connection closed by server", "dim"))
            )
            self._stop_event.set()

        async def on_pending() -> None:
            await self._print_queue.put(
                Text.from_markup(
                    f"[bold yellow]  ⏳ Waiting for host to approve your entry"
                    f" into room [bold cyan]{room_id}[/bold cyan]…[/bold yellow]"
                )
            )

        async def on_approved() -> None:
            await self._print_queue.put(
                Text.from_markup(
                    f"[bold green]  ✓ Host approved your entry into room "
                    f"[bold cyan]{room_id}[/bold cyan].[/bold green]"
                )
            )

        async def on_move(target_room: str) -> None:
            await self._print_queue.put(
                Text.from_markup(
                    f"[bold cyan]  ↪ Host is moving you to room "
                    f"[bold]{target_room}[/bold]…[/bold cyan]"
                )
            )
            await self._switch_join_room(target_room)

        async def on_roomlist(group_rooms: list[str]) -> None:
            self._update_known_groups(group_rooms)

        client.on_message = on_message
        client.on_disconnected = on_disconnected
        client.on_pending = on_pending
        client.on_approved = on_approved
        client.on_move = on_move
        client.on_roomlist = on_roomlist
        return client

    def _make_send_fn(self, room_id: str) -> Callable[[str], object]:
        """Return an async callable that sends a message to ``room_id`` via the server."""
        async def _send(text: str) -> None:
            await self._server.send_to_room(room_id, text)  # type: ignore[union-attr]
        return _send

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

    def _update_known_groups(self, group_rooms: list[str]) -> None:
        """Update _room_states with group rooms received from the server."""
        for room_id in group_rooms:
            if room_id not in self._room_states:
                self._room_states[room_id] = RoomState(
                    room_id=room_id, is_group=True, known_group=True
                )
            else:
                self._room_states[room_id].is_group = True


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
    parts: list[tuple[str, str]] = [
        ("  ✓ ", "bold green"),
        ("Connected to ", ""),
        (peer_alias or "peer", "bold magenta"),
    ]
    if room_id:
        parts.append((f"  [room: {room_id}]", "cyan dim"))
    console.print(Text.assemble(*parts))
    console.print(
        Text.assemble(
            ("    Fingerprint: ", "dim"),
            (fingerprint or "unknown", "yellow"),
        )
    )
    console.print("[dim]  Verify fingerprint out-of-band before trusting.[/dim]")
    console.print()
    _print_help(multi_room=False, is_host=False, is_join=True)
    console.print(Rule(style="dim"))
    console.print()


def _print_outgoing(
    alias: str, text: str, room_id: Optional[str] = None
) -> None:
    parts: list[tuple[str, str]] = [(_now(), "dim"), ("  ", "")]
    if room_id:
        parts.append((f"[{room_id}]  ", "cyan dim"))
    parts.extend(
        [
            (alias, "bold green"),
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


def _print_fingerprints(peer_fingerprints: dict[str, str]) -> None:
    for alias, fp in peer_fingerprints.items():
        console.print(
            Text.assemble(
                ("  Peer: ", "bold"),
                (alias, "magenta"),
                ("\n  FP:   ", "bold"),
                (fp, "yellow"),
            )
        )


def _print_rooms(
    room_states: dict[str, RoomState], active_room: str
) -> None:
    console.print()
    for room_id, state in room_states.items():
        marker = "▶" if room_id == active_room else " "
        room_label = f"[bold]{room_id}[/bold]" if room_id == active_room else room_id
        if state.connected:
            peers = state.peer_aliases or ([state.peer_alias] if state.peer_alias else [])
            peer_str = ", ".join(peers) if peers else ""
            console.print(
                f"[bold cyan]{marker}[/bold cyan] {room_label}"
                f"  [green]✓[/green] [magenta]{peer_str}[/magenta]"
            )
        elif state.known_group or state.is_group:
            console.print(
                f"[bold cyan]{marker}[/bold cyan] {room_label}"
                f"  [yellow]group[/yellow]  [dim]/switch to join[/dim]"
            )
        else:
            console.print(
                f"[bold cyan]{marker}[/bold cyan] {room_label}"
                f"  [dim]waiting for peer…[/dim]"
            )
    console.print()


def _print_rooms_from_server(
    server_rooms: list[dict[str, object]], active_room: str
) -> None:
    """Print room list as returned by query_rooms (live server data)."""
    from typing import Any
    console.print()
    for room in server_rooms:
        room_id = str(room.get("id", ""))
        kind = str(room.get("kind", "1:1"))
        peers = int(room.get("peers", 0))  # type: ignore[arg-type]
        available = room.get("available", True)
        marker = "▶" if room_id == active_room else " "
        room_label = f"[bold]{room_id}[/bold]" if room_id == active_room else room_id
        if kind == "group":
            if room_id == active_room:
                console.print(
                    f"[bold cyan]{marker}[/bold cyan] {room_label}"
                    f"  [yellow]group[/yellow]"
                    + (f"  [dim]{peers} peer(s)[/dim]" if peers else "  [dim]empty[/dim]")
                )
            else:
                console.print(
                    f"[bold cyan]{marker}[/bold cyan] {room_label}"
                    f"  [yellow]group[/yellow]"
                    + (f"  [dim]{peers} peer(s)[/dim]" if peers else "  [dim]empty[/dim]")
                    + "  [dim]/switch to join[/dim]"
                )
        elif available:
            console.print(
                f"[bold cyan]{marker}[/bold cyan] {room_label}"
                f"  [dim]1:1[/dim]  [green]available[/green]"
            )
        else:
            status = "[green]✓ connected[/green]" if room_id == active_room else "[dim]occupied[/dim]"
            console.print(
                f"[bold cyan]{marker}[/bold cyan] {room_label}"
                f"  [dim]1:1[/dim]  {status}"
            )
    console.print()


def _build_help_table(
    *, multi_room: bool = False, is_host: bool = False, is_join: bool = False
) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim cyan", no_wrap=True)
    t.add_column(style="dim")

    t.add_row("/fp", "Show peer fingerprint")
    t.add_row("/help", "Show this list")
    t.add_row("/quit", "Exit")

    if multi_room or is_host or is_join:
        t.add_row("/rooms", "List rooms and status")
        t.add_row("/switch <room>", "Change active room")

    if is_host:
        t.add_row("/new <room>", "Create a new room")
        t.add_row("/group <room>", "Convert room to group mode")
        t.add_row("/move <alias> <room>", "Move peer to another room")
        t.add_row("/allow <alias>", "Approve a join request")
        t.add_row("/deny <alias>", "Deny a join request")
        t.add_row("/pending", "List pending join requests")

    return t


def _print_help(*, multi_room: bool = False, is_host: bool = False, is_join: bool = False) -> None:
    console.print(_build_help_table(multi_room=multi_room, is_host=is_host, is_join=is_join))


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
