"""PGP message encryption and decryption (protocol.md §2.1).

All public functions accept and return ``str``. Internal conversion between
``str``, ``bytes`` and pgpy objects is handled here; callers never touch bytes.

Caller contract:
    The ``pgpy.PGPKey`` arguments must be **already unlocked** via
    ``with key.unlock(passphrase)`` before calling these functions.
    Managing the passphrase and the unlock lifetime is the UI layer's
    responsibility (cli/stealth_cli/ui/), not this module's.

Encoding pipeline (encrypt):
    plaintext str
        → pgpy.PGPMessage  (literal data packet)
        → sign with sender's private key  (inline one-pass signature)
        → encrypt with recipient's public key  (PGP encrypted message)
        → ASCII-armored str
        → Base64 URL-safe str  ← this is the JSON "payload" field

Decoding pipeline (decrypt):
    Base64 URL-safe str  (JSON "payload" field)
        → ASCII-armored str
        → pgpy encrypted message
        → decrypt with recipient's private key
        → verify inline signature with sender's public key
        → plaintext str  (only if signature is valid)
"""

import base64

import pgpy

from stealth_cli.crypto.keys import load_public_key
from stealth_cli.exceptions import SignatureError


def encrypt(
    plaintext: str,
    recipient_pubkey: str,
    sender_privkey: pgpy.PGPKey,
) -> str:
    """Encrypt and sign a plaintext message.

    The output is suitable for use as the ``"payload"`` field in a
    protocol.md §2.1 message JSON object.

    Args:
        plaintext: UTF-8 text to encrypt.
        recipient_pubkey: ASCII-armored PGP public key of the recipient.
        sender_privkey: Sender's private key, **already unlocked** by the
            caller via ``with sender_privkey.unlock(passphrase)``.

    Returns:
        Base64 URL-safe string containing the ASCII-armored PGP encrypted
        message (sign-then-encrypt).
    """
    pub = load_public_key(recipient_pubkey)

    msg = pgpy.PGPMessage.new(plaintext)

    # Sign with sender's private key (key must be unlocked by the caller).
    msg |= sender_privkey.sign(msg)

    # Encrypt with recipient's public key.
    encrypted = pub.encrypt(msg)

    # ASCII-armor → UTF-8 bytes → Base64 URL-safe string.
    armored = str(encrypted)
    return base64.urlsafe_b64encode(armored.encode("utf-8")).decode("ascii")


def decrypt(
    payload: str,
    recipient_privkey: pgpy.PGPKey,
    sender_pubkey: str,
) -> str:
    """Decrypt a payload and verify the sender's signature.

    Implements the decryption and verification steps of protocol.md §2.1.
    The message is returned **only** if the signature is valid; otherwise
    ``SignatureError`` is raised so the caller can discard the message.

    Args:
        payload: Base64 URL-safe string from the ``"payload"`` JSON field.
        recipient_privkey: Recipient's private key, **already unlocked** by
            the caller via ``with recipient_privkey.unlock(passphrase)``.
        sender_pubkey: ASCII-armored PGP public key of the sender.

    Returns:
        Decrypted plaintext as a UTF-8 string.

    Raises:
        SignatureError: If the signature is invalid, missing, or cannot be
            verified with ``sender_pubkey``. Callers must never display the
            plaintext when this exception is raised (protocol.md §2.1).
    """
    # Base64 URL-safe decode → ASCII-armored PGP message.
    # Add padding so urlsafe_b64decode never fails on missing '=' chars.
    armored = base64.urlsafe_b64decode(
        payload.encode("ascii") + b"=="
    ).decode("utf-8")

    # PGPMessage.from_blob returns the message object directly (unlike
    # PGPKey.from_blob which returns a (key, extras) tuple). Unpacking it
    # would iterate over internal packets — use the raw return value.
    result = pgpy.PGPMessage.from_blob(armored)
    encrypted_msg = result[0] if isinstance(result, tuple) else result

    # Decrypt (recipient_privkey must already be unlocked by the caller).
    decrypted = recipient_privkey.decrypt(encrypted_msg)

    # Verify the inline signature with the sender's public key.
    # protocol.md §2.1: "If the signature is not valid, discard the message."
    sender_pub = load_public_key(sender_pubkey)
    try:
        verification = sender_pub.verify(decrypted)
        if not verification:
            raise SignatureError(
                "PGP signature is invalid — message discarded (protocol.md §2.1)"
            )
    except pgpy.errors.PGPError as exc:
        raise SignatureError(
            "PGP signature verification failed — message discarded (protocol.md §2.1)"
        ) from exc

    # Return plaintext as str; pgpy may give bytes for binary literal packets.
    content = decrypted.message
    if isinstance(content, (bytes, bytearray)):
        return content.decode("utf-8")
    return str(content)
