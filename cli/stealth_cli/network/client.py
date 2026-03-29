"""WebSocket client — stealth-message protocol joiner (protocol.md §1–§4).

Connects to a host running :class:`~stealth_cli.network.server.StealthServer`,
performs the handshake, and provides a simple API for sending encrypted
messages, pinging, and disconnecting cleanly.

Usage example::

    client = StealthClient("Bob", armored_privkey, passphrase)

    async def on_msg(plaintext: str) -> None:
        print(f"[server] {plaintext}")

    client.on_message = on_msg
    await client.connect("ws://192.168.1.10:8765")

    print("Server fingerprint:", client.peer_fingerprint)
    await client.send_message("Hello!")
    rtt_ms = await client.ping()
    await client.disconnect()

All callbacks must be ``async def`` functions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

import websockets
import websockets.exceptions
from websockets.asyncio.client import ClientConnection, connect

from stealth_cli.crypto.keys import get_fingerprint, load_private_key
from stealth_cli.crypto.messages import decrypt, encrypt
from stealth_cli.exceptions import ProtocolError, SignatureError

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1"
HANDSHAKE_TIMEOUT = 10.0  # seconds — protocol §1.1
PONG_TIMEOUT = 10.0  # seconds — protocol §3.2


class StealthClient:
    """WebSocket client implementing the stealth-message protocol.

    Attributes:
        on_message: Called when a decrypted message arrives from the server.
            Signature: ``async def cb(plaintext: str) -> None``
        on_disconnected: Called when the connection is closed by either side.
            Signature: ``async def cb() -> None``
    """

    def __init__(
        self,
        alias: str,
        armored_privkey: str,
        passphrase: str,
    ) -> None:
        self._alias: str = alias[:64]  # §1.1: max 64 UTF-8 chars
        self._privkey = load_private_key(armored_privkey, passphrase)
        self._passphrase: str = passphrase
        self._armored_pubkey: str = str(self._privkey.pubkey)

        self._ws: ClientConnection | None = None
        self._recv_task: asyncio.Task[None] | None = None
        self._pong_event: asyncio.Event | None = None

        # Peer state — populated after a successful handshake.
        self._peer_alias: str | None = None
        self._peer_armored_pubkey: str | None = None
        self._peer_fingerprint: str | None = None

        # Public callbacks.
        self.on_message: Callable[[str], Awaitable[None]] | None = None
        self.on_disconnected: Callable[[], Awaitable[None]] | None = None

    # ------------------------------------------------------------------ #
    # Peer identity (available after connect)                              #
    # ------------------------------------------------------------------ #

    @property
    def peer_alias(self) -> str:
        """Alias of the connected server peer."""
        if self._peer_alias is None:
            raise RuntimeError("Not connected — call connect() first")
        return self._peer_alias

    @property
    def peer_fingerprint(self) -> str:
        """PGP fingerprint of the server's public key (groups of 4 chars)."""
        if self._peer_fingerprint is None:
            raise RuntimeError("Not connected — call connect() first")
        return self._peer_fingerprint

    @property
    def peer_armored_pubkey(self) -> str:
        """ASCII-armored PGP public key of the connected server."""
        if self._peer_armored_pubkey is None:
            raise RuntimeError("Not connected — call connect() first")
        return self._peer_armored_pubkey

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def connect(self, uri: str) -> None:
        """Connect to a StealthServer, perform the handshake, and start receiving.

        Args:
            uri: WebSocket URI, e.g. ``"ws://localhost:8765"``.

        Raises:
            TimeoutError: If the handshake is not completed within 10 s.
            :exc:`~stealth_cli.exceptions.ProtocolError`: On protocol violations.
            :exc:`websockets.exceptions.WebSocketException`: On connection failure.
        """
        # Disable websockets' built-in ping so our own protocol ping/pong (§3.2)
        # is the only keep-alive in play.
        self._ws = await connect(uri, ping_interval=None)
        try:
            await asyncio.wait_for(self._handshake(), timeout=HANDSHAKE_TIMEOUT)
        except (asyncio.TimeoutError, ProtocolError, Exception):
            await self._ws.close()
            self._ws = None
            raise

        # Start background receive loop.
        self._recv_task = asyncio.create_task(
            self._receive_loop(), name="stealth-client-recv"
        )

    async def disconnect(self) -> None:
        """Send a ``bye`` frame, close the connection, and stop the receive loop."""
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "bye"}))
                await self._ws.close()
            except websockets.exceptions.ConnectionClosed:
                pass

        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None

    async def send_message(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` for the server and send a §2.1 message.

        Args:
            plaintext: UTF-8 text to send.

        Raises:
            RuntimeError: If not connected.
        """
        if self._ws is None or self._peer_armored_pubkey is None:
            raise RuntimeError("Not connected")

        with self._privkey.unlock(self._passphrase):
            payload = encrypt(plaintext, self._peer_armored_pubkey, self._privkey)

        await self._ws.send(
            json.dumps(
                {
                    "type": "message",
                    "id": str(uuid.uuid4()),
                    "payload": payload,
                    "timestamp": int(time.time() * 1000),
                }
            )
        )

    async def ping(self) -> float:
        """Send a protocol ``ping`` and wait for the server's ``pong``.

        Returns:
            Round-trip time in milliseconds.

        Raises:
            RuntimeError: If not connected.
            TimeoutError: If no ``pong`` is received within 10 s (§3.2).
        """
        if self._ws is None:
            raise RuntimeError("Not connected")

        self._pong_event = asyncio.Event()
        start = time.monotonic()
        await self._ws.send(json.dumps({"type": "ping"}))

        try:
            await asyncio.wait_for(self._pong_event.wait(), timeout=PONG_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                "No pong received within 10 seconds (§3.2)"
            ) from exc

        return (time.monotonic() - start) * 1000.0

    # ------------------------------------------------------------------ #
    # Handshake — §1.1                                                     #
    # ------------------------------------------------------------------ #

    async def _handshake(self) -> None:
        """Client-side handshake: send hello → receive server hello."""
        assert self._ws is not None

        # Client sends first (§1.1).
        await self._ws.send(
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

        raw = await self._ws.recv()
        try:
            msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProtocolError("invalid JSON in server hello", 4002) from exc

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

        try:
            peer_armored = base64.urlsafe_b64decode(
                msg["pubkey"].encode("ascii") + b"=="
            ).decode("utf-8")
        except Exception as exc:
            raise ProtocolError("invalid pubkey encoding in server hello", 4002) from exc

        self._peer_alias = str(msg["alias"])[:64]
        self._peer_armored_pubkey = peer_armored
        self._peer_fingerprint = get_fingerprint(peer_armored)

    # ------------------------------------------------------------------ #
    # Receive loop                                                         #
    # ------------------------------------------------------------------ #

    async def _receive_loop(self) -> None:
        """Background task: read frames from the WebSocket and dispatch them."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                await self._dispatch(raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Receive loop error: %s", exc)
        finally:
            if self.on_disconnected:
                await self.on_disconnected()

    async def _dispatch(self, raw: str | bytes) -> None:
        """Parse and route one incoming WebSocket frame."""
        try:
            msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._safe_send_error(4002, "invalid JSON")
            return

        msg_type = msg.get("type")

        if msg_type == "message":
            await self._handle_chat(msg)
        elif msg_type == "pong":
            # Wake up any pending ping() call.
            if self._pong_event is not None and not self._pong_event.is_set():
                self._pong_event.set()
        elif msg_type == "ping":
            # Server may also send pings — reply with pong.
            assert self._ws is not None
            await self._ws.send(json.dumps({"type": "pong"}))
        elif msg_type == "bye":
            assert self._ws is not None
            await self._ws.close()
        elif msg_type == "error":
            logger.warning(
                "Error from server: code=%s reason=%s",
                msg.get("code"),
                msg.get("reason"),
            )
        elif msg_type is None:
            await self._safe_send_error(4002, "missing 'type' field")
        else:
            # Unknown type → ignore silently for forward compatibility (§5).
            logger.debug("Ignoring unknown message type %r from server", msg_type)

    async def _handle_chat(self, msg: dict[str, Any]) -> None:
        """Decrypt and deliver a §2.1 chat message."""
        for required in ("id", "payload", "timestamp"):
            if required not in msg:
                await self._safe_send_error(
                    4002, f"message missing field: {required!r}"
                )
                return

        try:
            with self._privkey.unlock(self._passphrase):
                plaintext = decrypt(
                    msg["payload"], self._privkey, self._peer_armored_pubkey  # type: ignore[arg-type]
                )
        except SignatureError:
            await self._safe_send_error(4003, "PGP signature invalid")
            return
        except Exception as exc:
            logger.debug("Decryption error: %s", exc)
            await self._safe_send_error(4004, "decryption failed")
            return

        if self.on_message:
            await self.on_message(plaintext)

    async def _safe_send_error(self, code: int, reason: str) -> None:
        """Send an error frame, ignoring a closed connection."""
        if self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps({"type": "error", "code": code, "reason": reason})
            )
        except websockets.exceptions.ConnectionClosed:
            pass
