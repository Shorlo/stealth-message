using System.Security;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging.Abstractions;
using StealthMessage.Crypto;

namespace StealthMessage.Tests.Crypto;

public sealed class PgpManagerTests
{
    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    private static readonly string TestPassphrase = "test-passphrase-stealth";
    private static readonly string TestAlias      = "Test User";

    private static PgpManager CreateManager() =>
        new(NullLogger<PgpManager>.Instance);

    private static SecureString ToSecure(string s)
    {
        var ss = new SecureString();
        foreach (char c in s) ss.AppendChar(c);
        ss.MakeReadOnly();
        return ss;
    }

    // ------------------------------------------------------------------
    // Shared keypair (generated once per test class for speed)
    // ------------------------------------------------------------------
    private static (string armoredPriv, string armoredPub) _aliceKeys;
    private static (string armoredPriv, string armoredPub) _bobKeys;
    private static readonly object _keyLock = new();
    private static bool _keysGenerated;

    private static async Task<((string privA, string pubA) alice, (string privB, string pubB) bob)>
        GetKeysAsync()
    {
        lock (_keyLock)
        {
            if (_keysGenerated)
                return (_aliceKeys, _bobKeys);
        }

        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);
        var alice = await mgr.GenerateKeypairAsync(TestAlias, pass);
        var bob   = await mgr.GenerateKeypairAsync("Bob", pass);

        lock (_keyLock)
        {
            _aliceKeys    = alice;
            _bobKeys      = bob;
            _keysGenerated = true;
            return (_aliceKeys, _bobKeys);
        }
    }

    // ------------------------------------------------------------------
    // Tests
    // ------------------------------------------------------------------

    [Fact]
    public async Task GenerateKeypair_ReturnsNonEmptyArmoredStrings()
    {
        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);
        var (priv, pub) = await mgr.GenerateKeypairAsync(TestAlias, pass);

        Assert.NotEmpty(priv);
        Assert.NotEmpty(pub);
        Assert.Contains("PGP PRIVATE KEY BLOCK", priv);
        Assert.Contains("PGP PUBLIC KEY BLOCK", pub);
    }

    [Fact]
    public async Task GetFingerprint_FormatIs40HexGroupedBy4()
    {
        var (_, (_, pubA)) = await GetKeysAsync();
        var mgr = CreateManager();
        string fp = mgr.GetFingerprint(pubA);

        // Must match: "XXXX XXXX ... XXXX" — 10 groups of 4 hex chars separated by spaces
        Assert.Matches(new Regex(@"^([0-9A-Fa-f]{4}\s){9}[0-9A-Fa-f]{4}$"), fp);
        // Total printable chars = 40 hex + 9 spaces
        Assert.Equal(49, fp.Length);
    }

    [Fact]
    public async Task EncryptDecrypt_RoundTrip_ReturnsOriginalPlaintext()
    {
        var ((privA, pubA), (privB, pubB)) = await GetKeysAsync();
        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);

        const string message = "Hello, stealth world!";
        string payload   = await mgr.EncryptAsync(message, pubB, privA, pass);
        string decrypted = await mgr.DecryptAsync(payload, privB, pubA, pass);

        Assert.Equal(message, decrypted);
    }

    [Fact]
    public async Task Encrypt_PayloadContainsNoBase64StandardChars()
    {
        var ((privA, pubA), (_, pubB)) = await GetKeysAsync();
        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);

        string payload = await mgr.EncryptAsync("test", pubB, privA, pass);

        Assert.DoesNotContain('+', payload);
        Assert.DoesNotContain('/', payload);
        Assert.DoesNotContain('=', payload);
    }

    [Fact]
    public async Task Decrypt_WrongSenderPubKey_ThrowsSignatureInvalidException()
    {
        var ((privA, pubA), (privB, pubB)) = await GetKeysAsync();
        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);

        // Alice encrypts for Bob
        string payload = await mgr.EncryptAsync("secret", pubB, privA, pass);

        // Bob decrypts but verifies against his own pub key (wrong sender key → sig invalid)
        await Assert.ThrowsAsync<SignatureInvalidException>(
            () => mgr.DecryptAsync(payload, privB, pubB, pass));
    }

    [Fact]
    public async Task Decrypt_CorruptedPayload_ThrowsDecryptionFailedException()
    {
        var (_, (privB, _)) = await GetKeysAsync();
        var (_, (_, pubA))  = await GetKeysAsync();
        var mgr = CreateManager();
        using var pass = ToSecure(TestPassphrase);

        string corrupted = "aGVsbG8gd29ybGQ"; // random base64url — not valid PGP

        await Assert.ThrowsAsync<DecryptionFailedException>(
            () => mgr.DecryptAsync(corrupted, privB, pubA, pass));
    }

    [Fact]
    public void Base64UrlEncode_NoPaddingOrStandardChars()
    {
        byte[] data    = Enumerable.Range(0, 256).Select(i => (byte)i).ToArray();
        string encoded = PgpManager.Base64UrlEncode(data);

        Assert.DoesNotContain('+', encoded);
        Assert.DoesNotContain('/', encoded);
        Assert.DoesNotContain('=', encoded);
    }

    [Fact]
    public void Base64UrlDecode_RoundTrip()
    {
        byte[] original = Encoding.UTF8.GetBytes("stealth-message test payload");
        string encoded  = PgpManager.Base64UrlEncode(original);
        byte[] decoded  = PgpManager.Base64UrlDecode(encoded);

        Assert.Equal(original, decoded);
    }
}
