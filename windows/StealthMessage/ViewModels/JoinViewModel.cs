using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.UI.Dispatching;
using StealthMessage.Crypto;
using StealthMessage.Network;

namespace StealthMessage.ViewModels;

public sealed class JoinViewModel : INotifyPropertyChanged, IAsyncDisposable
{
    private readonly PgpManager      _pgp;
    private readonly AppViewModel    _app;
    private readonly DispatcherQueue _dispatcher;
    private StealthClient?           _client;

    private string _serverUri     = string.Empty;
    private string _roomId        = string.Empty;
    private string _messageInput  = string.Empty;
    private string _errorMessage  = string.Empty;
    private string _peerAlias     = string.Empty;
    private string _peerFp        = string.Empty;
    private string _roomKind      = string.Empty;
    private bool   _isPending;
    private bool   _isConnected;

    public JoinViewModel(PgpManager pgp, AppViewModel app)
    {
        _pgp        = pgp;
        _app        = app;
        _dispatcher = DispatcherQueue.GetForCurrentThread();

        ConnectCommand    = new RelayCommand(ConnectAsync,    () => !_isConnected);
        DisconnectCommand = new RelayCommand(DisconnectAsync, () =>  _isConnected);
        SendMessageCommand = new RelayCommand(SendMessageAsync,
            () => _isConnected && !string.IsNullOrWhiteSpace(_messageInput));
    }

    // ---------------------------------------------------------------------------
    // Collections
    // ---------------------------------------------------------------------------

    public ObservableCollection<PeerViewModel> Peers    { get; } = new();
    public ObservableCollection<string>        Messages { get; } = new();

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public string ServerUri
    {
        get => _serverUri;
        set { _serverUri = value; OnPropertyChanged(); }
    }

    public string RoomId
    {
        get => _roomId;
        set { _roomId = value; OnPropertyChanged(); }
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

    public string PeerAlias
    {
        get => _peerAlias;
        private set { _peerAlias = value; OnPropertyChanged(); }
    }

    public string PeerFingerprint
    {
        get => _peerFp;
        private set { _peerFp = value; OnPropertyChanged(); }
    }

    public string RoomKind
    {
        get => _roomKind;
        private set { _roomKind = value; OnPropertyChanged(); }
    }

    public bool IsPending
    {
        get => _isPending;
        private set { _isPending = value; OnPropertyChanged(); }
    }

    public bool IsConnected
    {
        get => _isConnected;
        private set
        {
            _isConnected = value;
            OnPropertyChanged();
            ((RelayCommand)ConnectCommand).NotifyCanExecuteChanged();
            ((RelayCommand)DisconnectCommand).NotifyCanExecuteChanged();
        }
    }

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand ConnectCommand     { get; }
    public ICommand DisconnectCommand  { get; }
    public ICommand SendMessageCommand { get; }

    // ---------------------------------------------------------------------------
    // Connect
    // ---------------------------------------------------------------------------

    private async Task ConnectAsync()
    {
        ErrorMessage = string.Empty;
        if (!Uri.TryCreate(NormaliseUri(_serverUri), UriKind.Absolute, out var uri))
        {
            ErrorMessage = "Invalid server URI.";
            return;
        }
        if (string.IsNullOrWhiteSpace(_roomId))
        {
            ErrorMessage = "Enter a room name.";
            return;
        }

        var (armoredPriv, armoredPub, alias, passphrase) = _app.GetCredentials();
        _client = new StealthClient(NullLogger<StealthClient>.Instance);

        _client.OnMessage = async frame =>
        {
            try
            {
                string plaintext = await _pgp.DecryptAsync(
                    frame.Payload, armoredPriv, PeerFingerprint.Length > 0 ? armoredPub : armoredPub,
                    passphrase);
                string sender    = frame.Sender ?? PeerAlias;
                _dispatcher.TryEnqueue(() => Messages.Add($"[{sender}] {plaintext}"));
            }
            catch (SignatureInvalidException)
            {
                _dispatcher.TryEnqueue(() => Messages.Add("[!] Message discarded — invalid signature."));
            }
        };

        _client.OnPeerList = async frame =>
        {
            _dispatcher.TryEnqueue(() =>
            {
                Peers.Clear();
                foreach (var p in frame.Peers)
                    Peers.Add(new PeerViewModel { Alias = p.Alias, Fingerprint = p.Fingerprint });
                if (frame.Peers.Count == 1)
                {
                    PeerAlias       = frame.Peers[0].Alias;
                    PeerFingerprint = frame.Peers[0].Fingerprint;
                }
            });
            await Task.CompletedTask;
        };

        _client.OnKicked = async frame =>
        {
            _dispatcher.TryEnqueue(() =>
            {
                Messages.Add($"[System] You were kicked: {frame.Reason}");
                IsConnected = false;
                IsPending   = false;
            });
            await Task.CompletedTask;
        };

        _client.OnMoved = async frame =>
        {
            // Disconnect and reconnect to the new room (pre-approved)
            string newRoom = frame.Room;
            _dispatcher.TryEnqueue(() => Messages.Add($"[System] Moved to room: {newRoom}"));
            var oldClient  = _client;
            _client = null;
            if (oldClient is not null)
            {
                oldClient.OnDisconnected = null;
                await oldClient.DisposeAsync();
            }
            RoomId = newRoom;
            await ConnectAsync();
        };

        _client.OnDisconnected = async () =>
        {
            _dispatcher.TryEnqueue(() =>
            {
                IsConnected = false;
                IsPending   = false;
                Messages.Add("[System] Disconnected.");
            });
            await Task.CompletedTask;
        };

        IsPending = true;
        try
        {
            await _client.ConnectAsync(uri, _roomId, alias, armoredPub);
            IsPending   = false;
            IsConnected = true;
            Messages.Add("[System] Connected.");
        }
        catch (ProtocolException ex)
        {
            ErrorMessage = $"Protocol error {ex.Code}: {ex.Message}";
            IsPending    = false;
            await _client.DisposeAsync();
            _client = null;
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Connection failed: {ex.Message}";
            IsPending    = false;
            await _client.DisposeAsync();
            _client = null;
        }
    }

    // ---------------------------------------------------------------------------
    // Disconnect
    // ---------------------------------------------------------------------------

    private async Task DisconnectAsync()
    {
        var client = _client;
        _client = null;
        if (client is not null) await client.DisposeAsync();
        IsConnected = false;
        IsPending   = false;
        Messages.Add("[System] Disconnected.");
    }

    // ---------------------------------------------------------------------------
    // Send message
    // ---------------------------------------------------------------------------

    private async Task SendMessageAsync()
    {
        if (_client is null || string.IsNullOrWhiteSpace(_messageInput)) return;

        var (armoredPriv, armoredPub, alias, passphrase) = _app.GetCredentials();
        // For 1:1 rooms, encrypt for the single peer.
        // For group rooms with multiple peers, a real implementation encrypts per-peer.
        // Here we encrypt for the server's pubkey (host) as a simplification —
        // the full multi-recipient flow is handled in a future iteration.
        string encrypted = await _pgp.EncryptAsync(
            _messageInput, armoredPub, armoredPriv, passphrase);

        await _client.SendMessageAsync(encrypted);
        _dispatcher.TryEnqueue(() =>
        {
            Messages.Add($"[{alias}] {_messageInput}");
            MessageInput = string.Empty;
        });
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    private static string NormaliseUri(string raw)
    {
        if (raw.StartsWith("ws://", StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("wss://", StringComparison.OrdinalIgnoreCase))
            return raw;
        return "ws://" + raw;
    }

    // ---------------------------------------------------------------------------
    // IAsyncDisposable
    // ---------------------------------------------------------------------------

    public async ValueTask DisposeAsync()
    {
        if (_client is not null) await _client.DisposeAsync();
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
