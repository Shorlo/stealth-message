import Foundation
import ObjectivePGP

/// Swift actor wrapping ObjectivePGP for all crypto operations.
///
/// This is the **only** file that imports ObjectivePGP. No Objective-C API
/// leaks past this boundary — all inputs and outputs are Swift native types
/// (`String`, `Data`, `throws`).
///
/// Mirrors the Python reference implementation in `cli/stealth_cli/crypto/`:
/// - `keys.py`     → `generateKeypair`, `validatePassphrase`, `fingerprint`
/// - `messages.py` → `encrypt`, `decrypt`
///
/// Wire encoding (protocol.md §10):
///   plaintext → sign-then-encrypt → ASCII-armor → Base64 URL-safe → payload
actor PGPKeyManager {

    // MARK: - Key generation

    /// Generates a passphrase-protected RSA-4096 keypair.
    ///
    /// - Returns: `(armoredPrivate, armoredPublic)` ASCII-armored PGP blocks.
    func generateKeypair(
        alias: String,
        passphrase: String
    ) throws -> (armoredPrivate: String, armoredPublic: String) {
        let generator = KeyGenerator()
        generator.keyBitsLength = 4096
        // ObjectivePGP embeds the UID as "Name <>" — alias is the name component.
        let key = generator.generate(for: "\(alias) <>", passphrase: passphrase)

        let pubData  = try key.export(keyType: .public)
        let secData  = try key.export(keyType: .secret)

        let armoredPubData = Armor.armored(pubData,  as: .publicKey)
        let armoredSecData = Armor.armored(secData, as: .secretKey)

        guard
            let armoredPublic  = String(data: armoredPubData,  encoding: .utf8),
            let armoredPrivate = String(data: armoredSecData, encoding: .utf8)
        else {
            throw CryptoError.encodingFailed
        }
        return (armoredPrivate: armoredPrivate, armoredPublic: armoredPublic)
    }

    // MARK: - Passphrase validation

    /// Validates that `passphrase` unlocks `armoredPrivate`.
    ///
    /// Attempts a detached sign on a dummy payload; throws if the passphrase
    /// is wrong or the key cannot be parsed.
    func validatePassphrase(_ passphrase: String, armoredPrivate: String) throws {
        let keys = try readKeys(from: armoredPrivate)
        guard !keys.isEmpty else {
            throw CryptoError.invalidKey("No key found in armored block")
        }
        let probe = Data("passphrase-check".utf8)
        _ = try ObjectivePGP.sign(
            probe,
            detached: true,
            using: keys,
            passphraseForKey: { _ in passphrase }
        )
    }

    // MARK: - Fingerprint

    /// Returns the public-key fingerprint formatted as 40 uppercase hex chars
    /// in groups of 4 separated by spaces.
    ///
    /// Example: `"A1B2 C3D4 E5F6 7890 ABCD EF12 3456 7890 ABCD EF12"`
    func fingerprint(armoredPublic: String) throws -> String {
        let keys = try readKeys(from: armoredPublic)
        guard let key = keys.first,
              let fp  = key.publicKey?.fingerprint
        else {
            throw CryptoError.invalidKey("Cannot read fingerprint from key")
        }
        let hex = fp.hashedData.map { String(format: "%02X", $0) }.joined()
        return stride(from: 0, to: hex.count, by: 4).map { i -> String in
            let start = hex.index(hex.startIndex, offsetBy: i)
            let end   = hex.index(start, offsetBy: min(4, hex.count - i))
            return String(hex[start..<end])
        }.joined(separator: " ")
    }

    // MARK: - Encrypt (sign-then-encrypt)

    /// Encrypts and signs `plaintext` in a single pass.
    ///
    /// Pipeline (protocol.md §4):
    ///   plaintext → sign with sender privkey → encrypt with recipient pubkey
    ///   → ASCII-armor → Base64 URL-safe encode → payload string
    ///
    /// - Parameters:
    ///   - plaintext: UTF-8 text to protect.
    ///   - recipientArmoredPubkey: Recipient's ASCII-armored public key.
    ///   - senderArmoredPrivkey:   Sender's ASCII-armored private key (passphrase-protected).
    ///   - passphrase:             Sender's passphrase (held in memory only).
    /// - Returns: Base64 URL-safe payload string (the `"payload"` JSON field).
    func encrypt(
        plaintext: String,
        recipientArmoredPubkey: String,
        senderArmoredPrivkey: String,
        passphrase: String
    ) throws -> String {
        guard let plaintextData = plaintext.data(using: .utf8) else {
            throw CryptoError.encodingFailed
        }

        let recipientKeys = try readKeys(from: recipientArmoredPubkey)
        let senderKeys    = try readKeys(from: senderArmoredPrivkey)

        // ObjectivePGP signs with the private key(s) in `keys` and encrypts
        // for all public keys in `keys`. Passing both ensures sign + encrypt.
        let encryptedData = try ObjectivePGP.encrypt(
            plaintextData,
            addSignature: true,
            using: recipientKeys + senderKeys,
            passphraseForKey: { _ in passphrase }
        )

        let armoredData = Armor.armored(encryptedData, as: .message)
        guard let armoredStr = String(data: armoredData, encoding: .utf8) else {
            throw CryptoError.encodingFailed
        }

        // base64url(ascii_armor_utf8_bytes) — identical to the Python reference:
        //   base64.urlsafe_b64encode(armored.encode("utf-8")).decode("ascii")
        return Data(armoredStr.utf8)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .trimmingCharacters(in: CharacterSet(charactersIn: "="))
    }

    // MARK: - Decrypt (decrypt-then-verify)

    /// Decrypts `payload` and verifies the sender's signature.
    ///
    /// Pipeline (protocol.md §4):
    ///   Base64 URL-safe decode → ASCII-armor → decrypt with recipient privkey
    ///   → verify signature with sender pubkey → plaintext
    ///
    /// - Throws: `CryptoError.signatureInvalid` if the signature cannot be
    ///   verified. The caller **must not** display plaintext in that case.
    func decrypt(
        payload: String,
        recipientArmoredPrivkey: String,
        senderArmoredPubkey: String,
        passphrase: String
    ) throws -> String {
        // 1. Base64 URL-safe decode → bytes of the ASCII-armored message.
        let base64Standard = payload
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = base64Standard + String(repeating: "=", count: (4 - base64Standard.count % 4) % 4)
        guard let armoredBytes = Data(base64Encoded: padded),
              let armoredStr   = String(data: armoredBytes, encoding: .utf8)
        else {
            throw CryptoError.decryptionFailed("Invalid base64url payload")
        }

        let recipientKeys = try readKeys(from: recipientArmoredPrivkey)
        let senderKeys    = try readKeys(from: senderArmoredPubkey)

        do {
            let decryptedData = try ObjectivePGP.decrypt(
                Data(armoredStr.utf8),
                andVerifySignature: true,
                using: recipientKeys + senderKeys,
                passphraseForKey: { _ in passphrase }
            )
            guard let plaintext = String(data: decryptedData, encoding: .utf8) else {
                throw CryptoError.decryptionFailed("Decrypted content is not valid UTF-8")
            }
            return plaintext
        } catch CryptoError.signatureInvalid {
            throw CryptoError.signatureInvalid
        } catch {
            // Map ObjectivePGP signature errors to CryptoError.signatureInvalid.
            // protocol.md §4: invalid signatures must be discarded, never displayed.
            let desc = error.localizedDescription.lowercased()
            if desc.contains("signature") || desc.contains("verif") || desc.contains("signed") {
                throw CryptoError.signatureInvalid
            }
            throw CryptoError.decryptionFailed(error.localizedDescription)
        }
    }

    // MARK: - Private helpers

    private func readKeys(from armored: String) throws -> [Key] {
        guard let data = armored.data(using: .utf8) else {
            throw CryptoError.invalidKey("Cannot encode armored string as UTF-8")
        }
        return try ObjectivePGP.readKeys(from: data)
    }
}
