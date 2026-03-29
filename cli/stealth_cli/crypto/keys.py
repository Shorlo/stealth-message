"""PGP key generation, loading and fingerprint utilities.

All public functions accept and return ``str`` (ASCII-armored PGP blocks).
Internal conversion to/from binary is handled here; callers never touch bytes.

Security notes:
- Private keys returned by ``load_private_key`` are locked (protected).
  Callers must use ``key.unlock(passphrase)`` as a context manager to perform
  crypto operations, keeping the passphrase in memory only for the duration.
- Passphrases are never logged, stored, or included in exceptions.
"""

import pgpy
from pgpy.constants import (
    CompressionAlgorithm,
    HashAlgorithm,
    KeyFlags,
    PubKeyAlgorithm,
    SymmetricKeyAlgorithm,
)


def generate_keypair(alias: str, passphrase: str) -> tuple[str, str]:
    """Generate a passphrase-protected RSA-4096 keypair.

    Args:
        alias: Human-readable name embedded in the key UID (max 64 chars).
        passphrase: Passphrase used to protect the private key.

    Returns:
        A ``(armored_private, armored_public)`` tuple of ASCII-armored strings.
    """
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 4096)
    uid = pgpy.PGPUID.new(alias)
    key.add_uid(
        uid,
        usage={
            KeyFlags.Sign,
            KeyFlags.EncryptCommunications,
            KeyFlags.EncryptStorage,
        },
        hashes=[HashAlgorithm.SHA512, HashAlgorithm.SHA384, HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.Uncompressed],
    )
    key.protect(passphrase, SymmetricKeyAlgorithm.AES256, HashAlgorithm.SHA256)

    armored_private = str(key)
    armored_public = str(key.pubkey)
    return armored_private, armored_public


def load_private_key(armored: str, passphrase: str) -> pgpy.PGPKey:
    """Load and validate a passphrase-protected private key.

    The returned key is locked. Use ``with key.unlock(passphrase)`` to
    temporarily unlock it for crypto operations.

    Args:
        armored: ASCII-armored PGP private key block.
        passphrase: Passphrase that protects the key.

    Returns:
        The loaded ``pgpy.PGPKey`` in locked (protected) state.

    Raises:
        ValueError: If ``armored`` does not contain a private key.
        pgpy.errors.PGPDecryptionError: If ``passphrase`` is incorrect.
    """
    if "BEGIN PGP PRIVATE KEY BLOCK" not in armored:
        raise ValueError("armored does not contain a private key")

    key, _ = pgpy.PGPKey.from_blob(armored)

    # Validate the passphrase immediately; raises PGPDecryptionError if wrong.
    with key.unlock(passphrase):
        pass

    return key


def load_public_key(armored: str) -> pgpy.PGPKey:
    """Load a PGP public key from an ASCII-armored block.

    Args:
        armored: ASCII-armored PGP public key block.

    Returns:
        The loaded ``pgpy.PGPKey`` (public only).

    Raises:
        ValueError: If ``armored`` contains a private key instead of a public key.
    """
    if "BEGIN PGP PRIVATE KEY BLOCK" in armored:
        raise ValueError(
            "armored contains a private key; use load_private_key instead"
        )

    key, _ = pgpy.PGPKey.from_blob(armored)
    return key


def get_fingerprint(armored_public: str) -> str:
    """Return the fingerprint of a public key formatted in groups of 4 characters.

    Example output: ``"A1B2 C3D4 E5F6 7890 ABCD EF12 3456 7890 ABCD EF12"``

    The grouped format is the standard presentation for manual out-of-band
    verification between users (see docs/protocol.md §6).

    Args:
        armored_public: ASCII-armored PGP public key block.

    Returns:
        40-character hex fingerprint split into 10 groups of 4, separated
        by single spaces (total length: 49 characters).
    """
    key = load_public_key(armored_public)
    raw = str(key.fingerprint).upper()
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))
