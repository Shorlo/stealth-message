using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.UI.Dispatching;
using StealthMessage.Crypto;
using StealthMessage.Network;

namespace StealthMessage.ViewModels;

public sealed class PeerViewModel
{
    public string Alias       { get; init; } = string.Empty;
    public string Fingerprint { get; init; } = string.Empty;
}

public sealed class PendingPeerViewModel
{
    public string Alias       { get; init; } = string.Empty;
    public string Fingerprint { get; init; } = string.Empty;
    public string Room        { get; init; } = string.Empty;

    internal TaskCompletionSource<bool> Tcs { get; } = new();
}

public sealed class HostViewModel : INotifyPropertyChanged, IAsyncDisposable
{
    private readonly PgpManager      _pgp;
    private readonly AppViewModel    _app;
    private readonly StealthServer   _server;
    private readonly DispatcherQueue _dispatcher;

    // Single lock guards both dictionaries (always acquired together).
    private readonly object _peersLock = new();

    // alias → decoded armored pubkey
    private readonly Dictionary<string, string> _peerPubKeys = new(StringComparer.Ordinal);
    // alias → room name
    private readonly Dictionary<string, string> _peerRooms   = new(StringComparer.Ordinal);

    // Per-room collections — UI thread only
    private readonly Dictionary<string, ObservableCollection<PeerViewModel>> _roomPeers
        = new(StringComparer.Ordinal);
    private readonly Dictionary<string, ObservableCollection<string>> _roomMessages
        = new(StringComparer.Ordinal);

    private static readonly ObservableCollection<PeerViewModel> _emptyPeers    = new();
    private static readonly ObservableCollection<string>        _emptyMessages  = new();

    private string _port         = "8765";
    private string _newRoomName  = string.Empty;
    private string _newRoomKind  = "1to1";
    private string _messageInput = string.Empty;
    private string _errorMessage = string.Empty;
    private string _selectedRoom = string.Empty;
    private bool   _isRunning;

    public HostViewModel(PgpManager pgp, AppViewModel app)
    {
        _pgp        = pgp;
        _app        = app;
        _dispatcher = DispatcherQueue.GetForCurrentThread();
        _server     = new StealthServer(NullLogger<StealthServer>.Instance);

        _server.OnPeerConnected = (alias, _fp, armoredPub, room) =>
        {
            string fp = string.Empty;
            try { fp = _pgp.GetFingerprint(armoredPub); } catch { }
            lock (_peersLock)
            {
                _peerPubKeys[alias] = armoredPub;
                _peerRooms[alias]   = room;
            }
            _ = _dispatcher.TryEnqueue(() =>
            {
                if (_roomPeers.TryGetValue(room, out var peers))
                    peers.Add(new PeerViewModel { Alias = alias, Fingerprint = fp });
            });
        };

        _server.OnPeerDisconnected = (alias, room) =>
        {
            lock (_peersLock)
            {
                _peerPubKeys.Remove(alias);
                _peerRooms.Remove(alias);
            }
            _ = _dispatcher.TryEnqueue(() =>
            {
                if (_roomPeers.TryGetValue(room, out var peers))
                {
                    var p = peers.FirstOrDefault(x => x.Alias == alias);
                    if (p is not null) peers.Remove(p);
                }
            });
        };

        _server.OnMessage = async (payload, alias, peerArmoredPub, room) =>
        {
            var (armoredPriv, _, _, passphrase) = _app.GetCredentials();
            try
            {
                string plaintext = await _pgp.DecryptAsync(
                    payload, armoredPriv, peerArmoredPub, passphrase);
                string ts = Ts();
                _ = _dispatcher.TryEnqueue(() =>
                {
                    if (_roomMessages.TryGetValue(room, out var msgs))
                        msgs.Add($"[{ts}] [{alias}] {plaintext}");
                });
            }
            catch (SignatureInvalidException)
            {
                string ts = Ts();
                _ = _dispatcher.TryEnqueue(() =>
                {
                    if (_roomMessages.TryGetValue(room, out var msgs))
                        msgs.Add($"[{ts}] [!] Message from {alias} discarded — invalid signature.");
                });
            }
            catch (Exception ex)
            {
                string ts = Ts();
                _ = _dispatcher.TryEnqueue(() =>
                {
                    if (_roomMessages.TryGetValue(room, out var msgs))
                        msgs.Add($"[{ts}] [{alias}] <decryption failed: {ex.Message}>");
                });
            }
        };

        _server.OnJoinRequest = HandleJoinRequestAsync;

        StartServerCommand  = new RelayCommand(StartServerAsync,  () => !_isRunning);
        StopServerCommand   = new RelayCommand(StopServerAsync,   () =>  _isRunning);
        SendMessageCommand  = new RelayCommand(SendMessageAsync,
            () => _isRunning
               && !string.IsNullOrEmpty(_selectedRoom)
               && !string.IsNullOrWhiteSpace(_messageInput));
        AddRoomCommand      = new SyncRelayCommand(AddRoom);
        ApproveCommand      = new RelayCommand<PendingPeerViewModel>(ApproveAsync);
        DenyCommand         = new RelayCommand<PendingPeerViewModel>(DenyAsync);
        KickCommand         = new RelayCommand<PeerViewModel>(KickAsync);
        MoveCommand         = new RelayCommand<(PeerViewModel peer, string room)>(MoveAsync);
    }

    // ---------------------------------------------------------------------------
    // Collections
    // ---------------------------------------------------------------------------

    /// <summary>Messages for the currently selected room.</summary>
    public ObservableCollection<string> Messages
        => _roomMessages.TryGetValue(_selectedRoom, out var m) ? m : _emptyMessages;

    /// <summary>Peers connected to the currently selected room.</summary>
    public ObservableCollection<PeerViewModel> ConnectedPeers
        => _roomPeers.TryGetValue(_selectedRoom, out var p) ? p : _emptyPeers;

    public ObservableCollection<PendingPeerViewModel> PendingPeers { get; } = new();
    public ObservableCollection<string>               Rooms        { get; } = new();

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public string SelectedRoom
    {
        get => _selectedRoom;
        set
        {
            if (_selectedRoom == value) return;
            _selectedRoom = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(Messages));
            OnPropertyChanged(nameof(ConnectedPeers));
            ((RelayCommand)SendMessageCommand).NotifyCanExecuteChanged();
        }
    }

    public string Port
    {
        get => _port;
        set { _port = value; OnPropertyChanged(); }
    }

    public string NewRoomName
    {
        get => _newRoomName;
        set { _newRoomName = value; OnPropertyChanged(); }
    }

    public string NewRoomKind
    {
        get => _newRoomKind;
        set { _newRoomKind = value; OnPropertyChanged(); }
    }

    public string MessageInput
    {
        get => _messageInput;
        set
        {
            _messageInput = value; OnPropertyChanged();
            ((RelayCommand)SendMessageCommand).NotifyCanExecuteChanged();
        }
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set { _errorMessage = value; OnPropertyChanged(); }
    }

    public bool IsRunning
    {
        get => _isRunning;
        private set
        {
            _isRunning = value;
            OnPropertyChanged();
            ((RelayCommand)StartServerCommand).NotifyCanExecuteChanged();
            ((RelayCommand)StopServerCommand).NotifyCanExecuteChanged();
        }
    }

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand StartServerCommand { get; }
    public ICommand StopServerCommand  { get; }
    public ICommand SendMessageCommand { get; }
    public ICommand AddRoomCommand     { get; }
    public ICommand ApproveCommand     { get; }
    public ICommand DenyCommand        { get; }
    public ICommand KickCommand        { get; }
    public ICommand MoveCommand        { get; }

    // ---------------------------------------------------------------------------
    // Start / Stop
    // ---------------------------------------------------------------------------

    private Task StartServerAsync()
    {
        ErrorMessage = string.Empty;
        if (!int.TryParse(_port, out int port) || port < 1024 || port > 65535)
        {
            ErrorMessage = "Invalid port number.";
            return Task.CompletedTask;
        }

        var (_, armoredPub, alias, _) = _app.GetCredentials();
        string fingerprint = _pgp.GetFingerprint(armoredPub);

        // Ensure per-room collections exist for all already-added rooms
        foreach (var room in Rooms)
            EnsureRoomCollections(room);

        // Auto-select first room when none is selected
        if (string.IsNullOrEmpty(_selectedRoom) && Rooms.Count > 0)
            SelectedRoom = Rooms[0];

        var initialRooms = Rooms.Select(r => (r, _newRoomKind)).ToList();
        _server.Start(port, alias, armoredPub, fingerprint, initialRooms);
        IsRunning = true;
        AddSystemMessage($"[System] Server started on port {port}.");
        return Task.CompletedTask;
    }

    private async Task StopServerAsync()
    {
        await _server.StopAsync();
        IsRunning = false;
        lock (_peersLock)
        {
            _peerPubKeys.Clear();
            _peerRooms.Clear();
        }
        foreach (var peers in _roomPeers.Values) peers.Clear();
        AddSystemMessage("[System] Server stopped.");
    }

    // ---------------------------------------------------------------------------
    // Message send — encrypt individually for each peer in the selected room
    // ---------------------------------------------------------------------------

    private async Task SendMessageAsync()
    {
        if (string.IsNullOrWhiteSpace(_messageInput)) return;
        if (string.IsNullOrEmpty(_selectedRoom)) return;

        var (armoredPriv, _, alias, passphrase) = _app.GetCredentials();
        string text = _messageInput;
        string room = _selectedRoom;

        // Collect peers in the selected room only
        List<(string peerAlias, string armoredPub)> peers;
        lock (_peersLock)
        {
            peers = _peerPubKeys
                .Where(kv => _peerRooms.TryGetValue(kv.Key, out var r) && r == room)
                .Select(kv => (kv.Key, kv.Value))
                .ToList();
        }

        if (peers.Count == 0)
        {
            string ts0 = Ts();
            _ = _dispatcher.TryEnqueue(() =>
            {
                if (_roomMessages.TryGetValue(room, out var log))
                    log.Add($"[{ts0}] [System] No peers in this room.");
                MessageInput = string.Empty;
            });
            return;
        }

        foreach (var (peerAlias, peerPub) in peers)
        {
            try
            {
                string payload = await _pgp.EncryptAsync(text, peerPub, armoredPriv, passphrase);
                await _server.SendToAsync(peerAlias, new MessageFrame(
                    Id:        Guid.NewGuid().ToString(),
                    Payload:   payload,
                    Timestamp: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
            }
            catch (Exception ex)
            {
                string ts = Ts();
                _ = _dispatcher.TryEnqueue(() =>
                {
                    if (_roomMessages.TryGetValue(room, out var log))
                        log.Add($"[{ts}] [!] Failed to send to {peerAlias}: {ex.Message}");
                });
            }
        }

        string tsSent = Ts();
        _ = _dispatcher.TryEnqueue(() =>
        {
            if (_roomMessages.TryGetValue(room, out var log))
                log.Add($"[{tsSent}] [{alias}] {text}");
            MessageInput = string.Empty;
        });
    }

    // ---------------------------------------------------------------------------
    // Room management
    // ---------------------------------------------------------------------------

    private void AddRoom()
    {
        if (string.IsNullOrWhiteSpace(_newRoomName)) return;
        string name = _newRoomName.Trim();
        if (!Rooms.Contains(name))
        {
            EnsureRoomCollections(name);
            Rooms.Add(name);
            if (_isRunning) _server.AddRoom(name, _newRoomKind);
            // Auto-select if this is the first room
            if (string.IsNullOrEmpty(_selectedRoom)) SelectedRoom = name;
        }
        NewRoomName = string.Empty;
    }

    private void EnsureRoomCollections(string room)
    {
        if (!_roomMessages.ContainsKey(room))
            _roomMessages[room] = new ObservableCollection<string>();
        if (!_roomPeers.ContainsKey(room))
            _roomPeers[room] = new ObservableCollection<PeerViewModel>();
    }

    private static string Ts() => DateTimeOffset.Now.ToString("HH:mm");

    /// <summary>Adds a system message to the currently selected room (or first available).</summary>
    private void AddSystemMessage(string msg)
    {
        string entry = $"[{Ts()}] {msg}";
        ObservableCollection<string>? target = null;
        if (!string.IsNullOrEmpty(_selectedRoom))
            _roomMessages.TryGetValue(_selectedRoom, out target);
        if (target is null && _roomMessages.Count > 0)
            target = _roomMessages.Values.First();
        target?.Add(entry);
    }

    // ---------------------------------------------------------------------------
    // Peer management
    // ---------------------------------------------------------------------------

    private async Task<bool> HandleJoinRequestAsync(string alias, string fingerprint, string room)
    {
        var tcs     = new TaskCompletionSource<bool>();
        var pending = new PendingPeerViewModel
        {
            Alias       = alias,
            Fingerprint = fingerprint,
            Room        = room,
        };

        _pendingTasks[alias] = tcs;
        _ = _dispatcher.TryEnqueue(() => PendingPeers.Add(pending));

        return await tcs.Task;
    }

    private readonly Dictionary<string, TaskCompletionSource<bool>> _pendingTasks = new();

    private Task ApproveAsync(PendingPeerViewModel? pending)
    {
        if (pending is null) return Task.CompletedTask;
        if (_pendingTasks.Remove(pending.Alias, out var tcs)) tcs.TrySetResult(true);
        _ = _dispatcher.TryEnqueue(() => PendingPeers.Remove(pending));
        return Task.CompletedTask;
    }

    private Task DenyAsync(PendingPeerViewModel? pending)
    {
        if (pending is null) return Task.CompletedTask;
        if (_pendingTasks.Remove(pending.Alias, out var tcs)) tcs.TrySetResult(false);
        _ = _dispatcher.TryEnqueue(() => PendingPeers.Remove(pending));
        return Task.CompletedTask;
    }

    private async Task KickAsync(PeerViewModel? peer)
    {
        if (peer is null) return;
        await _server.KickAsync(peer.Alias, "Kicked by host.");
    }

    private async Task MoveAsync((PeerViewModel peer, string room) args)
    {
        await _server.MoveAsync(args.peer.Alias, args.room);
    }

    // ---------------------------------------------------------------------------
    // IAsyncDisposable
    // ---------------------------------------------------------------------------

    public async ValueTask DisposeAsync() => await _server.DisposeAsync();

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}

/// <summary>Generic RelayCommand with a typed parameter.</summary>
internal sealed class RelayCommand<T> : ICommand
{
    private readonly Func<T?, Task> _execute;
    public RelayCommand(Func<T?, Task> execute) => _execute = execute;
    public event EventHandler? CanExecuteChanged;
    public bool CanExecute(object? parameter) => true;
    public async void Execute(object? parameter) => await _execute(parameter is T t ? t : default);
    public void NotifyCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
