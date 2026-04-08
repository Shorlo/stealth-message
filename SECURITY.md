# Security policy

## Scope

This document covers the security policy of `stealth-message` across all
sub-projects: CLI (Python), macOS (Swift), Windows (C#), and Linux (Python/GTK4).

---

## Supported versions

| Version    | Security support |
|------------|------------------|
| `main`     | Active           |
| < 1.0.0    | No support (pre-release) |

---

## Reporting vulnerabilities

**Do not open public issues to report security vulnerabilities.**

To report a vulnerability, contact privately:

- **Email:** [info@syberiancode.com](mailto:info@syberiancode.com)
- **Subject:** `[SECURITY] stealth-message — brief description`

A confirmation of receipt will be sent within **72 hours**.

### What to include in the report

1. Description of the problem and its potential impact.
2. Steps to reproduce it (PoC if possible).
3. Affected version or commit.
4. Possible mitigation or proposed fix (optional).

### Responsible disclosure process

1. Report is received privately.
2. Vulnerability is confirmed and impact assessed.
3. Fix is developed and tested.
4. Fix is published together with an advisory.
5. Researcher is credited (unless anonymity is requested).

---

## Project security principles

### Private keys
- PGP private keys **never leave the user's device**.
- They are stored in the OS secure store:
  - macOS: Keychain Services (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`)
  - Windows: DPAPI (`ProtectedData.Protect`, scope `CurrentUser`)
  - Linux: libsecret (SecretService DBus)
  - CLI: `0600` file in the configuration directory
- Passphrases exist only in memory during the active session. **Never on disk.**

### Message encryption
- All messages are encrypted with the recipient's public key before sending.
- All messages are signed with the sender's private key.
- Messages with an invalid signature are discarded and the user is notified.
- Transport is WebSocket; WSS (TLS) is recommended on untrusted networks.

### Identity verification
- There is no centralised PKI or key directory.
- Users **must verify key fingerprints over an independent channel**
  (in person, by phone) before trusting a conversation.
- The UI must always display the full fingerprint (40 hex chars in groups of 4).

### Sensitive information in code
- No sensitive field (passphrase, private key, test fingerprint) may appear in
  logs, console output, clipboard, or test configuration files.
- Passphrases in the UI always use password fields (`SecureField`, `PasswordBox`,
  `Gtk.Entry.set_visibility(False)`, `prompt_toolkit` with `is_password=True`).

### Dependencies
- Minimise third-party dependencies, especially in crypto modules.
- Cryptography dependencies must be established and audited libraries.
- Review dependencies for new vulnerabilities (CVEs) before each release.

---

## Threats outside current scope

The following threats are outside the scope of the current version (v0.x):

- **Forward secrecy:** messages encrypted with a compromised key can be decrypted
  retroactively. A future version (v2) will introduce ephemeral session keys.
- **NAT traversal / relay:** the direct connection requires the host to be reachable.
  There is no TURN or relay support in this version.
- **Network anonymity:** the IP addresses of participants are visible to each other.
  There is no Tor or anonymity network integration.
- **Traffic analysis protection:** network metadata (size, timing) is not obfuscated
  in this version.
