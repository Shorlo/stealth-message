"""WebSocket server — stealth-message protocol host (protocol.md §1–§4).

The host is always a participant in the conversation, never a relay.
All crypto operations (encrypt/decrypt) happen here using the host's own
PGP keypair.

Room model
----------
Each server supports one or more named rooms (§1.1).  A room admits exactly
one peer at a time.  If the host is created with a fixed ``rooms`` list, only
those room names are accepted; unknown rooms get error 4007.  If ``rooms`` is
``None`` (default), any room name is accepted on first connection.

Usage example::

    server = StealthServer("Alice", armored_privkey, passphrase,
                           rooms=["pepe", "juan"])

    async def on_msg(alias: str, plaintext: str, room_id: str) -> None:
        print(f"[{room_id}] [{alias}] {plaintext}")

    server.on_message = on_msg
    await server.start(host="0.0.0.0", port=8765)

    await server.send_to_room("pepe", "Hello Pepe!")
    await server.stop()

All callbacks must be ``async def`` functions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import websockets
import websockets.exceptions
from websockets.asyncio.server import ServerConnection, serve

from stealth_cli.crypto.keys import get_fingerprint, load_private_key
from stealth_cli.crypto.messages import decrypt, encrypt
from stealth_cli.exceptions import ProtocolError, SignatureError

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1"
HANDSHAKE_TIMEOUT = 10.0  # seconds — protocol §1.1


# --------------------------------------------------------------------------- #
# Per-connection state                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class PeerSession:
    """State associated with one connected peer."""

    ws: ServerConnection
    alias: str
    armored_pubkey: str  # ASCII-armored PGP public key (not base64)
    fingerprint: str
    room_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


# --------------------------------------------------------------------------- #
# Server                                                                        #
# --------------------------------------------------------------------------- #


class StealthServer:
    """WebSocket host implementing the stealth-message protocol.

    Supports multiple simultaneous rooms, each with exactly one peer.

    Attributes:
        on_peer_connected: Called when a peer completes the handshake.
            Signature: ``async def cb(alias: str, fingerprint: str, room_id: str) -> None``
        on_message: Called when a decrypted message arrives from a peer.
            Signature: ``async def cb(peer_alias: str, plaintext: str, room_id: str) -> None``
        on_peer_disconnected: Called when a peer disconnects.
            Signature: ``async def cb(alias: str, room_id: str) -> None``
    """

    def __init__(
        self,
        alias: str,
        armored_privkey: str,
        passphrase: str,
        rooms: list[str] | None = None,
    ) -> None:
        self._alias: str = alias[:64]  # §1.1: max 64 UTF-8 chars
        self._privkey = load_private_key(armored_privkey, passphrase)
        self._passphrase: str = passphrase
        # Derive armored public key from the loaded private key.
        self._armored_pubkey: str = str(self._privkey.pubkey)

        # Allowed rooms: None → accept any room name; set → only those names.
        self._allowed_rooms: set[str] | None = (
            set(rooms) if rooms is not None else None
        )
        # room_id → PeerSession (max 1 peer per room).
        self._rooms: dict[str, PeerSession] = {}

        self._ws_server: Any = None  # websockets Server object
        self._server_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._started_event: asyncio.Event | None = None

        # Public callbacks — set before calling start().
        self.on_peer_connected: (
            Callable[[str, str, str], Awaitable[None]] | None
        ) = None
        self.on_message: Callable[[str, str, str], Awaitable[None]] | None = None
        self.on_peer_disconnected: (
            Callable[[str, str], Awaitable[None]] | None
        ) = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def start(self, host: str = "localhost", port: int = 0) -> None:
        """Start the server and wait until it is ready to accept connections.

        Args:
            host: Bind address. Defaults to ``localhost``.
            port: TCP port. ``0`` lets the OS assign a free port.
        """
        self._stop_event = asyncio.Event()
        self._started_event = asyncio.Event()
        self._server_task = asyncio.create_task(
            self._run(host, port), name="stealth-server"
        )
        await self._started_event.wait()

    async def stop(self) -> None:
        """Stop the server, close all connections, and wait for cleanup."""
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

    @property
    def port(self) -> int:
        """TCP port the server is listening on. Valid only after :meth:`start`."""
        if self._ws_server is None:
            raise RuntimeError("Server has not been started yet")
        return self._ws_server.sockets[0].getsockname()[1]

    @property
    def connected_peers(self) -> list[str]:
        """Aliases of currently connected and handshaked peers (all rooms)."""
        return [p.alias for p in self._rooms.values()]

    @property
    def room_peers(self) -> dict[str, str | None]:
        """Map of room_id → peer alias (``None`` if the room is empty).

        Only rooms that have ever had a peer, or are in the allowed-rooms list,
        appear in the result.
        """
        result: dict[str, str | None] = {}
        if self._allowed_rooms is not None:
            for r in self._allowed_rooms:
                result[r] = None
        for room_id, peer in self._rooms.items():
            result[room_id] = peer.alias
        return result

    async def broadcast(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` separately for each peer in every room."""
        for peer in list(self._rooms.values()):
            await self._send_message_to(peer, plaintext)

    def add_room(self, room_id: str) -> None:
        """Add a new room at runtime so peers can join it.

        If the server was created with a fixed room list, the new room is
        appended to that list.  If the server is open (no fixed rooms), this
        is a no-op because any name is already accepted.

        Args:
            room_id: Name of the new room (max 64 chars).
        """
        room_id = room_id[:64]
        if self._allowed_rooms is not None:
            self._allowed_rooms.add(room_id)

    async def send_to_room(self, room_id: str, plaintext: str) -> None:
        """Encrypt and send ``plaintext`` to the peer currently in ``room_id``.

        Args:
            room_id: Target room name.
            plaintext: UTF-8 text to send.

        Raises:
            ValueError: If no peer is connected in that room.
        """
        peer = self._rooms.get(room_id)
        if peer is None:
            raise ValueError(f"No peer connected in room {room_id!r}")
        await self._send_message_to(peer, plaintext)

    async def send_to(self, alias: str, plaintext: str) -> None:
        """Encrypt and send ``plaintext`` to the peer with the given alias.

        Args:
            alias: Peer alias as received during the handshake.
            plaintext: UTF-8 text to send.

        Raises:
            ValueError: If no connected peer has the given alias.
        """
        for peer in self._rooms.values():
            if peer.alias == alias:
                await self._send_message_to(peer, plaintext)
                return
        raise ValueError(f"No connected peer with alias {alias!r}")

    # ------------------------------------------------------------------ #
    # Server lifecycle                                                     #
    # ------------------------------------------------------------------ #

    async def _run(self, host: str, port: int) -> None:
        """Background task: keep the WebSocket server alive."""
        async with serve(
            self._handle_connection,
            host,
            port,
            ping_interval=None,
        ) as ws_server:
            self._ws_server = ws_server
            assert self._started_event is not None
            self._started_event.set()
            assert self._stop_event is not None
            await self._stop_event.wait()

    # ------------------------------------------------------------------ #
    # Connection handler                                                   #
    # ------------------------------------------------------------------ #

    async def _handle_connection(self, ws: ServerConnection) -> None:
        """Handle the full lifecycle of one peer connection."""
        peer: PeerSession | None = None
        try:
            peer = await asyncio.wait_for(
                self._do_handshake(ws), timeout=HANDSHAKE_TIMEOUT
            )
        except asyncio.TimeoutError:
            await self._safe_send_error(ws, 4005, "handshake timeout")
            return
        except ProtocolError as exc:
            await self._safe_send_error(ws, exc.code, str(exc))
            return
        except websockets.exceptions.ConnectionClosed:
            return
        except Exception as exc:
            logger.debug("Handshake error: %s", exc)
            await self._safe_send_error(ws, 4002, "handshake error")
            return

        self._rooms[peer.room_id] = peer
        logger.info(
            "Peer connected: %s  fp=%s  room=%s",
            peer.alias,
            peer.fingerprint,
            peer.room_id,
        )

        if self.on_peer_connected:
            await self.on_peer_connected(peer.alias, peer.fingerprint, peer.room_id)

        try:
            async for raw in ws:
                await self._dispatch(ws, peer, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._rooms.pop(peer.room_id, None)
            logger.info("Peer disconnected: %s  room=%s", peer.alias, peer.room_id)
            if self.on_peer_disconnected:
                await self.on_peer_disconnected(peer.alias, peer.room_id)

    # ------------------------------------------------------------------ #
    # Handshake — §1.1                                                     #
    # ------------------------------------------------------------------ #

    async def _do_handshake(self, ws: ServerConnection) -> PeerSession:
        """Server-side handshake: receive hello → validate → send hello.

        The client always sends first (protocol §1.1).
        """
        raw = await ws.recv()
        try:
            msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProtocolError("malformed hello: invalid JSON", 4002) from exc

        if msg.get("type") != "hello":
            raise ProtocolError(
                f"expected hello, got {msg.get('type')!r}", 4002
            )

        if str(msg.get("version")) != PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol version {msg.get('version')!r}", 4001
            )

        for required in ("alias", "pubkey"):
            if not msg.get(required):
                raise ProtocolError(f"hello missing field: {required!r}", 4002)

        # Room validation — §1.1
        room_id = str(msg.get("room") or "default")[:64] or "default"

        if self._allowed_rooms is not None and room_id not in self._allowed_rooms:
            raise ProtocolError(f"room {room_id!r} not found on this server", 4007)

        if room_id in self._rooms:
            raise ProtocolError(f"room {room_id!r} is already occupied", 4006)

        peer_alias = str(msg["alias"])[:64]

        try:
            peer_armored = base64.urlsafe_b64decode(
                msg["pubkey"].encode("ascii") + b"=="
            ).decode("utf-8")
        except Exception as exc:
            raise ProtocolError("invalid pubkey encoding in hello", 4002) from exc

        try:
            peer_fp = get_fingerprint(peer_armored)
        except Exception as exc:
            raise ProtocolError("invalid pubkey in hello", 4002) from exc

        # Send our hello.
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": PROTOCOL_VERSION,
                    "alias": self._alias,
                    "pubkey": base64.urlsafe_b64encode(
                        self._armored_pubkey.encode("utf-8")
                    ).decode("ascii"),
                }
            )
        )

        return PeerSession(
            ws=ws,
            alias=peer_alias,
            armored_pubkey=peer_armored,
            fingerprint=peer_fp,
            room_id=room_id,
        )

    # ------------------------------------------------------------------ #
    # Message dispatch — §2, §3, §4                                        #
    # ------------------------------------------------------------------ #

    async def _dispatch(
        self, ws: ServerConnection, peer: PeerSession, raw: str | bytes
    ) -> None:
        """Parse and route one incoming WebSocket frame."""
        try:
            msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._safe_send_error(ws, 4002, "invalid JSON")
            return

        msg_type = msg.get("type")

        if msg_type == "message":
            await self._handle_chat(ws, peer, msg)
        elif msg_type == "ping":
            await ws.send(json.dumps({"type": "pong"}))
        elif msg_type == "bye":
            await ws.close()
        elif msg_type == "pong":
            pass  # Server does not currently send pings; ignore stray pongs.
        elif msg_type == "error":
            logger.warning(
                "Error from peer %s (room=%s): code=%s reason=%s",
                peer.alias,
                peer.room_id,
                msg.get("code"),
                msg.get("reason"),
            )
        elif msg_type is None:
            await self._safe_send_error(ws, 4002, "missing 'type' field")
        else:
            # Unknown type → ignore silently for forward compatibility (§5).
            logger.debug(
                "Ignoring unknown message type %r from %s (room=%s)",
                msg_type,
                peer.alias,
                peer.room_id,
            )

    async def _handle_chat(
        self, ws: ServerConnection, peer: PeerSession, msg: dict[str, Any]
    ) -> None:
        """Decrypt and deliver a §2.1 chat message."""
        for required in ("id", "payload", "timestamp"):
            if required not in msg:
                await self._safe_send_error(
                    ws, 4002, f"message missing field: {required!r}"
                )
                return

        try:
            with self._privkey.unlock(self._passphrase):
                plaintext = decrypt(msg["payload"], self._privkey, peer.armored_pubkey)
        except SignatureError:
            await self._safe_send_error(ws, 4003, "PGP signature invalid")
            return
        except Exception as exc:
            logger.debug("Decryption error from %s: %s", peer.alias, exc)
            await self._safe_send_error(ws, 4004, "decryption failed")
            return

        logger.debug(
            "Message from %s (room=%s): %d chars",
            peer.alias,
            peer.room_id,
            len(plaintext),
        )
        if self.on_message:
            await self.on_message(peer.alias, plaintext, peer.room_id)

    # ------------------------------------------------------------------ #
    # Outbound helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _send_message_to(self, peer: PeerSession, plaintext: str) -> None:
        """Encrypt ``plaintext`` for ``peer`` and send it."""
        try:
            with self._privkey.unlock(self._passphrase):
                payload = encrypt(plaintext, peer.armored_pubkey, self._privkey)
        except Exception as exc:
            logger.error("Failed to encrypt for %s: %s", peer.alias, exc)
            return

        try:
            await peer.ws.send(
                json.dumps(
                    {
                        "type": "message",
                        "id": str(uuid.uuid4()),
                        "payload": payload,
                        "timestamp": int(time.time() * 1000),
                    }
                )
            )
        except websockets.exceptions.ConnectionClosed:
            logger.debug(
                "Connection closed before message could be sent to %s", peer.alias
            )

    @staticmethod
    async def _safe_send_error(ws: ServerConnection, code: int, reason: str) -> None:
        """Send a protocol error frame, ignoring a closed connection."""
        try:
            await ws.send(json.dumps({"type": "error", "code": code, "reason": reason}))
        except websockets.exceptions.ConnectionClosed:
            pass
