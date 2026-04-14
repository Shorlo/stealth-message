using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace StealthMessage.Crypto;

/// <summary>
/// Persists the RSA-4096 private key on disk using DPAPI (CurrentUser scope).
/// The key is encrypted with ProtectedData before writing; the passphrase never touches disk.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class KeyStore
{
    private readonly string _keysDir;
    private readonly string _keyFile;
    private readonly string _pubFile;
    private readonly string _configFile;
    private readonly ILogger<KeyStore> _logger;

    /// <summary>
    /// Production constructor — stores under <c>%APPDATA%\stealth-message\</c>.
    /// </summary>
    public KeyStore(ILogger<KeyStore> logger)
        : this(logger, baseDir: null) { }

    /// <summary>
    /// Testable constructor — pass an explicit <paramref name="baseDir"/> to override
    /// the default <c>%APPDATA%\stealth-message\</c> location.
    /// </summary>
    public KeyStore(ILogger<KeyStore> logger, string? baseDir)
    {
        _logger = logger;
        string root = baseDir
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                            "stealth-message");
        _keysDir    = Path.Combine(root, "keys");
        _keyFile    = Path.Combine(_keysDir, "private.bin");
        _pubFile    = Path.Combine(_keysDir, "public.asc");
        _configFile = Path.Combine(root, "config.json");
        Directory.CreateDirectory(_keysDir);
    }

    /// <summary>Returns true if an encrypted private key exists on disk.</summary>
    public bool HasIdentity() => File.Exists(_keyFile);

    /// <summary>
    /// Encrypts <paramref name="armoredPrivKey"/> with DPAPI (CurrentUser) and writes it to disk.
    /// Also saves the public key in plain ASCII armor.
    /// </summary>
    public void SavePrivateKey(string armoredPrivKey, string armoredPubKey)
    {
        byte[] raw       = Encoding.UTF8.GetBytes(armoredPrivKey);
        byte[] encrypted = ProtectedData.Protect(raw, null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(_keyFile, encrypted);
        File.WriteAllText(_pubFile, armoredPubKey, Encoding.UTF8);
        _logger.LogInformation("Private key saved (DPAPI-encrypted).");
    }

    /// <summary>
    /// Reads and DPAPI-decrypts the private key from disk.
    /// Returns the ASCII-armored private key string.
    /// </summary>
    public string LoadPrivateKey()
    {
        if (!File.Exists(_keyFile))
            throw new InvalidOperationException("No identity found. Call HasIdentity() first.");

        byte[] encrypted = File.ReadAllBytes(_keyFile);
        byte[] raw       = ProtectedData.Unprotect(encrypted, null, DataProtectionScope.CurrentUser);
        return Encoding.UTF8.GetString(raw);
    }

    /// <summary>Reads the ASCII-armored public key from disk.</summary>
    public string LoadPublicKey()
    {
        if (!File.Exists(_pubFile))
            throw new InvalidOperationException("No public key found on disk.");
        return File.ReadAllText(_pubFile, Encoding.UTF8);
    }

    /// <summary>
    /// Saves the alias to config.json (no passphrase, no secrets).
    /// </summary>
    public void SaveConfig(string alias)
    {
        var config = new { alias };
        File.WriteAllText(_configFile, JsonSerializer.Serialize(config), Encoding.UTF8);
    }

    /// <summary>Loads alias from config.json. Returns null if file does not exist.</summary>
    public string? LoadAlias()
    {
        if (!File.Exists(_configFile))
            return null;
        using var doc = JsonDocument.Parse(File.ReadAllText(_configFile, Encoding.UTF8));
        return doc.RootElement.TryGetProperty("alias", out var el) ? el.GetString() : null;
    }

    /// <summary>
    /// Securely deletes all identity files (overwrites bytes with zeros before deleting).
    /// </summary>
    public void DeleteAll()
    {
        SecureDelete(_keyFile);
        SecureDelete(_pubFile);
        SecureDelete(_configFile);
        _logger.LogInformation("Identity deleted.");
    }

    private static void SecureDelete(string path)
    {
        if (!File.Exists(path)) return;
        long length = new FileInfo(path).Length;
        if (length > 0)
        {
            using var fs = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.None);
            fs.Write(new byte[length]);
            fs.Flush(flushToDisk: true);
        }
        File.Delete(path);
    }
}
