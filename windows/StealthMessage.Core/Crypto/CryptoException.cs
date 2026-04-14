namespace StealthMessage.Crypto;

/// <summary>
/// Thrown when PGP signature verification fails. The message must be discarded.
/// </summary>
public sealed class SignatureInvalidException(string? message = null)
    : Exception(message ?? "PGP signature verification failed — message discarded.");

/// <summary>
/// Thrown when decryption fails (wrong key or corrupted payload).
/// </summary>
public sealed class DecryptionFailedException(string? message = null, Exception? inner = null)
    : Exception(message ?? "Decryption failed — wrong key or corrupted payload.", inner);

/// <summary>
/// Thrown when RSA-4096 key generation fails.
/// </summary>
public sealed class KeyGenerationException(string? message = null, Exception? inner = null)
    : Exception(message ?? "Key generation failed.", inner);
