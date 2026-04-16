using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Logging;

namespace StealthMessage.Network;

/// <summary>
/// WebSocket server based on <see cref="TcpListener"/>.
/// Handles room management, peer approval, and message relay.
/// Does not require administrator privileges (unlike HttpListener with http://+).
/// </summary>
public sealed class StealthServer : IAsyncDisposable
{
    // Timeouts (protocol.md)
    private static readonly TimeSpan HandshakeTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan ApprovalTimeout  = TimeSpan.FromSeconds(60);

    private const string ProtocolVersion = "1";
    private const string WsGuid         = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

    private readonly ILogger<StealthServer> _logger;
    private TcpListener? _listener;
    private CancellationTokenSource? _cts;
    private Task? _acceptTask;

    // ---------------------------------------------------------------------------
    // Rooms and peers
    // ---------------------------------------------------------------------------

    private readonly Dictionary<string, Room> _rooms = new(StringComparer.Ordinal);
    private readonly object _lock = new();

    private sealed class Room
    {
        public required string Kind { get; init; }  // "1to1" | "group"
        public List<ConnectedPeer> Peers { get; } = new();
        public HashSet<string> PreApproved { get; } = new(StringComparer.Ordinal);
    }

    private sealed class ConnectedPeer
    {
        public required string        Alias       { get; init; }
        public required string        Fingerprint { get; init; }
        public required string        ArmoredPub  { get; init; }
        public required WebSocket     WebSocket   { get; init; }
        public required SemaphoreSlim SendLock    { get; init; }
    }

    // ---------------------------------------------------------------------------
    // Callbacks for UI
    // ---------------------------------------------------------------------------

    /// <summary>Called when a peer wants to join a group room. Return true to approve.</summary>
    public Func<string, string, Task<bool>>? OnJoinRequest { get; set; }

    /// <summary>Called when a peer connects. Parameters: alias, fingerprint, armoredPubKey.</summary>
    public Action<string, string, string>? OnPeerConnected { get; set; }

    /// <summary>Called when a peer disconnects. Parameter: alias.</summary>
    public Action<string>? OnPeerDisconnected { get; set; }

    /// <summary>Called when a message arrives. Parameters: payload, senderAlias, peerArmoredPub.</summary>
    public Func<string, string, string, Task>? OnMessage { get; set; }

    public string HostAlias   { get; private set; } = string.Empty;
    public string ArmoredPub  { get; private set; } = string.Empty;
    public string Fingerprint { get; private set; } = string.Empty;

    public StealthServer(ILogger<StealthServer> logger) => _logger = logger;

    // ---------------------------------------------------------------------------
    // Start / Stop
    // ---------------------------------------------------------------------------

    public void Start(
        int    port,
        string hostAlias,
        string armoredPub,
        string fingerprint,
        IEnumerable<(string name, string kind)>? initialRooms = null)
    {
        HostAlias   = hostAlias;
        ArmoredPub  = armoredPub;
        Fingerprint = fingerprint;

        if (initialRooms is not null)
        {
            foreach (var (name, kind) in initialRooms)
                _rooms[name] = new Room { Kind = kind };
        }

        _listener = new TcpListener(IPAddress.Any, port);
        _listener.Start();
        _logger.LogInformation("Server listening on port {Port}.", port);

        _cts        = new CancellationTokenSource();
        _acceptTask = Task.Run(() => AcceptLoopAsync(_cts.Token));
    }

    public async Task StopAsync()
    {
        _cts?.Cancel();
        _listener?.Stop();
        if (_acceptTask is not null) try { await _acceptTask; } catch { }
    }

    // ---------------------------------------------------------------------------
    // Host commands
    // ---------------------------------------------------------------------------

    public void AddRoom(string name, string kind)
    {
        lock (_lock)
            _rooms.TryAdd(name, new Room { Kind = kind });
    }

    public async Task KickAsync(string alias, string reason)
    {
        ConnectedPeer? peer = FindPeer(alias);
        if (peer is null) return;
        await SendAsync(peer, WireFrameSerializer.Serialize(new KickFrame(reason)));
        await peer.WebSocket.CloseAsync(WebSocketCloseStatus.PolicyViolation, reason,
                                         CancellationToken.None);
    }

    public async Task MoveAsync(string alias, string targetRoom)
    {
        lock (_lock)
        {
            if (_rooms.TryGetValue(targetRoom, out var r))
                r.PreApproved.Add(alias);
        }
        ConnectedPeer? peer = FindPeer(alias);
        if (peer is null) return;
        await SendAsync(peer, WireFrameSerializer.Serialize(new MoveFrame(targetRoom)));
    }

    /// <summary>Sends a pre-built message frame to a specific connected peer.</summary>
    public async Task SendToAsync(string alias, MessageFrame frame)
    {
        ConnectedPeer? peer = FindPeer(alias);
        if (peer is null) return;
        await SendAsync(peer, WireFrameSerializer.Serialize(frame));
    }

    /// <summary>Returns the decoded ASCII-armored public key of a connected peer, or null.</summary>
    public string? GetPeerPublicKey(string alias)
    {
        ConnectedPeer? peer = FindPeer(alias);
        return peer?.ArmoredPub;
    }

    // ---------------------------------------------------------------------------
    // Accept loop
    // ---------------------------------------------------------------------------

    private async Task AcceptLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            TcpClient client;
            try { client = await _listener!.AcceptTcpClientAsync(ct); }
            catch (OperationCanceledException) { break; }
            catch (SocketException) { break; }

            _ = Task.Run(() => HandleTcpClientAsync(client, ct), ct);
        }
    }

    // ---------------------------------------------------------------------------
    // TCP → WebSocket upgrade
    // ---------------------------------------------------------------------------

    private async Task HandleTcpClientAsync(TcpClient client, CancellationToken ct)
    {
        client.NoDelay = true;
        using (client)
        {
            NetworkStream stream = client.GetStream();
            try
            {
                Dictionary<string, string> headers = await ReadHttpHeadersAsync(stream, ct);

                if (!headers.TryGetValue("Sec-WebSocket-Key", out string? wsKey))
                {
                    byte[] reject = "HTTP/1.1 400 Bad Request\r\n\r\n"u8.ToArray();
                    await stream.WriteAsync(reject, ct);
                    return;
                }

                await SendWebSocketUpgradeAsync(stream, wsKey, ct);

                using WebSocket ws = WebSocket.CreateFromStream(stream,
                    new WebSocketCreationOptions
                    {
                        IsServer          = true,
                        SubProtocol       = null,
                        KeepAliveInterval = Timeout.InfiniteTimeSpan,
                    });

                await HandleConnectionAsync(ws, ct);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error during TCP/WebSocket handshake.");
            }
        }
    }

    private static async Task<Dictionary<string, string>> ReadHttpHeadersAsync(
        Stream stream, CancellationToken ct)
    {
        var headers    = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var lineBuffer = new List<byte>(256);
        var buf        = new byte[1];
        bool firstLine = true;

        while (true)
        {
            lineBuffer.Clear();
            while (true)
            {
                await stream.ReadExactlyAsync(buf, ct);
                if (buf[0] == '\n' && lineBuffer.Count > 0 && lineBuffer[^1] == '\r')
                {
                    lineBuffer.RemoveAt(lineBuffer.Count - 1);
                    break;
                }
                lineBuffer.Add(buf[0]);
            }

            if (lineBuffer.Count == 0) break;
            if (firstLine) { firstLine = false; continue; }

            string line  = Encoding.UTF8.GetString(lineBuffer.ToArray());
            int    colon = line.IndexOf(':');
            if (colon > 0)
                headers[line[..colon].Trim()] = line[(colon + 1)..].Trim();
        }

        return headers;
    }

    private static async Task SendWebSocketUpgradeAsync(
        Stream stream, string wsKey, CancellationToken ct)
    {
        string accept = Convert.ToBase64String(
            SHA1.HashData(Encoding.UTF8.GetBytes(wsKey + WsGuid)));

        string response =
            "HTTP/1.1 101 Switching Protocols\r\n" +
            "Upgrade: websocket\r\n" +
            "Connection: Upgrade\r\n" +
            $"Sec-WebSocket-Accept: {accept}\r\n" +
            "\r\n";

        await stream.WriteAsync(Encoding.UTF8.GetBytes(response), ct);
        await stream.FlushAsync(ct);
    }

    // ---------------------------------------------------------------------------
    // Per-connection handler
    // ---------------------------------------------------------------------------

    private async Task HandleConnectionAsync(WebSocket ws, CancellationToken ct)
    {
        try
        {
            string firstJson;
            try
            {
                using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeoutCts.CancelAfter(HandshakeTimeout);
                firstJson = await ReceiveOneFrameAsync(ws, timeoutCts.Token);
            }
            catch (OperationCanceledException)
            {
                await CloseAsync(ws, WebSocketCloseStatus.EndpointUnavailable, "Handshake timeout");
                return;
            }

            WireFrame first = WireFrameSerializer.Parse(firstJson);

            if (first is ListRoomsFrame)
            {
                await HandleListRoomsAsync(ws, ct);
                return;
            }

            if (first is not HelloFrame hello)
            {
                await SendErrorAsync(ws, ProtocolException.Malformed, "Expected hello or listrooms.");
                return;
            }

            if (hello.Version != ProtocolVersion)
            {
                await SendErrorAsync(ws, ProtocolException.VersionMismatch,
                    $"Server requires protocol {ProtocolVersion}.");
                return;
            }

            await HandleHelloAsync(ws, hello, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error handling connection.");
            try { await CloseAsync(ws, WebSocketCloseStatus.InternalServerError, "Internal error"); }
            catch { }
        }
    }

    // ---------------------------------------------------------------------------
    // listrooms — no auth, no handshake
    // ---------------------------------------------------------------------------

    private async Task HandleListRoomsAsync(WebSocket ws, CancellationToken ct)
    {
        List<RoomInfo> rooms;
        lock (_lock)
        {
            rooms = _rooms.Select(kv => new RoomInfo(
                Id:        kv.Key,
                Kind:      kv.Value.Kind == "1to1" ? "1:1" : kv.Value.Kind, // protocol §1: "1:1"
                Peers:     kv.Value.Peers.Count,
                Available: kv.Value.Kind == "1to1" ? kv.Value.Peers.Count == 0 : true))
            .ToList();
        }
        await SendRawAsync(ws, WireFrameSerializer.Serialize(new RoomsInfoFrame(rooms)), ct);
        await CloseAsync(ws, WebSocketCloseStatus.NormalClosure, "done");
    }

    // ---------------------------------------------------------------------------
    // Handshake and join
    // ---------------------------------------------------------------------------

    private async Task HandleHelloAsync(WebSocket ws, HelloFrame hello, CancellationToken ct)
    {
        Room? room;
        lock (_lock)
        {
            if (!_rooms.TryGetValue(hello.Room, out room))
            {
                room = new Room { Kind = "1to1" };
                _rooms[hello.Room] = room;
            }

            if (room.Kind == "1to1" && room.Peers.Count >= 1)
            {
                _ = SendErrorAsync(ws, ProtocolException.RoomFull, "Room is full.");
                return;
            }
        }

        // Group room: require host approval unless pre-approved
        bool isGroup = room.Kind == "group";
        if (isGroup)
        {
            bool preApproved;
            lock (_lock) { preApproved = room.PreApproved.Remove(hello.Alias); }

            if (!preApproved)
            {
                await SendRawAsync(ws, WireFrameSerializer.Serialize(new PendingFrame()), ct);

                bool approved = false;
                if (OnJoinRequest is not null)
                {
                    string fp = hello.PubKey.Length > 16 ? hello.PubKey[..16] + "…" : hello.PubKey;
                    using var approvalCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    approvalCts.CancelAfter(ApprovalTimeout);
                    try { approved = await OnJoinRequest(hello.Alias, fp); }
                    catch { approved = false; }
                }

                if (!approved)
                {
                    await SendErrorAsync(ws, ProtocolException.JoinDenied, "Join request denied.");
                    return;
                }

                await SendRawAsync(ws, WireFrameSerializer.Serialize(new ApprovedFrame()), ct);
            }
        }

        // Decode client's pubkey — base64url(armored_bytes) per protocol §2
        string peerArmored;
        try
        {
            peerArmored = Encoding.UTF8.GetString(Base64UrlDecode(hello.PubKey));
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Invalid pubkey encoding from '{Alias}'.", hello.Alias);
            await SendErrorAsync(ws, ProtocolException.Malformed, "Invalid pubkey encoding.");
            return;
        }

        // Send server hello — encode own pubkey as base64url(armored_bytes) per protocol §2
        string encodedPub = Base64UrlEncode(Encoding.UTF8.GetBytes(ArmoredPub));
        await SendRawAsync(ws, WireFrameSerializer.Serialize(
            new ServerHelloFrame(ProtocolVersion, HostAlias, encodedPub)), ct);

        var peer = new ConnectedPeer
        {
            Alias       = hello.Alias,
            Fingerprint = hello.Alias, // real FP computed by HostViewModel via PgpManager
            ArmoredPub  = peerArmored,
            WebSocket   = ws,
            SendLock    = new SemaphoreSlim(1, 1),
        };

        lock (_lock) { room.Peers.Add(peer); }
        OnPeerConnected?.Invoke(hello.Alias, peer.Fingerprint, peerArmored);
        _logger.LogInformation("Peer '{Alias}' joined room '{Room}'.", hello.Alias, hello.Room);

        await SendRoomListAsync(ct);
        await SendPeerListToRoomAsync(hello.Room, ct);

        try { await PeerReceiveLoopAsync(peer, hello.Room, ct); }
        finally
        {
            lock (_lock) { room.Peers.Remove(peer); }
            OnPeerDisconnected?.Invoke(hello.Alias);
            _logger.LogInformation("Peer '{Alias}' left room '{Room}'.", hello.Alias, hello.Room);
            await SendPeerListToRoomAsync(hello.Room, ct);
        }
    }

    // ---------------------------------------------------------------------------
    // Per-peer receive loop
    // ---------------------------------------------------------------------------

    private async Task PeerReceiveLoopAsync(ConnectedPeer peer, string roomName, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && peer.WebSocket.State == WebSocketState.Open)
        {
            string json;
            try { json = await ReceiveOneFrameAsync(peer.WebSocket, ct); }
            catch { break; }

            WireFrame frame;
            try { frame = WireFrameSerializer.Parse(json); }
            catch { continue; }

            switch (frame)
            {
                case MessageFrame msg:
                    await RelayMessageAsync(msg, peer, roomName, ct);
                    if (OnMessage is not null)
                        await OnMessage(msg.Payload, peer.Alias, peer.ArmoredPub);
                    break;
                case PingFrame:
                    await SendAsync(peer, WireFrameSerializer.Serialize(new PongFrame()));
                    break;
                case ByeFrame:
                    return;
                default:
                    _logger.LogDebug("Unhandled peer frame: {Type}.", frame.GetType().Name);
                    break;
            }
        }
    }

    // ---------------------------------------------------------------------------
    // Relay helpers
    // ---------------------------------------------------------------------------

    private async Task RelayMessageAsync(
        MessageFrame msg, ConnectedPeer sender, string roomName, CancellationToken ct)
    {
        Room? room;
        lock (_lock) { _rooms.TryGetValue(roomName, out room); }
        if (room is null) return;

        List<ConnectedPeer> targets;
        lock (_lock) { targets = room.Peers.Where(p => p != sender).ToList(); }

        string relayed = WireFrameSerializer.Serialize(
            msg with { Sender = room.Kind == "group" ? sender.Alias : null });

        foreach (var target in targets)
            await SendAsync(target, relayed);
    }

    private async Task SendPeerListToRoomAsync(string roomName, CancellationToken ct)
    {
        Room? room;
        lock (_lock) { _rooms.TryGetValue(roomName, out room); }
        if (room is null) return;

        List<ConnectedPeer> peers;
        lock (_lock) { peers = room.Peers.ToList(); }

        string json = WireFrameSerializer.Serialize(new PeerListFrame(
            peers.Select(p => new PeerInfo(p.Alias, p.Fingerprint)).ToList()));

        foreach (var peer in peers)
            await SendAsync(peer, json);
    }

    private async Task SendRoomListAsync(CancellationToken ct)
    {
        List<string> groupRooms;
        lock (_lock)
        {
            groupRooms = _rooms
                .Where(kv => kv.Value.Kind == "group")
                .Select(kv => kv.Key)
                .ToList();
        }
        if (groupRooms.Count == 0) return;

        string json = WireFrameSerializer.Serialize(new RoomListFrame(groupRooms));

        List<ConnectedPeer> all;
        lock (_lock) { all = _rooms.Values.SelectMany(r => r.Peers).ToList(); }
        foreach (var peer in all)
            await SendAsync(peer, json);
    }

    // ---------------------------------------------------------------------------
    // Low-level send / receive
    // ---------------------------------------------------------------------------

    private static async Task SendAsync(ConnectedPeer peer, string json)
    {
        await peer.SendLock.WaitAsync();
        try
        {
            if (peer.WebSocket.State != WebSocketState.Open) return;
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            await peer.WebSocket.SendAsync(bytes, WebSocketMessageType.Text,
                                           endOfMessage: true, CancellationToken.None);
        }
        finally { peer.SendLock.Release(); }
    }

    private static Task SendRawAsync(WebSocket ws, string json, CancellationToken ct)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        return ws.SendAsync(bytes, WebSocketMessageType.Text, endOfMessage: true, ct);
    }

    private static Task SendErrorAsync(WebSocket ws, int code, string reason)
        => SendRawAsync(ws,
               WireFrameSerializer.Serialize(new ErrorFrame(code, reason)),
               CancellationToken.None);

    private static Task CloseAsync(WebSocket ws, WebSocketCloseStatus status, string desc)
    {
        return ws.State is WebSocketState.Open or WebSocketState.CloseReceived
            ? ws.CloseAsync(status, desc, CancellationToken.None)
            : Task.CompletedTask;
    }

    private static async Task<string> ReceiveOneFrameAsync(WebSocket ws, CancellationToken ct)
    {
        var buffer = new ArraySegment<byte>(new byte[64 * 1024]);
        using var ms = new System.IO.MemoryStream();
        WebSocketReceiveResult result;
        do
        {
            result = await ws.ReceiveAsync(buffer, ct);
            if (result.MessageType == WebSocketMessageType.Close)
                throw new WebSocketException(WebSocketError.ConnectionClosedPrematurely);
            ms.Write(buffer.Array!, buffer.Offset, result.Count);
        }
        while (!result.EndOfMessage);
        return Encoding.UTF8.GetString(ms.ToArray());
    }

    private ConnectedPeer? FindPeer(string alias)
    {
        lock (_lock)
        {
            return _rooms.Values
                .SelectMany(r => r.Peers)
                .FirstOrDefault(p => string.Equals(p.Alias, alias, StringComparison.Ordinal));
        }
    }

    // ---------------------------------------------------------------------------
    // Base64 URL-safe helpers — RFC 4648 §5, no padding
    // ---------------------------------------------------------------------------

    private static string Base64UrlEncode(byte[] data)
        => Convert.ToBase64String(data).Replace('+', '-').Replace('/', '_').TrimEnd('=');

    private static byte[] Base64UrlDecode(string encoded)
    {
        string s = encoded.Replace('-', '+').Replace('_', '/');
        switch (s.Length % 4)
        {
            case 2: s += "=="; break;
            case 3: s += "=";  break;
        }
        return Convert.FromBase64String(s);
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _cts?.Dispose();
    }
}
