using System.Runtime.InteropServices;
using System.Security;
using System.Text;
using Microsoft.Extensions.Logging;
using Org.BouncyCastle.Bcpg;
using Org.BouncyCastle.Bcpg.OpenPgp;
using PgpCore;

namespace StealthMessage.Crypto;

/// <summary>
/// All PGP operations: key generation (RSA-4096), sign-then-encrypt, decrypt-then-verify,
/// and fingerprint formatting.  Passphrase is accepted as <see cref="SecureString"/> and
/// converted to a plain string only for the duration of each individual cryptographic operation.
/// </summary>
public sealed class PgpManager
{
    private readonly ILogger<PgpManager> _logger;

    public PgpManager(ILogger<PgpManager> logger)
    {
        _logger = logger;
    }

    // -------------------------------------------------------------------------
    // Key generation
    // -------------------------------------------------------------------------

    /// <summary>
    /// Generates an RSA-4096 keypair. Alias is embedded in the key UID.
    /// </summary>
    /// <returns>ASCII-armored (private key, public key) tuple.</returns>
    public async Task<(string armoredPriv, string armoredPub)> GenerateKeypairAsync(
        string alias, SecureString passphrase)
    {
        if (string.IsNullOrWhiteSpace(alias))
            throw new ArgumentException("Alias must not be empty.", nameof(alias));

        string pass = ToInsecureString(passphrase);
        try
        {
            using var pubStream  = new MemoryStream();
            using var privStream = new MemoryStream();
            var pgp = new PGP();
            await pgp.GenerateKeyAsync(pubStream, privStream, alias, pass, strength: 4096);
            string armoredPub  = Encoding.UTF8.GetString(pubStream.ToArray());
            string armoredPriv = Encoding.UTF8.GetString(privStream.ToArray());
            _logger.LogInformation("RSA-4096 keypair generated for alias '{Alias}'.", alias);
            return (armoredPriv, armoredPub);
        }
        catch (Exception ex)
        {
            throw new KeyGenerationException(inner: ex);
        }
        finally
        {
            // Overwrite local pass variable as soon as possible
            pass = new string('\0', pass.Length);
        }
    }

    // -------------------------------------------------------------------------
    // Fingerprint
    // -------------------------------------------------------------------------

    /// <summary>
    /// Returns the fingerprint of an ASCII-armored public key.
    /// Format: 40 uppercase hex characters grouped by 4, space-separated.
    /// Example: "A1B2 C3D4 E5F6 7890 A1B2 C3D4 E5F6 7890 A1B2 C3D4"
    /// </summary>
    public string GetFingerprint(string armoredPub)
    {
        byte[] raw = Encoding.UTF8.GetBytes(armoredPub);
        using var armoredStream = new ArmoredInputStream(new MemoryStream(raw));
        var factory = new PgpObjectFactory(armoredStream);
        PgpPublicKey pubKey;

        if (factory.NextPgpObject() is PgpPublicKeyRing ring)
        {
            pubKey = ring.GetPublicKey();
        }
        else
        {
            throw new ArgumentException("Could not read PGP public key from armored data.");
        }

        byte[] fp  = pubKey.GetFingerprint();
        string hex = BitConverter.ToString(fp).Replace("-", "", StringComparison.Ordinal)
                                              .ToUpperInvariant();
        // Group hex string into chunks of 4 characters separated by spaces
        return string.Join(" ",
            Enumerable.Range(0, hex.Length / 4)
                      .Select(i => hex.Substring(i * 4, 4)));
    }

    // -------------------------------------------------------------------------
    // Encrypt (send pipeline)
    // -------------------------------------------------------------------------

    /// <summary>
    /// Signs <paramref name="plaintext"/> with <paramref name="senderPriv"/> then encrypts
    /// it for <paramref name="recipientPub"/>.
    /// </summary>
    /// <returns>
    /// ASCII-armored PGP message encoded as Base64 URL-safe (no padding, RFC 4648 §5).
    /// </returns>
    public async Task<string> EncryptAsync(
        string plaintext,
        string recipientPub,
        string senderPriv,
        SecureString passphrase)
    {
        string pass = ToInsecureString(passphrase);
        try
        {
            using var recipientPubStream = ToStream(recipientPub);
            using var senderPrivStream   = ToStream(senderPriv);
            var keys = new EncryptionKeys(recipientPubStream, senderPrivStream, pass);
            var pgp  = new PGP(keys);

            using var inputStream  = ToStream(plaintext);
            using var outputStream = new MemoryStream();
            await pgp.EncryptAndSignAsync(inputStream, outputStream);

            // ASCII-armored PGP message → Base64 URL-safe, no padding
            byte[] armoredBytes = outputStream.ToArray();
            return Base64UrlEncode(armoredBytes);
        }
        catch (Exception ex) when (ex is not SignatureInvalidException
                                       and not DecryptionFailedException)
        {
            throw new DecryptionFailedException("Encryption failed.", ex);
        }
        finally
        {
            pass = new string('\0', pass.Length);
        }
    }

    // -------------------------------------------------------------------------
    // Decrypt (receive pipeline)
    // -------------------------------------------------------------------------

    /// <summary>
    /// Base64 URL-safe decodes <paramref name="payload"/>, decrypts it with
    /// <paramref name="recipientPriv"/>, and verifies the PGP signature against
    /// <paramref name="senderPub"/>.
    /// </summary>
    /// <exception cref="SignatureInvalidException">
    /// Thrown when the signature is missing or does not verify — caller must discard the message.
    /// </exception>
    /// <exception cref="DecryptionFailedException">
    /// Thrown when decryption fails (wrong key, corruption).
    /// </exception>
    public async Task<string> DecryptAsync(
        string payload,
        string recipientPriv,
        string senderPub,
        SecureString passphrase)
    {
        string pass = ToInsecureString(passphrase);
        try
        {
            byte[] armoredBytes = Base64UrlDecode(payload);
            string armoredMsg   = Encoding.UTF8.GetString(armoredBytes);

            using var senderPubStream    = ToStream(senderPub);
            using var recipientPrivStream = ToStream(recipientPriv);
            var keys = new EncryptionKeys(senderPubStream, recipientPrivStream, pass);
            var pgp  = new PGP(keys);

            using var inputStream  = ToStream(armoredMsg);
            using var outputStream = new MemoryStream();
            await pgp.DecryptAndVerifyAsync(inputStream, outputStream);

            return Encoding.UTF8.GetString(outputStream.ToArray());
        }
        catch (PgpException ex) when (IsSignatureError(ex))
        {
            _logger.LogWarning("Signature verification failed — message discarded.");
            throw new SignatureInvalidException();
        }
        catch (Exception ex) when (ex is not SignatureInvalidException)
        {
            throw new DecryptionFailedException(inner: ex);
        }
        finally
        {
            pass = new string('\0', pass.Length);
        }
    }

    // -------------------------------------------------------------------------
    // Base64 URL-safe helpers (RFC 4648 §5, no padding)
    // -------------------------------------------------------------------------

    public static string Base64UrlEncode(byte[] data)
    {
        return Convert.ToBase64String(data)
                      .Replace('+', '-')
                      .Replace('/', '_')
                      .TrimEnd('=');
    }

    public static byte[] Base64UrlDecode(string encoded)
    {
        string s = encoded.Replace('-', '+').Replace('_', '/');
        switch (s.Length % 4)
        {
            case 2: s += "=="; break;
            case 3: s += "=";  break;
        }
        return Convert.FromBase64String(s);
    }

    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------

    private static string ToInsecureString(SecureString ss)
    {
        IntPtr ptr = Marshal.SecureStringToGlobalAllocUnicode(ss);
        try   { return Marshal.PtrToStringUni(ptr)!; }
        finally { Marshal.ZeroFreeGlobalAllocUnicode(ptr); }
    }

    private static MemoryStream ToStream(string text)
    {
        var ms = new MemoryStream(Encoding.UTF8.GetBytes(text));
        ms.Seek(0, SeekOrigin.Begin);
        return ms;
    }

    private static bool IsSignatureError(PgpException ex)
    {
        string msg = ex.Message ?? string.Empty;
        return msg.Contains("verif", StringComparison.OrdinalIgnoreCase)
            || msg.Contains("sign",  StringComparison.OrdinalIgnoreCase)
            || msg.Contains("bad",   StringComparison.OrdinalIgnoreCase);
    }
}
