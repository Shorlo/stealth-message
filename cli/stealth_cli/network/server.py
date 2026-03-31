"""WebSocket server — stealth-message protocol host (protocol.md §1–§4).

Room model
----------
Rooms can be **1-on-1** (default, max 1 peer) or **group** (unlimited peers
with host-approval gate).

* 1-on-1 room: second peer gets error 4006 immediately.
* Group room:  every peer gets a ``pending`` message and waits up to
  JOIN_REQUEST_TIMEOUT seconds for the host to ``/allow`` or ``/deny`` them.
  The ``on_join_request`` callback fires so the host UI can display the
  prompt.

The host can also call ``move_peer(alias, target_room)`` which sends a
``move`` message to that peer so their client can switch rooms automatically.
If the target is occupied the room is automatically converted to a group room
and the incoming peer is pre-approved (no approval prompt).

Usage example::

    server = StealthServer("Alice", armored_privkey, passphrase,
                           rooms=["pepe", "juan"])

    async def on_join_request(alias, fingerprint, room_id):
        print(f"{alias} wants to join {room_id}")

    server.on_join_request = on_join_request
    await server.start(host="0.0.0.0", port=8765)

    await server.approve_join("Pepe")     # or deny_join(...)
    await server.move_peer("Juan", "pepe")
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
HANDSHAKE_TIMEOUT = 10.0      # seconds — protocol §1.1
JOIN_REQUEST_TIMEOUT = 60.0   # seconds — host must respond within this time


# --------------------------------------------------------------------------- #
# Per-connection state                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class PeerSession:
    """State associated with one connected peer."""

    ws: ServerConnection
    alias: str
    armored_pubkey: str
    fingerprint: str
    room_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PendingPeer:
    """A peer waiting for host approval to enter a group room."""

    session: PeerSession
    room_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False


# --------------------------------------------------------------------------- #
# Server                                                                        #
# --------------------------------------------------------------------------- #


class StealthServer:
    """WebSocket host implementing the stealth-message protocol.

    Supports multiple rooms:
    - 1-on-1 rooms (default): exactly one peer; second attempt gets 4006.
    - Group rooms: multiple peers; new peers wait for host approval.

    Callbacks
    ---------
    on_peer_connected(alias, fingerprint, room_id)
    on_message(alias, plaintext, room_id)
    on_peer_disconnected(alias, room_id)
    on_join_request(alias, fingerprint, room_id)  — group rooms only
    """

    def __init__(
        self,
        alias: str,
        armored_privkey: str,
        passphrase: str,
        rooms: list[str] | None = None,
        group_rooms: list[str] | None = None,
    ) -> None:
        self._alias: str = alias[:64]
        self._privkey = load_private_key(armored_privkey, passphrase)
        self._passphrase: str = passphrase
        self._armored_pubkey: str = str(self._privkey.pubkey)

        # Allowed rooms: None → accept any name; set → only those names.
        self._allowed_rooms: set[str] | None = (
            set(rooms) if rooms is not None else None
        )
        # Group rooms allow multiple peers (with host approval).
        self._group_rooms: set[str] = set(group_rooms or [])

        # room_id → list[PeerSession]  (max 1 for 1:1 rooms, N for group rooms)
        self._rooms: dict[str, list[PeerSession]] = {}
        # Pending join requests keyed by session id.
        self._pending: dict[str, PendingPeer] = {}
        # alias → room_id for host-initiated moves (bypass approval).
        self._pre_approved: dict[str, str] = {}

        self._ws_server: Any = None
        self._server_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._started_event: asyncio.Event | None = None

        # Public callbacks — set before calling start().
        self.on_peer_connected: Callable[[str, str, str], Awaitable[None]] | None = None
        self.on_message: Callable[[str, str, str], Awaitable[None]] | None = None
        self.on_peer_disconnected: Callable[[str, str], Awaitable[None]] | None = None
        self.on_join_request: Callable[[str, str, str], Awaitable[None]] | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def start(self, host: str = "localhost", port: int = 0) -> None:
        self._stop_event = asyncio.Event()
        self._started_event = asyncio.Event()
        self._server_task = asyncio.create_task(
            self._run(host, port), name="stealth-server"
        )
        await self._started_event.wait()

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

    @property
    def port(self) -> int:
        if self._ws_server is None:
            raise RuntimeError("Server has not been started yet")
        return self._ws_server.sockets[0].getsockname()[1]

    @property
    def connected_peers(self) -> list[str]:
        """Aliases of all connected peers across all rooms."""
        return [p.alias for peers in self._rooms.values() for p in peers]

    @property
    def room_peers(self) -> dict[str, list[str] | None]:
        """Map of room_id → list of peer aliases (``None`` if empty)."""
        result: dict[str, list[str] | None] = {}
        if self._allowed_rooms is not None:
            for r in self._allowed_rooms:
                result[r] = None
        for room_id, peers in self._rooms.items():
            result[room_id] = [p.alias for p in peers] if peers else None
        return result

    def add_room(self, room_id: str, group: bool = False) -> None:
        """Add a new room (or convert existing) at runtime."""
        room_id = room_id[:64]
        if self._allowed_rooms is not None:
            self._allowed_rooms.add(room_id)
        if group:
            self._group_rooms.add(room_id)

    def make_group_room(self, room_id: str) -> None:
        """Convert a room to group mode (multiple peers, host approval required)."""
        self._group_rooms.add(room_id)
        if self._allowed_rooms is not None:
            self._allowed_rooms.add(room_id)
        # Notify all connected peers of the updated group room list.
        asyncio.get_running_loop().create_task(self._broadcast_roomlist())

    def is_group_room(self, room_id: str) -> bool:
        return room_id in self._group_rooms

    def approve_join(self, alias: str) -> None:
        """Approve a pending join request by peer alias."""
        for entry in self._pending.values():
            if entry.session.alias == alias:
                entry.approved = True
                entry.event.set()
                return
        raise ValueError(f"No pending join request from {alias!r}")

    def deny_join(self, alias: str) -> None:
        """Deny a pending join request by peer alias."""
        for entry in self._pending.values():
            if entry.session.alias == alias:
                entry.approved = False
                entry.event.set()
                return
        raise ValueError(f"No pending join request from {alias!r}")

    @property
    def pending_requests(self) -> list[tuple[str, str, str]]:
        """List of (alias, fingerprint, room_id) for pending join requests."""
        return [
            (e.session.alias, e.session.fingerprint, e.room_id)
            for e in self._pending.values()
        ]

    async def move_peer(self, alias: str, target_room: str) -> None:
        """Send a ``move`` message to a peer, pre-approving them for ``target_room``.

        The target room is automatically converted to a group room if it
        already has a peer.
        """
        target_room = target_room[:64]
        # Find the peer.
        peer: PeerSession | None = None
        for peers in self._rooms.values():
            for p in peers:
                if p.alias == alias:
                    peer = p
                    break

        if peer is None:
            raise ValueError(f"No connected peer with alias {alias!r}")

        # If target room already has peers, make it a group room.
        if self._rooms.get(target_room):
            self.make_group_room(target_room)

        # Pre-approve this alias for the target room (bypasses approval prompt).
        self._pre_approved[alias] = target_room

        # Ensure the target room is accessible.
        if self._allowed_rooms is not None:
            self._allowed_rooms.add(target_room)

        try:
            await peer.ws.send(
                json.dumps({"type": "move", "room": target_room})
            )
        except websockets.exceptions.ConnectionClosed:
            self._pre_approved.pop(alias, None)
            raise

    async def broadcast(self, plaintext: str) -> None:
        """Encrypt and send to every connected peer across all rooms."""
        for peers in list(self._rooms.values()):
            for peer in list(peers):
                await self._send_message_to(peer, plaintext)

    async def send_to_room(self, room_id: str, plaintext: str) -> None:
        """Encrypt and send to all peers in the given room."""
        peers = self._rooms.get(room_id, [])
        if not peers:
            raise ValueError(f"No peer connected in room {room_id!r}")
        for peer in list(peers):
            await self._send_message_to(peer, plaintext)

    async def send_to(self, alias: str, plaintext: str) -> None:
        """Encrypt and send to the peer with the given alias."""
        for peers in self._rooms.values():
            for peer in peers:
                if peer.alias == alias:
                    await self._send_message_to(peer, plaintext)
                    return
        raise ValueError(f"No connected peer with alias {alias!r}")

    # ------------------------------------------------------------------ #
    # Server lifecycle                                                     #
    # ------------------------------------------------------------------ #

    async def _run(self, host: str, port: int) -> None:
        async with serve(
            self._handle_connection, host, port, ping_interval=None
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
        # Read the first frame to decide: listrooms query or normal hello.
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
        except asyncio.TimeoutError:
            await self._safe_send_error(ws, 4005, "handshake timeout")
            return
        except websockets.exceptions.ConnectionClosed:
            return

        try:
            first_msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._safe_send_error(ws, 4002, "invalid JSON")
            return

        # Handle lightweight room-discovery request (no auth needed).
        if first_msg.get("type") == "listrooms":
            await self._handle_listrooms(ws)
            return

        peer: PeerSession | None = None
        pending_entry: PendingPeer | None = None
        try:
            peer, pending_entry = await asyncio.wait_for(
                self._do_handshake(ws, first_msg=first_msg), timeout=HANDSHAKE_TIMEOUT
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

        # If this is a group-room join that requires host approval, wait here —
        # outside the HANDSHAKE_TIMEOUT so the host has the full JOIN_REQUEST_TIMEOUT.
        if pending_entry is not None:
            try:
                await asyncio.wait_for(
                    pending_entry.event.wait(), timeout=JOIN_REQUEST_TIMEOUT
                )
            except asyncio.TimeoutError:
                del self._pending[peer.id]
                await self._safe_send_error(ws, 4008, "join request timed out")
                return

            del self._pending[peer.id]

            if not pending_entry.approved:
                await self._safe_send_error(ws, 4008, "join request denied by host")
                return

            try:
                await ws.send(json.dumps({"type": "approved"}))
            except websockets.exceptions.ConnectionClosed:
                return

        self._rooms.setdefault(peer.room_id, []).append(peer)
        logger.info("Peer connected: %s  fp=%s  room=%s", peer.alias, peer.fingerprint, peer.room_id)

        # Send the current group room list to the newly connected peer.
        await self._send_roomlist_to(peer)

        # In group rooms, broadcast updated peer list to all peers in the room.
        if peer.room_id in self._group_rooms:
            await self._broadcast_peerlist(peer.room_id)

        if self.on_peer_connected:
            await self.on_peer_connected(peer.alias, peer.fingerprint, peer.room_id)

        try:
            async for raw in ws:
                await self._dispatch(ws, peer, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            room_list = self._rooms.get(peer.room_id, [])
            if peer in room_list:
                room_list.remove(peer)
            if not room_list:
                self._rooms.pop(peer.room_id, None)
            logger.info("Peer disconnected: %s  room=%s", peer.alias, peer.room_id)
            # Broadcast updated peer list after someone leaves the group room.
            if peer.room_id in self._group_rooms:
                await self._broadcast_peerlist(peer.room_id)
            if self.on_peer_disconnected:
                await self.on_peer_disconnected(peer.alias, peer.room_id)

    # ------------------------------------------------------------------ #
    # Handshake — §1.1                                                     #
    # ------------------------------------------------------------------ #

    async def _do_handshake(
        self, ws: ServerConnection, *, first_msg: dict[str, Any] | None = None
    ) -> tuple[PeerSession, PendingPeer | None]:
        if first_msg is not None:
            msg = first_msg
        else:
            raw = await ws.recv()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ProtocolError("malformed hello: invalid JSON", 4002) from exc

        if msg.get("type") != "hello":
            raise ProtocolError(f"expected hello, got {msg.get('type')!r}", 4002)

        if str(msg.get("version")) != PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol version {msg.get('version')!r}", 4001
            )

        for required in ("alias", "pubkey"):
            if not msg.get(required):
                raise ProtocolError(f"hello missing field: {required!r}", 4002)

        room_id = str(msg.get("room") or "default")[:64] or "default"

        if self._allowed_rooms is not None and room_id not in self._allowed_rooms:
            raise ProtocolError(f"room {room_id!r} not found on this server", 4007)

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

        existing = self._rooms.get(room_id, [])
        is_group = room_id in self._group_rooms
        is_pre_approved = self._pre_approved.get(peer_alias) == room_id

        if existing and not is_group and not is_pre_approved:
            # 1-on-1 room already occupied → reject.
            raise ProtocolError(f"room {room_id!r} is already occupied", 4006)

        if existing and is_pre_approved:
            # Host-initiated move: remove from pre-approval list and proceed.
            self._pre_approved.pop(peer_alias, None)

        # Send our hello.
        await ws.send(
            json.dumps({
                "type": "hello",
                "version": PROTOCOL_VERSION,
                "alias": self._alias,
                "pubkey": base64.urlsafe_b64encode(
                    self._armored_pubkey.encode("utf-8")
                ).decode("ascii"),
            })
        )

        peer = PeerSession(
            ws=ws,
            alias=peer_alias,
            armored_pubkey=peer_armored,
            fingerprint=peer_fp,
            room_id=room_id,
        )

        if is_group and not is_pre_approved:
            # Group room → pending approval flow for every peer (including the first).
            # We send the server hello FIRST so the client knows who the host is,
            # then send `pending` so the client can display a waiting message.
            pending = PendingPeer(session=peer, room_id=room_id)
            self._pending[peer.id] = pending

            try:
                await ws.send(json.dumps({"type": "pending"}))
            except websockets.exceptions.ConnectionClosed:
                del self._pending[peer.id]
                raise

            # Notify the host UI.
            if self.on_join_request:
                await self.on_join_request(peer_alias, peer_fp, room_id)

            # Return the pending entry so _handle_connection can wait for approval
            # outside the HANDSHAKE_TIMEOUT.
            return peer, pending

        return peer, None

    # ------------------------------------------------------------------ #
    # Message dispatch — §2, §3, §4                                        #
    # ------------------------------------------------------------------ #

    async def _dispatch(
        self, ws: ServerConnection, peer: PeerSession, raw: str | bytes
    ) -> None:
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
            pass
        elif msg_type == "error":
            logger.warning(
                "Error from peer %s (room=%s): code=%s reason=%s",
                peer.alias, peer.room_id, msg.get("code"), msg.get("reason"),
            )
        elif msg_type is None:
            await self._safe_send_error(ws, 4002, "missing 'type' field")
        else:
            logger.debug("Ignoring unknown message type %r from %s", msg_type, peer.alias)

    async def _handle_chat(
        self, ws: ServerConnection, peer: PeerSession, msg: dict[str, Any]
    ) -> None:
        for required in ("id", "payload", "timestamp"):
            if required not in msg:
                await self._safe_send_error(ws, 4002, f"message missing field: {required!r}")
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

        logger.debug("Message from %s (room=%s): %d chars", peer.alias, peer.room_id, len(plaintext))

        if self.on_message:
            await self.on_message(peer.alias, plaintext, peer.room_id)

        # In group rooms, forward the message to all other peers in the room.
        if peer.room_id in self._group_rooms:
            for other in list(self._rooms.get(peer.room_id, [])):
                if other.id != peer.id:
                    await self._send_message_to(other, plaintext, sender=peer.alias)

    # ------------------------------------------------------------------ #
    # Outbound helpers                                                     #
    # ------------------------------------------------------------------ #

    def _rooms_info(self) -> list[dict[str, Any]]:
        """Return room info for discovery — no peer names, only counts."""
        all_rooms: set[str] = set(self._allowed_rooms or []) | set(self._rooms.keys())
        result = []
        for room_id in sorted(all_rooms):
            is_group = room_id in self._group_rooms
            peer_count = len(self._rooms.get(room_id, []))
            if is_group:
                result.append({"id": room_id, "kind": "group", "peers": peer_count})
            else:
                result.append(
                    {"id": room_id, "kind": "1:1", "peers": peer_count, "available": peer_count == 0}
                )
        return result

    async def _handle_listrooms(self, ws: ServerConnection) -> None:
        """Respond to a listrooms query and close the connection."""
        try:
            await ws.send(json.dumps({"type": "roomsinfo", "rooms": self._rooms_info()}))
            await ws.close()
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _send_roomlist_to(self, peer: PeerSession) -> None:
        """Send the current group room list to a single peer."""
        frame = json.dumps({"type": "roomlist", "groups": sorted(self._group_rooms)})
        try:
            await peer.ws.send(frame)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _broadcast_peerlist(self, room_id: str) -> None:
        """Send the updated peer list to all peers in a group room.

        Each peer receives the aliases and fingerprints of all OTHER peers in
        the room (not themselves, since they already know their own identity).
        """
        peers_in_room = list(self._rooms.get(room_id, []))
        for peer in peers_in_room:
            others = [
                {"alias": p.alias, "fingerprint": p.fingerprint}
                for p in peers_in_room
                if p.id != peer.id
            ]
            frame = json.dumps({"type": "peerlist", "peers": others})
            try:
                await peer.ws.send(frame)
            except websockets.exceptions.ConnectionClosed:
                pass

    async def _broadcast_roomlist(self) -> None:
        """Send the updated group room list to all connected peers."""
        frame = json.dumps({"type": "roomlist", "groups": sorted(self._group_rooms)})
        for peers in list(self._rooms.values()):
            for peer in list(peers):
                try:
                    await peer.ws.send(frame)
                except websockets.exceptions.ConnectionClosed:
                    pass

    async def _send_message_to(
        self, peer: PeerSession, plaintext: str, sender: str | None = None
    ) -> None:
        try:
            with self._privkey.unlock(self._passphrase):
                payload = encrypt(plaintext, peer.armored_pubkey, self._privkey)
        except Exception as exc:
            logger.error("Failed to encrypt for %s: %s", peer.alias, exc)
            return

        frame: dict[str, Any] = {
            "type": "message",
            "id": str(uuid.uuid4()),
            "payload": payload,
            "timestamp": int(time.time() * 1000),
        }
        if sender is not None:
            frame["sender"] = sender

        try:
            await peer.ws.send(json.dumps(frame))
        except websockets.exceptions.ConnectionClosed:
            logger.debug("Connection closed before message could be sent to %s", peer.alias)

    @staticmethod
    async def _safe_send_error(ws: ServerConnection, code: int, reason: str) -> None:
        try:
            await ws.send(json.dumps({"type": "error", "code": code, "reason": reason}))
        except websockets.exceptions.ConnectionClosed:
            pass
