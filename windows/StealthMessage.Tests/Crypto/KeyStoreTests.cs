using System.Runtime.Versioning;
using Microsoft.Extensions.Logging.Abstractions;
using StealthMessage.Crypto;

namespace StealthMessage.Tests.Crypto;

/// <summary>
/// KeyStore tests run against the real DPAPI (CurrentUser) — no mocking.
/// Each test class instance gets its own temporary directory for full isolation.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class KeyStoreTests : IDisposable
{
    private readonly string _tempDir;

    public KeyStoreTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "stealth-message-tests-" + Guid.NewGuid());
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); } catch { /* best effort */ }
    }

    private KeyStore CreateStore() =>
        new(NullLogger<KeyStore>.Instance, _tempDir);

    // ------------------------------------------------------------------
    // Tests
    // ------------------------------------------------------------------

    [Fact]
    public void HasIdentity_ReturnsFalse_BeforeSaving()
    {
        Assert.False(CreateStore().HasIdentity());
    }

    [Fact]
    public void SaveAndLoad_PrivateKey_RoundTrip()
    {
        const string fakePriv = "-----BEGIN PGP PRIVATE KEY BLOCK-----\ntest\n-----END PGP PRIVATE KEY BLOCK-----";
        const string fakePub  = "-----BEGIN PGP PUBLIC KEY BLOCK-----\ntest\n-----END PGP PUBLIC KEY BLOCK-----";
        var store = CreateStore();

        store.SavePrivateKey(fakePriv, fakePub);

        Assert.Equal(fakePriv, store.LoadPrivateKey());
    }

    [Fact]
    public void HasIdentity_ReturnsTrueAfterSave()
    {
        var store = CreateStore();
        store.SavePrivateKey("priv", "pub");
        Assert.True(store.HasIdentity());
    }

    [Fact]
    public void DeleteAll_HasIdentityReturnsFalse()
    {
        var store = CreateStore();
        store.SavePrivateKey("priv", "pub");
        store.DeleteAll();
        Assert.False(store.HasIdentity());
    }

    [Fact]
    public void SaveAndLoadConfig_AliasRoundTrip()
    {
        var store = CreateStore();
        store.SaveConfig("Alice");
        Assert.Equal("Alice", store.LoadAlias());
    }

    [Fact]
    public void LoadAlias_ReturnsNull_WhenNoConfigFile()
    {
        Assert.Null(CreateStore().LoadAlias());
    }

    [Fact]
    public void LoadPublicKey_ReturnsCorrectContent()
    {
        const string pub = "-----BEGIN PGP PUBLIC KEY BLOCK-----\ntest\n-----END PGP PUBLIC KEY BLOCK-----";
        var store = CreateStore();
        store.SavePrivateKey("priv", pub);
        Assert.Equal(pub, store.LoadPublicKey());
    }
}
