using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Security;
using Microsoft.Extensions.Logging;
using StealthMessage.Crypto;

namespace StealthMessage.ViewModels;

/// <summary>
/// Screens in the app state machine.
/// </summary>
public enum Screen { Setup, Unlock, Hub, Host, Join }

/// <summary>
/// Root state machine. Holds references to shared services and navigates between screens.
/// All ViewModels receive their dependencies through this class.
/// </summary>
public sealed class AppViewModel : INotifyPropertyChanged
{
    private readonly ILogger<AppViewModel>   _logger;
    private readonly PgpManager             _pgp;
    private readonly KeyStore               _keyStore;

    private Screen   _currentScreen  = Screen.Setup;
    private object?  _currentViewModel;

    // Persisted ViewModels — survive Hub ↔ Host/Join navigation (same as macOS)
    private HostViewModel? _activeHostViewModel;
    private JoinViewModel? _activeJoinViewModel;

    // Session state — held in memory only
    private string?     _armoredPriv;
    private string?     _armoredPub;
    private string?     _alias;
    private string?     _fingerprint;
    private SecureString? _sessionPassphrase;

    public AppViewModel(
        ILogger<AppViewModel> logger,
        PgpManager            pgp,
        KeyStore              keyStore)
    {
        _logger   = logger;
        _pgp      = pgp;
        _keyStore = keyStore;
    }

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public Screen CurrentScreen
    {
        get => _currentScreen;
        private set { _currentScreen = value; OnPropertyChanged(); }
    }

    public object? CurrentViewModel
    {
        get => _currentViewModel;
        private set { _currentViewModel = value; OnPropertyChanged(); }
    }

    // Read-only session fields (set once per session)
    public string? Alias       => _alias;
    public string? Fingerprint => _fingerprint;

    // Active screen ViewModels — exposed so Hub can read running/connected state
    public HostViewModel? ActiveHostViewModel => _activeHostViewModel;
    public JoinViewModel? ActiveJoinViewModel => _activeJoinViewModel;

    // ---------------------------------------------------------------------------
    // Initialisation — call once on app startup
    // ---------------------------------------------------------------------------

    public void Initialize()
    {
        if (_keyStore.HasIdentity())
        {
            NavigateTo(Screen.Unlock);
        }
        else
        {
            NavigateTo(Screen.Setup);
        }
    }

    // ---------------------------------------------------------------------------
    // Navigation
    // ---------------------------------------------------------------------------

    public void NavigateTo(Screen screen)
    {
        CurrentScreen = screen;
        CurrentViewModel = screen switch
        {
            Screen.Setup   => new SetupViewModel(_pgp, _keyStore, this),
            Screen.Unlock  => new UnlockViewModel(_pgp, _keyStore, this),
            Screen.Hub     => new HubViewModel(_pgp, this),
            // Reuse existing VMs so a running server / active connection survives Hub navigation
            Screen.Host    => _activeHostViewModel ??= new HostViewModel(_pgp, this),
            Screen.Join    => _activeJoinViewModel ??= new JoinViewModel(_pgp, this),
            _              => throw new ArgumentOutOfRangeException(nameof(screen))
        };
        _logger.LogInformation("Navigated to {Screen}.", screen);
    }

    /// <summary>
    /// Returns to the Hub screen without destroying Host or Join ViewModels.
    /// A running server and active connections remain intact.
    /// </summary>
    public void ReturnToHub()
    {
        CurrentScreen    = Screen.Hub;
        CurrentViewModel = new HubViewModel(_pgp, this);
        _logger.LogInformation("Returned to Hub.");
    }

    /// <summary>
    /// Navigates to the Join screen, pre-filling server URI and room if provided.
    /// Reuses an existing JoinViewModel if one is present.
    /// </summary>
    public void NavigateToJoin(string serverUri = "", string roomId = "")
    {
        _activeJoinViewModel ??= new JoinViewModel(_pgp, this);
        if (!string.IsNullOrEmpty(serverUri))
            _activeJoinViewModel.ServerUri = serverUri;
        if (!string.IsNullOrEmpty(roomId))
            _activeJoinViewModel.RoomId = roomId;
        CurrentScreen    = Screen.Join;
        CurrentViewModel = _activeJoinViewModel;
        _logger.LogInformation("Navigated to Join.");
    }

    // ---------------------------------------------------------------------------
    // Session management (called by Setup/Unlock ViewModels)
    // ---------------------------------------------------------------------------

    internal void SetSession(
        string       armoredPriv,
        string       armoredPub,
        string       alias,
        string       fingerprint,
        SecureString passphrase)
    {
        // Dispose previous session passphrase if any
        _sessionPassphrase?.Dispose();

        _armoredPriv       = armoredPriv;
        _armoredPub        = armoredPub;
        _alias             = alias;
        _fingerprint       = fingerprint;
        _sessionPassphrase = passphrase;

        // Discard any VMs left over from a previous session
        _activeHostViewModel = null;
        _activeJoinViewModel = null;

        OnPropertyChanged(nameof(Alias));
        OnPropertyChanged(nameof(Fingerprint));
    }

    internal void ClearSession()
    {
        _sessionPassphrase?.Dispose();
        _sessionPassphrase = null;
        _armoredPriv       = null;
        _armoredPub        = null;
        _alias             = null;
        _fingerprint       = null;
    }

    /// <summary>Returns session credentials — only valid after Setup or Unlock.</summary>
    internal (string armoredPriv, string armoredPub, string alias, SecureString passphrase)
        GetCredentials()
    {
        if (_armoredPriv is null || _armoredPub is null ||
            _alias is null || _sessionPassphrase is null)
            throw new InvalidOperationException("No active session.");
        return (_armoredPriv, _armoredPub, _alias, _sessionPassphrase);
    }

    // ---------------------------------------------------------------------------
    // INotifyPropertyChanged
    // ---------------------------------------------------------------------------

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
