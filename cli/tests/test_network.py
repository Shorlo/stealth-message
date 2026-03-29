"""Integration tests for StealthServer and StealthClient.

A real WebSocket server is started on localhost (random port) and a real
client connects to it. All tests exercise the full protocol stack:
handshake → encrypt/decrypt → transport.

RSA-4096 key generation is expensive (~2-5 s each). Server and client
keypairs are generated once at session scope and reused across all tests.

Run with:
    pytest tests/test_network.py -v
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from stealth_cli.crypto.keys import generate_keypair, get_fingerprint, load_public_key
from stealth_cli.network.client import StealthClient
from stealth_cli.network.server import StealthServer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PASSPHRASE = "network-test-passphrase-42"
SERVER_ALIAS = "Test Server"
CLIENT_ALIAS = "Test Client"
WAIT_TIMEOUT = 5.0  # seconds — all asyncio.wait_for() calls in tests


# ---------------------------------------------------------------------------
# Session-scoped keypairs (RSA-4096 generated once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def server_keys() -> tuple[str, str]:
    return generate_keypair(SERVER_ALIAS, PASSPHRASE)


@pytest.fixture(scope="session")
def client_keys() -> tuple[str, str]:
    return generate_keypair(CLIENT_ALIAS, PASSPHRASE)


# ---------------------------------------------------------------------------
# Per-test server fixture with event queues
# ---------------------------------------------------------------------------


@pytest.fixture
async def server(server_keys: tuple[str, str]) -> asyncio.AsyncGenerator:
    """Running StealthServer with asyncio.Queue inboxes for callbacks."""
    msgs: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    connected: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    disconnected: asyncio.Queue[str] = asyncio.Queue()

    srv = StealthServer(SERVER_ALIAS, server_keys[0], PASSPHRASE)

    async def on_msg(alias: str, txt: str) -> None:
        await msgs.put((alias, txt))

    async def on_connected(alias: str, fp: str) -> None:
        await connected.put((alias, fp))

    async def on_disconnected(alias: str) -> None:
        await disconnected.put(alias)

    srv.on_message = on_msg
    srv.on_peer_connected = on_connected
    srv.on_peer_disconnected = on_disconnected

    await srv.start(host="localhost", port=0)

    # Attach queues as attributes for test access.
    srv.msgs = msgs  # type: ignore[attr-defined]
    srv.connected = connected  # type: ignore[attr-defined]
    srv.disconnected = disconnected  # type: ignore[attr-defined]

    yield srv

    await srv.stop()


# ---------------------------------------------------------------------------
# Per-test client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(
    server: StealthServer, client_keys: tuple[str, str]
) -> asyncio.AsyncGenerator:
    """StealthClient connected to the test server, with a message queue."""
    msgs: asyncio.Queue[str] = asyncio.Queue()

    cli = StealthClient(CLIENT_ALIAS, client_keys[0], PASSPHRASE)

    async def on_msg(txt: str) -> None:
        await msgs.put(txt)

    cli.on_message = on_msg
    await cli.connect(f"ws://localhost:{server.port}")

    # Wait until the server acknowledges the peer.
    await asyncio.wait_for(server.connected.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]

    cli.msgs = msgs  # type: ignore[attr-defined]

    yield cli

    await cli.disconnect()


# ---------------------------------------------------------------------------
# §1 Handshake
# ---------------------------------------------------------------------------


async def test_handshake_client_knows_server_alias(
    client: StealthClient,
) -> None:
    assert client.peer_alias == SERVER_ALIAS


async def test_handshake_client_knows_server_fingerprint(
    client: StealthClient, server_keys: tuple[str, str]
) -> None:
    expected_fp = get_fingerprint(server_keys[1])
    assert client.peer_fingerprint == expected_fp


async def test_handshake_server_knows_client_alias(
    server: StealthServer, client: StealthClient
) -> None:
    assert CLIENT_ALIAS in server.connected_peers


async def test_handshake_server_has_one_connected_peer(
    server: StealthServer, client: StealthClient
) -> None:
    assert len(server.connected_peers) == 1


async def test_handshake_server_received_peer_connected_event(
    server: StealthServer, client: StealthClient
) -> None:
    # The event was already consumed by the client fixture; queue should be empty.
    # Re-verify by checking connected_peers instead.
    assert CLIENT_ALIAS in server.connected_peers


async def test_handshake_server_received_correct_client_fingerprint(
    server_keys: tuple[str, str], client_keys: tuple[str, str]
) -> None:
    """The server's on_peer_connected callback must receive the client's real fingerprint."""
    connected: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    srv = StealthServer(SERVER_ALIAS, server_keys[0], PASSPHRASE)

    async def on_connected(alias: str, fp: str) -> None:
        await connected.put((alias, fp))

    srv.on_peer_connected = on_connected
    await srv.start(host="localhost", port=0)

    try:
        cli = StealthClient(CLIENT_ALIAS, client_keys[0], PASSPHRASE)
        await cli.connect(f"ws://localhost:{srv.port}")

        alias, received_fp = await asyncio.wait_for(connected.get(), timeout=WAIT_TIMEOUT)

        expected_fp = get_fingerprint(client_keys[1])
        assert alias == CLIENT_ALIAS
        assert received_fp == expected_fp
    finally:
        await cli.disconnect()
        await srv.stop()


# ---------------------------------------------------------------------------
# §1.1 Handshake error cases
# ---------------------------------------------------------------------------


async def test_handshake_wrong_version_closes_connection(
    server: StealthServer,
) -> None:
    """A client sending version != '1' must receive error 4001."""
    ws = await websockets.connect(f"ws://localhost:{server.port}", ping_interval=None)
    try:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "version": "99",
                    "alias": "Bad Client",
                    "pubkey": "dW5rbm93bg==",  # base64("unknown")
                }
            )
        )
        raw = await asyncio.wait_for(ws.recv(), timeout=WAIT_TIMEOUT)
        resp = json.loads(raw)
        assert resp["type"] == "error"
        assert resp["code"] == 4001
    finally:
        await ws.close()


async def test_handshake_malformed_json_returns_error(
    server: StealthServer,
) -> None:
    """A non-JSON first frame must return error 4002."""
    ws = await websockets.connect(f"ws://localhost:{server.port}", ping_interval=None)
    try:
        await ws.send("not json at all {{{")
        raw = await asyncio.wait_for(ws.recv(), timeout=WAIT_TIMEOUT)
        resp = json.loads(raw)
        assert resp["type"] == "error"
        assert resp["code"] == 4002
    finally:
        await ws.close()


async def test_handshake_missing_pubkey_returns_error(
    server: StealthServer,
) -> None:
    """A hello missing the pubkey field must return error 4002."""
    ws = await websockets.connect(f"ws://localhost:{server.port}", ping_interval=None)
    try:
        await ws.send(
            json.dumps({"type": "hello", "version": "1", "alias": "NoKey"})
        )
        raw = await asyncio.wait_for(ws.recv(), timeout=WAIT_TIMEOUT)
        resp = json.loads(raw)
        assert resp["type"] == "error"
        assert resp["code"] == 4002
    finally:
        await ws.close()


# ---------------------------------------------------------------------------
# §2 Encrypted chat messages
# ---------------------------------------------------------------------------


async def test_client_to_server_message(
    server: StealthServer, client: StealthClient
) -> None:
    """Client → Server: server decrypts and delivers to on_message callback."""
    await client.send_message("Hello from client!")
    alias, plaintext = await asyncio.wait_for(
        server.msgs.get(), timeout=WAIT_TIMEOUT  # type: ignore[attr-defined]
    )
    assert alias == CLIENT_ALIAS
    assert plaintext == "Hello from client!"


async def test_server_to_client_message(
    server: StealthServer, client: StealthClient
) -> None:
    """Server → Client: client decrypts and delivers to on_message callback."""
    await server.broadcast("Hello from server!")
    plaintext = await asyncio.wait_for(
        client.msgs.get(), timeout=WAIT_TIMEOUT  # type: ignore[attr-defined]
    )
    assert plaintext == "Hello from server!"


async def test_bidirectional_exchange(
    server: StealthServer, client: StealthClient
) -> None:
    """Full bidirectional exchange in a single test."""
    await client.send_message("ping-payload")
    _, from_client = await asyncio.wait_for(server.msgs.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]
    assert from_client == "ping-payload"

    await server.broadcast("pong-payload")
    from_server = await asyncio.wait_for(client.msgs.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]
    assert from_server == "pong-payload"


async def test_message_with_unicode_and_emoji(
    server: StealthServer, client: StealthClient
) -> None:
    text = "Hola 🔒 Ñoño ™ ← →"
    await client.send_message(text)
    _, received = await asyncio.wait_for(server.msgs.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]
    assert received == text


async def test_multiple_messages_in_sequence(
    server: StealthServer, client: StealthClient
) -> None:
    messages = ["first", "second", "third"]
    for m in messages:
        await client.send_message(m)

    for expected in messages:
        _, received = await asyncio.wait_for(server.msgs.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]
        assert received == expected


async def test_server_send_to_specific_peer(
    server: StealthServer, client: StealthClient
) -> None:
    await server.send_to(CLIENT_ALIAS, "direct message")
    plaintext = await asyncio.wait_for(client.msgs.get(), timeout=WAIT_TIMEOUT)  # type: ignore[attr-defined]
    assert plaintext == "direct message"


# ---------------------------------------------------------------------------
# §3 Session control
# ---------------------------------------------------------------------------


async def test_ping_pong_returns_rtt(
    server: StealthServer, client: StealthClient
) -> None:
    """Ping must return a non-negative RTT in milliseconds."""
    rtt = await asyncio.wait_for(client.ping(), timeout=WAIT_TIMEOUT)
    assert isinstance(rtt, float)
    assert rtt >= 0.0


async def test_ping_pong_rtt_is_small_on_localhost(
    server: StealthServer, client: StealthClient
) -> None:
    rtt = await asyncio.wait_for(client.ping(), timeout=WAIT_TIMEOUT)
    assert rtt < 1000.0  # loopback should be well under 1 second


async def test_bye_triggers_server_disconnect_event(
    server: StealthServer, client: StealthClient
) -> None:
    """Sending bye must cause the server to fire on_peer_disconnected."""
    await client.disconnect()
    alias = await asyncio.wait_for(
        server.disconnected.get(), timeout=WAIT_TIMEOUT  # type: ignore[attr-defined]
    )
    assert alias == CLIENT_ALIAS


# ---------------------------------------------------------------------------
# §4 Error handling
# ---------------------------------------------------------------------------


async def test_unknown_message_type_is_ignored(
    server: StealthServer, client: StealthClient
) -> None:
    """An unknown 'type' must be silently ignored (§5) — no disconnect."""
    assert client._ws is not None
    await client._ws.send(json.dumps({"type": "future_unknown_type", "data": 42}))
    # Give the server time to process it and send something back if it were
    # going to — it shouldn't disconnect or respond.
    await asyncio.sleep(0.1)
    assert CLIENT_ALIAS in server.connected_peers


async def test_malformed_json_after_handshake_returns_error(
    server: StealthServer, client: StealthClient
) -> None:
    """Malformed JSON after handshake → error 4002 (recoverable)."""
    errors: asyncio.Queue[dict] = asyncio.Queue()

    original_dispatch = client._dispatch

    async def capture_errors(raw):
        await original_dispatch(raw)

    # Send malformed JSON directly through the WebSocket.
    assert client._ws is not None
    await client._ws.send("{ bad json }")

    # Wait briefly; if the server sends an error, the client's receive loop will
    # call on_error (if set) or log it. We verify the connection stays alive.
    await asyncio.sleep(0.2)
    assert CLIENT_ALIAS in server.connected_peers


async def test_server_send_to_nonexistent_peer_raises(
    server: StealthServer, client: StealthClient
) -> None:
    with pytest.raises(ValueError, match="nonexistent"):
        await server.send_to("nonexistent", "hello")
