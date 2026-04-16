using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Extensions.Logging;
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

    // Completion source resolved when host approves or denies
    internal TaskCompletionSource<bool> Tcs { get; } = new();
}

public sealed class HostViewModel : INotifyPropertyChanged, IAsyncDisposable
{
    private readonly PgpManager      _pgp;
    private readonly AppViewModel    _app;
    private readonly StealthServer   _server;
    private readonly DispatcherQueue _dispatcher;

    private string _port         = "8765";
    private string _newRoomName  = string.Empty;
    private string _newRoomKind  = "1to1";
    private string _messageInput = string.Empty;
    private string _errorMessage = string.Empty;
    private bool   _isRunning;

    // alias → raw ASCII-armored public key (populated in OnPeerConnected)
    private readonly Dictionary<string, string> _peerPubKeys = new(StringComparer.Ordinal);

    public HostViewModel(PgpManager pgp, AppViewModel app)
    {
        _pgp        = pgp;
        _app        = app;
        _dispatcher = DispatcherQueue.GetForCurrentThread();
        _server     = new StealthServer(NullLogger<StealthServer>.Instance);

        _server.OnPeerConnected    = (alias, fp, armoredPub) =>
        {
            _peerPubKeys[alias] = armoredPub;
            _ = _dispatcher.TryEnqueue(() =>
                ConnectedPeers.Add(new PeerViewModel { Alias = alias, Fingerprint = fp }));
        };
        _server.OnPeerDisconnected = alias =>
        {
            _peerPubKeys.Remove(alias);
            _ = _dispatcher.TryEnqueue(() =>
            {
                var p = ConnectedPeers.FirstOrDefault(x => x.Alias == alias);
                if (p is not null) ConnectedPeers.Remove(p);
            });
        };
        _server.OnMessage = async (payload, alias, peerArmoredPub) =>
        {
            var (armoredPriv, _, _, passphrase) = _app.GetCredentials();
            try
            {
                string plaintext = await _pgp.DecryptAsync(payload, armoredPriv, peerArmoredPub, passphrase);
                _dispatcher.TryEnqueue(() => Messages.Add($"[{alias}] {plaintext}"));
            }
            catch (SignatureInvalidException)
            {
                _dispatcher.TryEnqueue(() => Messages.Add($"[!] Message from {alias} had invalid signature — discarded."));
            }
            catch (Exception ex)
            {
                _dispatcher.TryEnqueue(() => Messages.Add($"[{alias}]: <decryption failed: {ex.Message}>"));
            }
        };
        _server.OnJoinRequest      = HandleJoinRequestAsync;

        StartServerCommand  = new RelayCommand(StartServerAsync,  () => !_isRunning);
        StopServerCommand   = new RelayCommand(StopServerAsync,   () =>  _isRunning);
        SendMessageCommand  = new RelayCommand(SendMessageAsync,  () =>  _isRunning && !string.IsNullOrWhiteSpace(_messageInput));
        AddRoomCommand      = new SyncRelayCommand(AddRoom);
        ApproveCommand      = new RelayCommand<PendingPeerViewModel>(ApproveAsync);
        DenyCommand         = new RelayCommand<PendingPeerViewModel>(DenyAsync);
        KickCommand         = new RelayCommand<PeerViewModel>(KickAsync);
        MoveCommand         = new RelayCommand<(PeerViewModel peer, string room)>(MoveAsync);
    }

    // ---------------------------------------------------------------------------
    // Collections
    // ---------------------------------------------------------------------------

    public ObservableCollection<PeerViewModel>        ConnectedPeers { get; } = new();
    public ObservableCollection<PendingPeerViewModel> PendingPeers   { get; } = new();
    public ObservableCollection<string>               Messages       { get; } = new();
    public ObservableCollection<string>               Rooms          { get; } = new();

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

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
        set { _messageInput = value; OnPropertyChanged();
              ((RelayCommand)SendMessageCommand).NotifyCanExecuteChanged(); }
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

        var initialRooms = Rooms.Select(r => (r, "1to1")).ToList();
        _server.Start(port, alias, armoredPub, fingerprint, initialRooms);
        IsRunning = true;
        Messages.Add($"[System] Server started on port {port}.");
        return Task.CompletedTask;
    }

    private async Task StopServerAsync()
    {
        await _server.StopAsync();
        IsRunning = false;
        Messages.Add("[System] Server stopped.");
    }

    // ---------------------------------------------------------------------------
    // Message send
    // ---------------------------------------------------------------------------

    private async Task SendMessageAsync()
    {
        if (string.IsNullOrWhiteSpace(_messageInput)) return;
        var (armoredPriv, _, alias, passphrase) = _app.GetCredentials();
        string text = _messageInput;

        // Encrypt individually for each connected peer and send via server
        foreach (var peer in ConnectedPeers.ToList())
        {
            if (!_peerPubKeys.TryGetValue(peer.Alias, out string? peerPub)) continue;
            try
            {
                string encrypted = await _pgp.EncryptAsync(text, peerPub, armoredPriv, passphrase);
                var frame = new MessageFrame(
                    Id:        Guid.NewGuid().ToString(),
                    Payload:   encrypted,
                    Timestamp: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                await _server.SendToAsync(peer.Alias, frame);
            }
            catch (Exception ex)
            {
                _dispatcher.TryEnqueue(() =>
                    Messages.Add($"[!] Failed to send to {peer.Alias}: {ex.Message}"));
            }
        }

        _dispatcher.TryEnqueue(() =>
        {
            Messages.Add($"[{alias}] {text}");
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
            Rooms.Add(name);
            if (_isRunning) _server.AddRoom(name, _newRoomKind);
        }
        NewRoomName = string.Empty;
    }

    // ---------------------------------------------------------------------------
    // Peer management
    // ---------------------------------------------------------------------------

    private async Task<bool> HandleJoinRequestAsync(string alias, string fingerprint)
    {
        var tcs     = new TaskCompletionSource<bool>();
        var pending = new PendingPeerViewModel { Alias = alias, Fingerprint = fingerprint };

        // Forward TCS so Approve/Deny commands can resolve it
        _pendingTasks[alias] = tcs;
        _dispatcher.TryEnqueue(() => PendingPeers.Add(pending));

        return await tcs.Task;
    }

    private readonly Dictionary<string, TaskCompletionSource<bool>> _pendingTasks = new();

    private Task ApproveAsync(PendingPeerViewModel? pending)
    {
        if (pending is null) return Task.CompletedTask;
        if (_pendingTasks.Remove(pending.Alias, out var tcs)) tcs.TrySetResult(true);
        _dispatcher.TryEnqueue(() => PendingPeers.Remove(pending));
        return Task.CompletedTask;
    }

    private Task DenyAsync(PendingPeerViewModel? pending)
    {
        if (pending is null) return Task.CompletedTask;
        if (_pendingTasks.Remove(pending.Alias, out var tcs)) tcs.TrySetResult(false);
        _dispatcher.TryEnqueue(() => PendingPeers.Remove(pending));
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
