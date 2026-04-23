using System.Net.WebSockets;
using System.Text;
using Microsoft.Extensions.Logging;

namespace StealthMessage.Network;

/// <summary>
/// WebSocket client that implements the stealth-message handshake, receive loop,
/// ping/pong keep-alive, and clean disconnect.
/// Thread-safe for concurrent callers: all sends are guarded by <c>_sendLock</c>.
/// </summary>
public sealed class StealthClient : IAsyncDisposable
{
    // Timeouts (protocol.md)
    private static readonly TimeSpan HandshakeTimeout  = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan PendingTimeout    = TimeSpan.FromSeconds(65);
    private static readonly TimeSpan PingInterval      = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan PongTimeout       = TimeSpan.FromSeconds(10);

    private readonly ILogger<StealthClient> _logger;
    private readonly ClientWebSocket        _ws       = new();
    private readonly SemaphoreSlim          _sendLock = new(1, 1);
    private CancellationTokenSource?        _cts;
    private Task?                           _receiveTask;
    private Task?                           _pingTask;
    // Frame received during handshake peek (e.g. peer-list for 1:1 rooms); dispatched first in receive loop
    private WireFrame?                      _bufferedFrame;

    // Peer identity — populated after handshake
    public string? PeerAlias         { get; private set; }
    public string? PeerArmoredPubkey { get; private set; }
    public string? PeerFingerprint   { get; private set; }

    // ---------------------------------------------------------------------------
    // Public callbacks
    // ---------------------------------------------------------------------------
    public Func<MessageFrame, Task>? OnMessage      { get; set; }
    public Func<PeerListFrame, Task>? OnPeerList    { get; set; }
    public Func<RoomListFrame, Task>? OnRoomList    { get; set; }
    public Func<KickFrame, Task>?     OnKicked      { get; set; }
    public Func<MoveFrame, Task>?     OnMoved       { get; set; }
    public Func<Task>?                OnDisconnected { get; set; }

    public StealthClient(ILogger<StealthClient> logger)
    {
        _logger = logger;
    }

    // ---------------------------------------------------------------------------
    // Connect + Handshake
    // ---------------------------------------------------------------------------

    /// <summary>
    /// Opens the WebSocket, performs the hello handshake, and waits for approval
    /// if the server sends a pending frame (group rooms).
    /// Starts the receive loop and ping loop on success.
    /// </summary>
    public async Task ConnectAsync(
        Uri    serverUri,
        string roomId,
        string alias,
        string armoredPub,
        CancellationToken cancellationToken = default)
    {
        await _ws.ConnectAsync(serverUri, cancellationToken);
        _logger.LogInformation("WebSocket connected to {Uri}.", serverUri);

        // pubkey must be base64url(armored_bytes) per protocol §2
        string encodedPub = Base64UrlEncode(Encoding.UTF8.GetBytes(armoredPub));
        var hello = new HelloFrame("1", roomId, alias, encodedPub);
        await SendRawAsync(WireFrameSerializer.Serialize(hello), cancellationToken);

        // Server always sends server-hello first (before any pending frame)
        using var handshakeCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        handshakeCts.CancelAfter(HandshakeTimeout);
        var response = await ReceiveFrameAsync(handshakeCts.Token);

        if (response is ErrorFrame earlyErr)
            throw new ProtocolException(earlyErr.Code, earlyErr.Reason);

        if (response is not ServerHelloFrame serverHello)
            throw new ProtocolException(ProtocolException.Malformed,
                $"Expected server-hello, got {response.GetType().Name}");

        try
        {
            PeerAlias         = serverHello.Alias;
            PeerArmoredPubkey = Encoding.UTF8.GetString(Base64UrlDecode(serverHello.PubKey));
        }
        catch (Exception ex)
        {
            throw new ProtocolException(ProtocolException.Malformed,
                $"Invalid pubkey encoding in server hello: {ex.Message}");
        }

        // Peek for optional pending frame (group rooms, not pre-approved).
        // 600 ms window — if nothing arrives the room is 1:1 or peer is pre-approved.
        // Any non-pending frame (e.g. peer-list for 1:1) is buffered for the receive loop.
        using (var peekCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken))
        {
            peekCts.CancelAfter(TimeSpan.FromMilliseconds(600));
            try
            {
                var peek = await ReceiveFrameAsync(peekCts.Token);
                if (peek is PendingFrame)
                {
                    _logger.LogInformation("Join pending — waiting for host approval.");
                    using var pendingCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    pendingCts.CancelAfter(PendingTimeout);
                    var approval = await ReceiveFrameAsync(pendingCts.Token);
                    switch (approval)
                    {
                        case ApprovedFrame:
                            _logger.LogInformation("Host approved.");
                            break;
                        case ErrorFrame err:
                            throw new ProtocolException(err.Code, err.Reason);
                        default:
                            throw new ProtocolException(ProtocolException.Malformed,
                                $"Unexpected frame while pending: {approval.GetType().Name}");
                    }
                }
                else
                {
                    // Non-pending frame arrived (e.g. peer-list for 1:1 room) — buffer for dispatch
                    _bufferedFrame = peek;
                }
            }
            catch (OperationCanceledException)
            {
                // Timeout — no extra frame, direct join
            }
        }

        _logger.LogInformation("Handshake complete. Peer: {Alias}.", PeerAlias);

        _cts         = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _receiveTask = Task.Run(() => ReceiveLoopAsync(_cts.Token));
        _pingTask    = Task.Run(() => PingLoopAsync(_cts.Token));
    }

    // ---------------------------------------------------------------------------
    // Send message
    // ---------------------------------------------------------------------------

    public async Task SendMessageAsync(string encryptedPayload, CancellationToken ct = default)
    {
        var frame = new MessageFrame(
            Id:        Guid.NewGuid().ToString(),
            Payload:   encryptedPayload,
            Timestamp: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        await SendRawAsync(WireFrameSerializer.Serialize(frame), ct);
    }

    // ---------------------------------------------------------------------------
    // Disconnect
    // ---------------------------------------------------------------------------

    public async Task DisconnectAsync()
    {
        OnDisconnected = null; // suppress callback on intentional close
        try
        {
            if (_ws.State == WebSocketState.Open)
                await SendRawAsync(WireFrameSerializer.Serialize(new ByeFrame()), CancellationToken.None);
        }
        catch { /* best effort */ }

        _cts?.Cancel();
        if (_receiveTask is not null) try { await _receiveTask; } catch { }
        if (_pingTask    is not null) try { await _pingTask;    } catch { }

        if (_ws.State is WebSocketState.Open or WebSocketState.CloseReceived)
        {
            try { await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", CancellationToken.None); }
            catch { }
        }
    }

    // ---------------------------------------------------------------------------
    // Room discovery — no auth required
    // ---------------------------------------------------------------------------

    public static async Task<IReadOnlyList<RoomInfo>> QueryRoomsAsync(
        Uri serverUri,
        ILogger<StealthClient> logger,
        CancellationToken ct = default)
    {
        using var ws = new ClientWebSocket();
        await ws.ConnectAsync(serverUri, ct);

        await SendRawOnceAsync(ws, WireFrameSerializer.Serialize(new ListRoomsFrame()), ct);

        string json = await ReceiveOneFrameAsync(ws, ct);
        var frame   = WireFrameSerializer.Parse(json);

        // Server closes after roomsinfo — attempt graceful close, ignore errors
        try { await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "done", CancellationToken.None); }
        catch { }

        return frame is RoomsInfoFrame ri
            ? ri.Rooms
            : throw new ProtocolException(ProtocolException.Malformed,
                  $"Expected roomsinfo, got {frame.GetType().Name}");
    }

    // ---------------------------------------------------------------------------
    // IAsyncDisposable
    // ---------------------------------------------------------------------------

    public async ValueTask DisposeAsync()
    {
        await DisconnectAsync();
        _ws.Dispose();
        _cts?.Dispose();
        _sendLock.Dispose();
    }

    // ---------------------------------------------------------------------------
    // Loops
    // ---------------------------------------------------------------------------

    private async Task ReceiveLoopAsync(CancellationToken ct)
    {
        try
        {
            // Dispatch any frame that arrived during the handshake peek
            if (_bufferedFrame is not null)
            {
                await DispatchAsync(_bufferedFrame, ct);
                _bufferedFrame = null;
            }

            while (!ct.IsCancellationRequested)
            {
                string json;
                try { json = await ReceiveOneFrameAsync(_ws, ct); }
                catch (OperationCanceledException) { break; }
                catch (WebSocketException)         { break; }

                WireFrame frame;
                try { frame = WireFrameSerializer.Parse(json); }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Malformed frame ignored.");
                    continue;
                }

                await DispatchAsync(frame, ct);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _logger.LogError(ex, "Receive loop terminated unexpectedly.");
        }
        finally
        {
            var cb = OnDisconnected;
            if (cb is not null)
                try { await cb(); } catch { }
        }
    }

    private async Task PingLoopAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(PingInterval, ct);
                await SendRawAsync(WireFrameSerializer.Serialize(new PingFrame()), ct);
                _logger.LogDebug("Ping sent.");
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { _logger.LogWarning(ex, "Ping loop ended."); }
    }

    private async Task DispatchAsync(WireFrame frame, CancellationToken ct)
    {
        switch (frame)
        {
            case MessageFrame f  when OnMessage  is not null: await OnMessage(f);  break;
            case PeerListFrame f when OnPeerList is not null: await OnPeerList(f); break;
            case RoomListFrame f when OnRoomList is not null: await OnRoomList(f); break;
            case KickFrame f     when OnKicked   is not null: await OnKicked(f);   break;
            case MoveFrame f     when OnMoved    is not null: await OnMoved(f);    break;
            case PongFrame:
                _logger.LogDebug("Pong received.");
                break;
            case ByeFrame:
                _logger.LogInformation("Server sent bye — closing.");
                _cts?.Cancel();
                break;
            default:
                _logger.LogDebug("Unhandled frame: {Type}.", frame.GetType().Name);
                break;
        }
    }

    // ---------------------------------------------------------------------------
    // Low-level send / receive helpers
    // ---------------------------------------------------------------------------

    private async Task SendRawAsync(string json, CancellationToken ct)
    {
        await _sendLock.WaitAsync(ct);
        try
        {
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            await _ws.SendAsync(bytes, WebSocketMessageType.Text, endOfMessage: true, ct);
        }
        finally { _sendLock.Release(); }
    }

    private async Task<WireFrame> ReceiveFrameAsync(CancellationToken ct)
    {
        string json = await ReceiveOneFrameAsync(_ws, ct);
        return WireFrameSerializer.Parse(json);
    }

    private static async Task SendRawOnceAsync(ClientWebSocket ws, string json, CancellationToken ct)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        await ws.SendAsync(bytes, WebSocketMessageType.Text, endOfMessage: true, ct);
    }

    private static async Task<string> ReceiveOneFrameAsync(ClientWebSocket ws, CancellationToken ct)
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
}
