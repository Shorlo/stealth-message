using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using StealthMessage.Crypto;
using StealthMessage.Network;

namespace StealthMessage.ViewModels;

public sealed class HubViewModel : INotifyPropertyChanged
{
    private readonly PgpManager   _pgp;
    private readonly AppViewModel _app;

    private string _serverAddress = string.Empty;
    private string _port          = "8765";
    private string _roomId        = string.Empty;
    private string _errorMessage  = string.Empty;
    private bool   _isDiscovering;

    public HubViewModel(PgpManager pgp, AppViewModel app)
    {
        _pgp = pgp;
        _app = app;

        HostCommand            = new RelayCommand(HostAsync);
        JoinCommand            = new RelayCommand(JoinAsync);
        ResumeJoinCommand      = new RelayCommand(ResumeJoinAsync);
        DiscoverRoomsCommand   = new RelayCommand(DiscoverRoomsAsync);
        CopyFingerprintCommand = new SyncRelayCommand(CopyFingerprint);
    }

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public string Fingerprint => _app.Fingerprint ?? string.Empty;
    public string Alias       => _app.Alias       ?? string.Empty;

    // Resume state — read live from the preserved ViewModels
    public bool IsHostRunning   => _app.ActiveHostViewModel?.IsRunning   ?? false;
    public bool IsJoinConnected => _app.ActiveJoinViewModel?.IsConnected ?? false;

    public string ServerAddress
    {
        get => _serverAddress;
        set { _serverAddress = value; OnPropertyChanged(); }
    }

    public string Port
    {
        get => _port;
        set { _port = value; OnPropertyChanged(); }
    }

    public string RoomId
    {
        get => _roomId;
        set { _roomId = value; OnPropertyChanged(); }
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set { _errorMessage = value; OnPropertyChanged(); }
    }

    public bool IsDiscovering
    {
        get => _isDiscovering;
        private set { _isDiscovering = value; OnPropertyChanged(); }
    }

    public ObservableCollection<RoomInfo> AvailableRooms { get; } = new();

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand HostCommand            { get; }
    public ICommand JoinCommand            { get; }
    public ICommand ResumeJoinCommand      { get; }
    public ICommand DiscoverRoomsCommand   { get; }
    public ICommand CopyFingerprintCommand { get; }

    // ---------------------------------------------------------------------------
    // Discover rooms
    // ---------------------------------------------------------------------------

    private async Task DiscoverRoomsAsync()
    {
        ErrorMessage  = string.Empty;
        IsDiscovering = true;
        AvailableRooms.Clear();
        try
        {
            if (!Uri.TryCreate(BuildServerUri(), UriKind.Absolute, out var uri))
            {
                ErrorMessage = "Invalid server address.";
                return;
            }
            var rooms = await StealthClient.QueryRoomsAsync(uri, NullLogger<StealthClient>.Instance);
            foreach (var r in rooms)
                AvailableRooms.Add(r);
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Discovery failed: {ex.Message}";
        }
        finally
        {
            IsDiscovering = false;
        }
    }

    // ---------------------------------------------------------------------------
    // Host / Join navigation
    // ---------------------------------------------------------------------------

    private Task HostAsync()
    {
        _app.NavigateTo(Screen.Host);
        return Task.CompletedTask;
    }

    private Task JoinAsync()
    {
        ErrorMessage = string.Empty;
        if (string.IsNullOrWhiteSpace(_serverAddress))
        {
            ErrorMessage = "Enter a server address.";
            return Task.CompletedTask;
        }
        // Pass server address and room so JoinView doesn't need re-entry
        _app.NavigateToJoin(BuildServerUri(), _roomId);
        return Task.CompletedTask;
    }

    private Task ResumeJoinAsync()
    {
        _app.NavigateTo(Screen.Join);
        return Task.CompletedTask;
    }

    // ---------------------------------------------------------------------------
    // Clipboard
    // ---------------------------------------------------------------------------

    private void CopyFingerprint()
    {
        var pkg = new Windows.ApplicationModel.DataTransfer.DataPackage();
        pkg.SetText(Fingerprint);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(pkg);
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    private string BuildServerUri()
    {
        string addr = _serverAddress.Contains("://") ? _serverAddress : $"ws://{_serverAddress}";
        if (!addr.Contains(':')) addr += $":{_port}";
        return addr;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
