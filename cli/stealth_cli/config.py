"""Configuration and key persistence (platformdirs-based).

Directory layout (example on macOS):
    ~/Library/Application Support/stealth-message/
    ├── config.json          ← alias and settings
    └── keys/
        ├── private.asc      ← ASCII-armored private key  (mode 0600)
        └── public.asc       ← ASCII-armored public key   (mode 0644)

The private key file is stored with permissions 0600 so only the owning
user can read it. The passphrase is NEVER persisted anywhere on disk.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

APP_NAME = "stealth-message"


# --------------------------------------------------------------------------- #
# Paths                                                                         #
# --------------------------------------------------------------------------- #


def _config_dir() -> Path:
    return Path(user_config_dir(APP_NAME))


def _keys_dir() -> Path:
    return _config_dir() / "keys"


def config_file() -> Path:
    return _config_dir() / "config.json"


def private_key_file() -> Path:
    return _keys_dir() / "private.asc"


def public_key_file() -> Path:
    return _keys_dir() / "public.asc"


# --------------------------------------------------------------------------- #
# First-use detection                                                           #
# --------------------------------------------------------------------------- #


def is_first_use() -> bool:
    """Return True if no saved keypair exists yet."""
    return not (private_key_file().exists() and public_key_file().exists())


# --------------------------------------------------------------------------- #
# Persistence                                                                   #
# --------------------------------------------------------------------------- #


def save_keypair(
    armored_private: str,
    armored_public: str,
    alias: str,
) -> None:
    """Persist the PGP keypair and alias to disk.

    The private key is written with mode 0600 (owner read/write only).

    Args:
        armored_private: ASCII-armored PGP private key block.
        armored_public:  ASCII-armored PGP public key block.
        alias:           Human-readable name stored in config.json.
    """
    _config_dir().mkdir(parents=True, exist_ok=True)
    _keys_dir().mkdir(parents=True, exist_ok=True)

    # Write private key — restrictive permissions.
    priv_path = private_key_file()
    priv_path.write_text(armored_private, encoding="utf-8")
    priv_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

    # Write public key — readable by owner.
    pub_path = public_key_file()
    pub_path.write_text(armored_public, encoding="utf-8")
    pub_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

    # Write config.
    cfg = {"alias": alias}
    config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def load_alias() -> Optional[str]:
    """Load the stored alias from config.json, or None if not found."""
    path = config_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("alias", "")) or None
    except (json.JSONDecodeError, OSError):
        return None


def load_armored_private() -> str:
    """Read the ASCII-armored private key from disk.

    Raises:
        FileNotFoundError: If the key file does not exist (first use).
        OSError: On permission or I/O errors.
    """
    return private_key_file().read_text(encoding="utf-8")


def load_armored_public() -> str:
    """Read the ASCII-armored public key from disk."""
    return public_key_file().read_text(encoding="utf-8")
