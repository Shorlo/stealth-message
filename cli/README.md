# stealth-message CLI

End-to-end encrypted PGP chat. No central server. No accounts. No content metadata.

## Installation

```bash
curl -fsSL https://syberiancode.com/stealth-message/install.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://syberiancode.com/stealth-message/install.ps1 | iex"
```

**Or install directly with pip:**
```bash
pip install stealth-message-cli
```

## Requirements

- Python 3.10, 3.11, or 3.12

## Usage

```bash
stealth-cli
```

## Security

- RSA-4096 keypair per user
- Sign-then-encrypt on send, decrypt-then-verify on receive
- Private key is passphrase-protected on disk
- Wire encoding: ASCII-armored PGP → Base64 URL-safe

## License

GPL-3.0. See [LICENSE](https://github.com/syberiancode/stealth-message/blob/main/LICENSE).
