using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Security;
using System.Windows.Input;
using StealthMessage.Crypto;

namespace StealthMessage.ViewModels;

public sealed class UnlockViewModel : INotifyPropertyChanged
{
    private readonly PgpManager   _pgp;
    private readonly KeyStore     _keyStore;
    private readonly AppViewModel _app;

    private SecureString _passphrase   = new();
    private string       _errorMessage = string.Empty;
    private bool         _isUnlocking;

    public UnlockViewModel(PgpManager pgp, KeyStore keyStore, AppViewModel app)
    {
        _pgp      = pgp;
        _keyStore = keyStore;
        _app      = app;
        UnlockCommand        = new RelayCommand(UnlockAsync);
        ResetIdentityCommand = new RelayCommand(ResetIdentityAsync);
    }

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public SecureString Passphrase
    {
        get => _passphrase;
        set { _passphrase = value; OnPropertyChanged(); }
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set { _errorMessage = value; OnPropertyChanged(); }
    }

    public bool IsUnlocking
    {
        get => _isUnlocking;
        private set { _isUnlocking = value; OnPropertyChanged(); }
    }

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand UnlockCommand        { get; }
    public ICommand ResetIdentityCommand { get; }

    // ---------------------------------------------------------------------------
    // Unlock
    // ---------------------------------------------------------------------------

    private async Task UnlockAsync()
    {
        ErrorMessage = string.Empty;
        IsUnlocking  = true;
        try
        {
            string armoredPriv = _keyStore.LoadPrivateKey();
            string armoredPub  = _keyStore.LoadPublicKey();
            string? alias      = _keyStore.LoadAlias() ?? "Unknown";

            // Validate passphrase by attempting key generation op
            // (PgpCore will throw if the passphrase can't unlock the key)
            await ValidatePassphraseAsync(armoredPriv, _passphrase);

            string fingerprint = _pgp.GetFingerprint(armoredPub);
            var sessionPass    = _passphrase.Copy();
            _app.SetSession(armoredPriv, armoredPub, alias, fingerprint, sessionPass);
            _app.NavigateTo(Screen.Hub);
        }
        catch (DecryptionFailedException)
        {
            ErrorMessage = "Wrong passphrase. Please try again.";
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Unlock failed: {ex.Message}";
        }
        finally
        {
            IsUnlocking = false;
        }
    }

    /// <summary>
    /// Validates the passphrase by trying to perform a PGP sign operation.
    /// Throws <see cref="DecryptionFailedException"/> if passphrase is wrong.
    /// </summary>
    private async Task ValidatePassphraseAsync(string armoredPriv, SecureString passphrase)
    {
        // Encrypt a dummy message to self — if passphrase is wrong, PgpCore throws.
        string armoredPub = _keyStore.LoadPublicKey();
        await _pgp.EncryptAsync("ping", armoredPub, armoredPriv, passphrase);
    }

    // ---------------------------------------------------------------------------
    // Reset identity
    // ---------------------------------------------------------------------------

    private async Task ResetIdentityAsync()
    {
        // The View is responsible for showing a confirmation dialog before calling this.
        _app.ClearSession();
        _keyStore.DeleteAll();
        _app.NavigateTo(Screen.Setup);
        await Task.CompletedTask;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
