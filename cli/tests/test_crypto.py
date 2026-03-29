"""Tests for stealth_cli.crypto.keys.

Run with:
    pytest tests/test_crypto.py -v

Note: RSA-4096 key generation is slow (~2-5 s per key). Session-scoped fixtures
generate the keypair once and reuse it across all tests.
"""

import pytest
import pgpy

from stealth_cli.crypto.keys import (
    generate_keypair,
    get_fingerprint,
    load_private_key,
    load_public_key,
)

ALIAS = "Test User"
PASSPHRASE = "test-passphrase-123"
WRONG_PASSPHRASE = "wrong-passphrase"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def keypair() -> tuple[str, str]:
    """Generate one RSA-4096 keypair for the whole test session."""
    return generate_keypair(ALIAS, PASSPHRASE)


@pytest.fixture(scope="session")
def armored_private(keypair: tuple[str, str]) -> str:
    return keypair[0]


@pytest.fixture(scope="session")
def armored_public(keypair: tuple[str, str]) -> str:
    return keypair[1]


# ---------------------------------------------------------------------------
# generate_keypair
# ---------------------------------------------------------------------------


def test_generate_keypair_returns_two_nonempty_strings(
    keypair: tuple[str, str],
) -> None:
    private, public = keypair
    assert isinstance(private, str) and len(private) > 0
    assert isinstance(public, str) and len(public) > 0


def test_generate_keypair_private_has_pgp_header(armored_private: str) -> None:
    assert "-----BEGIN PGP PRIVATE KEY BLOCK-----" in armored_private


def test_generate_keypair_public_has_pgp_header(armored_public: str) -> None:
    assert "-----BEGIN PGP PUBLIC KEY BLOCK-----" in armored_public


def test_generate_keypair_alias_present_in_key(armored_private: str) -> None:
    key, _ = pgpy.PGPKey.from_blob(armored_private)
    names = [uid.name for uid in key.userids]
    assert ALIAS in names


def test_generate_keypair_is_rsa4096(armored_private: str) -> None:
    key, _ = pgpy.PGPKey.from_blob(armored_private)
    assert key.key_size == 4096


def test_generate_keypair_private_is_passphrase_protected(
    armored_private: str,
) -> None:
    key, _ = pgpy.PGPKey.from_blob(armored_private)
    assert key.is_protected


def test_generate_keypair_two_calls_produce_different_keys() -> None:
    """Verify randomness: two independent keypairs must differ."""
    _, pub1 = generate_keypair(ALIAS, PASSPHRASE)
    _, pub2 = generate_keypair(ALIAS, PASSPHRASE)
    assert pub1 != pub2


# ---------------------------------------------------------------------------
# load_private_key
# ---------------------------------------------------------------------------


def test_load_private_key_returns_pgpkey(armored_private: str) -> None:
    key = load_private_key(armored_private, PASSPHRASE)
    assert isinstance(key, pgpy.PGPKey)


def test_load_private_key_result_is_protected(armored_private: str) -> None:
    key = load_private_key(armored_private, PASSPHRASE)
    assert key.is_protected


def test_load_private_key_wrong_passphrase_raises(armored_private: str) -> None:
    with pytest.raises(Exception):
        load_private_key(armored_private, WRONG_PASSPHRASE)


def test_load_private_key_public_input_raises(armored_public: str) -> None:
    with pytest.raises(ValueError):
        load_private_key(armored_public, PASSPHRASE)


# ---------------------------------------------------------------------------
# load_public_key
# ---------------------------------------------------------------------------


def test_load_public_key_returns_pgpkey(armored_public: str) -> None:
    key = load_public_key(armored_public)
    assert isinstance(key, pgpy.PGPKey)


def test_load_public_key_result_is_not_protected(armored_public: str) -> None:
    key = load_public_key(armored_public)
    assert not key.is_protected


def test_load_public_key_private_input_raises(armored_private: str) -> None:
    with pytest.raises(ValueError):
        load_public_key(armored_private)


# ---------------------------------------------------------------------------
# get_fingerprint
# ---------------------------------------------------------------------------


def test_get_fingerprint_returns_string(armored_public: str) -> None:
    fp = get_fingerprint(armored_public)
    assert isinstance(fp, str)


def test_get_fingerprint_groups_of_four_chars(armored_public: str) -> None:
    fp = get_fingerprint(armored_public)
    groups = fp.split(" ")
    assert all(len(g) == 4 for g in groups), f"Unexpected grouping: {fp!r}"


def test_get_fingerprint_total_length(armored_public: str) -> None:
    # 40 hex chars + 9 spaces between 10 groups = 49 chars
    fp = get_fingerprint(armored_public)
    assert len(fp) == 49, f"Unexpected length {len(fp)}: {fp!r}"


def test_get_fingerprint_only_hex_and_spaces(armored_public: str) -> None:
    fp = get_fingerprint(armored_public)
    assert all(c in "0123456789ABCDEF " for c in fp.upper())


def test_get_fingerprint_is_uppercase(armored_public: str) -> None:
    fp = get_fingerprint(armored_public)
    assert fp == fp.upper()


def test_get_fingerprint_is_deterministic(armored_public: str) -> None:
    assert get_fingerprint(armored_public) == get_fingerprint(armored_public)


def test_get_fingerprint_matches_loaded_key(armored_public: str) -> None:
    """Fingerprint must match the one pgpy computes from the loaded key."""
    key = load_public_key(armored_public)
    raw = str(key.fingerprint).upper()
    expected = " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))
    assert get_fingerprint(armored_public) == expected
