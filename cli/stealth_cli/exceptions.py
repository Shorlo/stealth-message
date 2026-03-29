"""Custom exceptions for stealth-message CLI.

All exceptions raised by stealth_cli modules are defined here.
Network and protocol error codes follow docs/protocol.md §4.
"""


class StealthError(Exception):
    """Base exception for all stealth-message errors."""


class SignatureError(StealthError):
    """Raised when a PGP signature is missing, invalid, or cannot be verified.

    Callers receiving this exception must discard the message and notify the
    user — never display plaintext from an unverified message (protocol.md §2.1).
    """


class ProtocolError(StealthError):
    """Raised when a received WebSocket message violates the protocol spec.

    Attributes:
        code: Numeric error code defined in protocol.md §4.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code
