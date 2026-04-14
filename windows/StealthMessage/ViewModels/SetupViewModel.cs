using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Security;
using System.Windows.Input;
using StealthMessage.Crypto;

namespace StealthMessage.ViewModels;

public sealed class SetupViewModel : INotifyPropertyChanged
{
    private readonly PgpManager   _pgp;
    private readonly KeyStore     _keyStore;
    private readonly AppViewModel _app;

    private string      _alias           = string.Empty;
    private SecureString _passphrase     = new();
    private SecureString _confirmPass    = new();
    private string      _fingerprint     = string.Empty;
    private string      _errorMessage    = string.Empty;
    private bool        _isGenerating;
    private bool        _isComplete;

    public SetupViewModel(PgpManager pgp, KeyStore keyStore, AppViewModel app)
    {
        _pgp      = pgp;
        _keyStore = keyStore;
        _app      = app;
        GenerateCommand = new RelayCommand(async () => await GenerateAsync(), CanGenerate);
    }

    // ---------------------------------------------------------------------------
    // Properties
    // ---------------------------------------------------------------------------

    public string Alias
    {
        get => _alias;
        set { _alias = value; OnPropertyChanged(); ((RelayCommand)GenerateCommand).NotifyCanExecuteChanged(); }
    }

    public SecureString Passphrase
    {
        get => _passphrase;
        set { _passphrase = value; OnPropertyChanged(); ((RelayCommand)GenerateCommand).NotifyCanExecuteChanged(); }
    }

    public SecureString ConfirmPassphrase
    {
        get => _confirmPass;
        set { _confirmPass = value; OnPropertyChanged(); ((RelayCommand)GenerateCommand).NotifyCanExecuteChanged(); }
    }

    public string Fingerprint
    {
        get => _fingerprint;
        private set { _fingerprint = value; OnPropertyChanged(); }
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set { _errorMessage = value; OnPropertyChanged(); }
    }

    public bool IsGenerating
    {
        get => _isGenerating;
        private set { _isGenerating = value; OnPropertyChanged(); }
    }

    public bool IsComplete
    {
        get => _isComplete;
        private set { _isComplete = value; OnPropertyChanged(); }
    }

    // ---------------------------------------------------------------------------
    // Commands
    // ---------------------------------------------------------------------------

    public ICommand GenerateCommand { get; }

    private bool CanGenerate()
    {
        return !_isGenerating
            && !string.IsNullOrWhiteSpace(_alias)
            && _passphrase.Length >= 8
            && PassphrasesMatch();
    }

    // ---------------------------------------------------------------------------
    // Generate keypair
    // ---------------------------------------------------------------------------

    private async Task GenerateAsync()
    {
        if (!PassphrasesMatch())
        {
            ErrorMessage = "Passphrases do not match.";
            return;
        }

        ErrorMessage  = string.Empty;
        IsGenerating  = true;

        try
        {
            var (armoredPriv, armoredPub) = await _pgp.GenerateKeypairAsync(_alias, _passphrase);
            string fingerprint = _pgp.GetFingerprint(armoredPub);

            _keyStore.SavePrivateKey(armoredPriv, armoredPub);
            _keyStore.SaveConfig(_alias);

            // Clone passphrase for session (PasswordBox resets on navigate)
            var sessionPass = _passphrase.Copy();
            _app.SetSession(armoredPriv, armoredPub, _alias, fingerprint, sessionPass);

            Fingerprint = fingerprint;
            IsComplete  = true;

            // Navigate to Hub after brief display of fingerprint
            await Task.Delay(2000);
            _app.NavigateTo(Screen.Hub);
        }
        catch (KeyGenerationException ex)
        {
            ErrorMessage = $"Key generation failed: {ex.Message}";
        }
        catch (Exception ex)
        {
            ErrorMessage = $"Unexpected error: {ex.Message}";
        }
        finally
        {
            IsGenerating = false;
        }
    }

    private bool PassphrasesMatch()
    {
        if (_passphrase.Length != _confirmPass.Length) return false;
        // SecureString comparison without exposing either to memory as string
        nint p1 = System.Runtime.InteropServices.Marshal.SecureStringToGlobalAllocUnicode(_passphrase);
        nint p2 = System.Runtime.InteropServices.Marshal.SecureStringToGlobalAllocUnicode(_confirmPass);
        try
        {
            return System.Runtime.InteropServices.Marshal.PtrToStringUni(p1)
                == System.Runtime.InteropServices.Marshal.PtrToStringUni(p2);
        }
        finally
        {
            System.Runtime.InteropServices.Marshal.ZeroFreeGlobalAllocUnicode(p1);
            System.Runtime.InteropServices.Marshal.ZeroFreeGlobalAllocUnicode(p2);
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
