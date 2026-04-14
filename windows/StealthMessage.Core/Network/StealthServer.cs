using System.Net;
using System.Net.WebSockets;
using System.Text;
using Microsoft.Extensions.Logging;

namespace StealthMessage.Network;

/// <summary>
/// WebSocket server based on <see cref="HttpListener"/>.
/// Handles room management, peer approval, and message relay.
/// </summary>
public sealed class StealthServer : IAsyncDisposable
{
    // Timeouts (protocol.md)
    private static readonly TimeSpan HandshakeTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan ApprovalTimeout  = TimeSpan.FromSeconds(60);
    private static readonly TimeSpan PingInterval     = TimeSpan.FromSeconds(30);

    private const string ProtocolVersion = "0.8";

    private readonly ILogger<StealthServer> _logger;
    private readonly HttpListener _listener = new();
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
        // Pre-approved aliases (used when host moves a peer to another room)
        public HashSet<string> PreApproved { get; } = new(StringComparer.Ordinal);
    }

    private sealed class ConnectedPeer
    {
        public required string          Alias       { get; init; }
        public required string          Fingerprint { get; init; }
        public required string          ArmoredPub  { get; init; }
        public required WebSocket       WebSocket   { get; init; }
        public required SemaphoreSlim   SendLock    { get; init; }
    }

    // ---------------------------------------------------------------------------
    // Callbacks for UI
    // ---------------------------------------------------------------------------

    /// <summary>
    /// Called when a peer wants to join a group room.
    /// Return true to approve, false to deny.
    /// </summary>
    public Func<string, string, Task<bool>>? OnJoinRequest { get; set; }

    /// <summary>Called when a peer connects (after approval if group room).</summary>
    public Action<string, string>? OnPeerConnected { get; set; }

    /// <summary>Called when a peer disconnects.</summary>
    public Action<string>? OnPeerDisconnected { get; set; }

    /// <summary>Called when a new message arrives for the host's room.</summary>
    public Func<string, string, Task>? OnMessage { get; set; }

    public string HostAlias   { get; private set; } = string.Empty;
    public string ArmoredPub  { get; private set; } = string.Empty;
    public string Fingerprint { get; private set; } = string.Empty;

    public StealthServer(ILogger<StealthServer> logger) => _logger = logger;

    // ---------------------------------------------------------------------------
    // Start / Stop
    // ---------------------------------------------------------------------------

    /// <summary>
    /// Starts the HTTP listener on the specified port and begins accepting WebSocket connections.
    /// </summary>
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

        _listener.Prefixes.Add($"http://+:{port}/");
        _listener.Start();
        _logger.LogInformation("Server listening on port {Port}.", port);

        _cts        = new CancellationTokenSource();
        _acceptTask = Task.Run(() => AcceptLoopAsync(_cts.Token));
    }

    public async Task StopAsync()
    {
        _cts?.Cancel();
        _listener.Stop();
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

    /// <summary>
    /// Moves <paramref name="alias"/> to <paramref name="targetRoom"/>.
    /// Pre-approves the peer so they don't need host approval again.
    /// </summary>
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

    // ---------------------------------------------------------------------------
    // Accept loop
    // ---------------------------------------------------------------------------

    private async Task AcceptLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            HttpListenerContext ctx;
            try { ctx = await _listener.GetContextAsync(); }
            catch (HttpListenerException) { break; }
            catch (ObjectDisposedException) { break; }

            if (!ctx.Request.IsWebSocketRequest) { ctx.Response.Close(); continue; }

            _ = Task.Run(() => HandleConnectionAsync(ctx, ct), ct);
        }
    }

    // ---------------------------------------------------------------------------
    // Per-connection handler
    // ---------------------------------------------------------------------------

    private async Task HandleConnectionAsync(HttpListenerContext ctx, CancellationToken ct)
    {
        HttpListenerWebSocketContext wsCtx;
        try { wsCtx = await ctx.AcceptWebSocketAsync(null); }
        catch (Exception ex) { _logger.LogWarning(ex, "WebSocket upgrade failed."); return; }

        WebSocket ws = wsCtx.WebSocket;
        try
        {
            // Read first frame to detect listrooms vs hello
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
        finally
        {
            ws.Dispose();
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
                Kind:      kv.Value.Kind,
                Peers:     kv.Value.Peers.Count,
                Available: kv.Value.Kind == "1to1" ? kv.Value.Peers.Count == 0 : true))
            .ToList();
        }
        var frame = new RoomsInfoFrame(rooms);
        await SendRawAsync(ws, WireFrameSerializer.Serialize(frame), ct);
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
                // Create ad-hoc 1:1 room for direct connections
                room = new Room { Kind = "1to1" };
                _rooms[hello.Room] = room;
            }

            // 1:1 room full check
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

        // Send server hello
        var serverHello = new ServerHelloFrame(ProtocolVersion, HostAlias, ArmoredPub);
        await SendRawAsync(ws, WireFrameSerializer.Serialize(serverHello), ct);

        // Register peer
        var sendLock = new SemaphoreSlim(1, 1);
        var peer     = new ConnectedPeer
        {
            Alias       = hello.Alias,
            Fingerprint = ExtractFingerprint(hello.PubKey),
            ArmoredPub  = hello.PubKey,
            WebSocket   = ws,
            SendLock    = sendLock,
        };

        lock (_lock) { room.Peers.Add(peer); }
        OnPeerConnected?.Invoke(hello.Alias, peer.Fingerprint);
        _logger.LogInformation("Peer '{Alias}' joined room '{Room}'.", hello.Alias, hello.Room);

        // Send room list (group only) and peer list
        await SendRoomListAsync(ct);
        await SendPeerListToRoomAsync(hello.Room, ct);

        // Receive loop for this peer
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
                        await OnMessage(msg.Payload, peer.Alias);
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

        var peerList = new PeerListFrame(
            peers.Select(p => new PeerInfo(p.Alias, p.Fingerprint)).ToList());
        string json = WireFrameSerializer.Serialize(peerList);

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
        // Only relevant for group rooms; 1:1 rooms are not announced
        if (groupRooms.Count == 0) return;

        var frame = new RoomListFrame(groupRooms);
        string json = WireFrameSerializer.Serialize(frame);

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

    /// <summary>
    /// Returns the first 40 characters of the pub key as a stub fingerprint.
    /// Real fingerprint extraction requires PgpManager; injecting it here would
    /// create a circular dependency — the UI layer should pass the pre-computed
    /// fingerprint instead.
    /// </summary>
    private static string ExtractFingerprint(string armoredPub)
    {
        // Strip armor header/footer, take first 40 chars of body as identifier.
        // The real fingerprint is computed by PgpManager and stored in the ViewModel.
        return armoredPub.Length >= 40 ? armoredPub[..40] : armoredPub;
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _cts?.Dispose();
    }
}
