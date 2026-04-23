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

        ConnectCommand      = new RelayCommand(ConnectAsync,    () => !_isConnected);
        DisconnectCommand   = new RelayCommand(DisconnectAsync, () =>  _isConnected);
        SendMessageCommand  = new RelayCommand(SendMessageAsync,
            () => _isConnected && !string.IsNullOrWhiteSpace(_messageInput));
        SwitchRoomCommand   = new RelayCommand<string>(SwitchRoomAsync);
        RefreshRoomsCommand = new RelayCommand(RefreshRoomsAsync, () => _isConnected);
    }

    // ---------------------------------------------------------------------------
    // Collections
    // ---------------------------------------------------------------------------

    public ObservableCollection<PeerViewModel> Peers          { get; } = new();
    public ObservableCollection<string>        Messages       { get; } = new();
    /// <summary>All rooms on the server except the one currently joined.</summary>
    public ObservableCollection<string>        AvailableRooms { get; } = new();

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
            ((RelayCommand)RefreshRoomsCommand).NotifyCanExecuteChanged();
        }
    }

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand ConnectCommand      { get; }
    public ICommand DisconnectCommand   { get; }
    public ICommand SendMessageCommand  { get; }
    public ICommand SwitchRoomCommand   { get; }
    public ICommand RefreshRoomsCommand { get; }

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

        // Fresh log for every new room — don't bleed messages across sessions
        Messages.Clear();
        AvailableRooms.Clear();
        Peers.Clear();
        PeerFingerprint = string.Empty;

        var (armoredPriv, armoredPub, alias, passphrase) = _app.GetCredentials();
        _client = new StealthClient(NullLogger<StealthClient>.Instance);

        IsPending = true;
        try
        {
            await _client.ConnectAsync(uri, _roomId, alias, armoredPub);

            // PeerArmoredPubkey and PeerAlias are populated after the handshake completes
            string? peerPub   = _client.PeerArmoredPubkey;
            string  hostAlias = _client.PeerAlias ?? "Host";
            if (!string.IsNullOrEmpty(hostAlias)) PeerAlias = hostAlias;
            // For 1:1 rooms the server never sends a peerlist, so compute the fingerprint
            // directly from the host pubkey received in server-hello.
            if (!string.IsNullOrEmpty(peerPub))
                try { PeerFingerprint = _pgp.GetFingerprint(peerPub); } catch { }

            // Set up callbacks — receive loop is running but we haven't missed anything yet
            _client.OnMessage = async frame =>
            {
                try
                {
                    string senderPub = peerPub ?? armoredPub;
                    string plaintext = await _pgp.DecryptAsync(frame.Payload, armoredPriv, senderPub, passphrase);
                    string sender    = frame.Sender ?? PeerAlias;
                    string ts        = Ts();
                    _dispatcher.TryEnqueue(() => Messages.Add($"[{ts}] [{sender}] {plaintext}"));
                }
                catch (SignatureInvalidException)
                {
                    string ts = Ts();
                    _dispatcher.TryEnqueue(() => Messages.Add($"[{ts}] [!] Message discarded — invalid signature."));
                }
                catch (Exception ex)
                {
                    string ts = Ts();
                    _dispatcher.TryEnqueue(() => Messages.Add($"[{ts}] [!] Decryption failed: {ex.Message}"));
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

            // The server sends roomlist immediately after join — use it to seed AvailableRooms
            // with group rooms.  A full QueryRoomsAsync (started below) adds 1:1 rooms too.
            _client.OnRoomList = frame =>
            {
                _dispatcher.TryEnqueue(() =>
                {
                    foreach (var room in frame.Groups)
                    {
                        if (room != _roomId && !AvailableRooms.Contains(room))
                            AvailableRooms.Add(room);
                    }
                });
                return Task.CompletedTask;
            };

            _client.OnKicked = async frame =>
            {
                string ts = Ts();
                _dispatcher.TryEnqueue(() =>
                {
                    Messages.Add($"[{ts}] [System] You were kicked: {frame.Reason}");
                    IsConnected = false;
                    IsPending   = false;
                    AvailableRooms.Clear();
                });
                await Task.CompletedTask;
            };

            _client.OnMoved = frame =>
            {
                string newRoom = frame.Room;
                var oldClient = _client;
                _client = null;
                if (oldClient is not null)
                {
                    oldClient.OnDisconnected = null;
                    _ = oldClient.DisposeAsync().AsTask();
                }
                _ = _dispatcher.TryEnqueue(async () =>
                {
                    RoomId = newRoom;
                    await ConnectAsync();
                });
                return Task.CompletedTask;
            };

            _client.OnDisconnected = async () =>
            {
                string ts = Ts();
                _dispatcher.TryEnqueue(() =>
                {
                    IsConnected = false;
                    IsPending   = false;
                    AvailableRooms.Clear();
                    Messages.Add($"[{ts}] [System] Disconnected.");
                });
                await Task.CompletedTask;
            };

            IsPending   = false;
            IsConnected = true;
            Messages.Add($"[{Ts()}] [System] Connected to {_roomId}. Host: {hostAlias}");

            // Query ALL rooms (1:1 + group) in the background so the Switch room
            // panel shows every room the user can move to, not just group rooms.
            _ = Task.Run(RefreshRoomsAsync);
        }
        catch (ProtocolException ex)
        {
            ErrorMessage = $"Protocol error {ex.Code}: {ex.Message}";
            IsPending    = false;
            var c1 = _client; _client = null;
            if (c1 is not null) await c1.DisposeAsync();
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Connection failed: {ex.Message}";
            IsPending    = false;
            var c2 = _client; _client = null;
            if (c2 is not null) await c2.DisposeAsync();
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
        AvailableRooms.Clear();
        Messages.Add($"[{Ts()}] [System] Disconnected.");
    }

    // ---------------------------------------------------------------------------
    // Switch room (reconnect to a different room on the same server)
    // ---------------------------------------------------------------------------

    private async Task SwitchRoomAsync(string? newRoom)
    {
        if (string.IsNullOrWhiteSpace(newRoom)) return;
        var client = _client;
        _client = null;
        if (client is not null)
        {
            client.OnDisconnected = null;
            await client.DisposeAsync();
        }
        IsConnected = false;
        IsPending   = false;
        RoomId      = newRoom;
        await ConnectAsync();
    }

    // ---------------------------------------------------------------------------
    // Refresh room list (queries server for all available rooms)
    // ---------------------------------------------------------------------------

    private async Task RefreshRoomsAsync()
    {
        if (!Uri.TryCreate(NormaliseUri(_serverUri), UriKind.Absolute, out var uri)) return;
        try
        {
            var rooms = await StealthClient.QueryRoomsAsync(uri, NullLogger<StealthClient>.Instance);
            string current = _roomId;
            _dispatcher.TryEnqueue(() =>
            {
                AvailableRooms.Clear();
                foreach (var r in rooms)
                {
                    if (r.Id != current)
                        AvailableRooms.Add(r.Id);
                }
            });
        }
        catch { /* non-fatal — panel stays with whatever was known */ }
    }

    // ---------------------------------------------------------------------------
    // Send message
    // ---------------------------------------------------------------------------

    private async Task SendMessageAsync()
    {
        if (_client is null || string.IsNullOrWhiteSpace(_messageInput)) return;

        var (armoredPriv, _, alias, passphrase) = _app.GetCredentials();

        string? recipientPub = _client.PeerArmoredPubkey;
        if (recipientPub is null)
        {
            ErrorMessage = "No host public key — cannot encrypt. Reconnect and try again.";
            return;
        }

        string text = _messageInput;
        try
        {
            string encrypted = await _pgp.EncryptAsync(text, recipientPub, armoredPriv, passphrase);
            await _client.SendMessageAsync(encrypted);
            string ts = Ts();
            _dispatcher.TryEnqueue(() =>
            {
                Messages.Add($"[{ts}] [{alias}] {text}");
                MessageInput = string.Empty;
            });
        }
        catch (Exception ex)
        {
            _dispatcher.TryEnqueue(() => ErrorMessage = $"Send failed: {ex.Message}");
        }
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    private static string Ts() => DateTimeOffset.Now.ToString("HH:mm");

    private static string NormaliseUri(string raw)
    {
        raw = raw.Trim();

        if (raw.StartsWith("ws://",  StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("wss://", StringComparison.OrdinalIgnoreCase))
            return raw;

        // Accept "host/port" shorthand (e.g. "192.168.1.30/8765")
        if (!raw.Contains(':'))
        {
            int slash = raw.IndexOf('/');
            if (slash > 0 && int.TryParse(raw.AsSpan(slash + 1), out _))
                raw = raw[..slash] + ':' + raw[(slash + 1)..];
        }

        return "ws://" + raw;
    }

    // ---------------------------------------------------------------------------
    // IAsyncDisposable
    // ---------------------------------------------------------------------------

    public void ReturnToHub() => _app.ReturnToHub();

    public async ValueTask DisposeAsync()
    {
        if (_client is not null) await _client.DisposeAsync();
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
