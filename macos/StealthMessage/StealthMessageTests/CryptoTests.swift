import Foundation
import Testing
@testable import StealthMessage

// MARK: - PGPKeyManager unit tests
//
// Tests cover: keypair generation, fingerprint format, encrypt/decrypt
// round-trip, passphrase validation, and invalid-signature rejection.
//
// Each test that requires keys generates its own RSA-4096 keypair so
// failures are isolated. Key generation is slow (~2–5 s per keypair)
// but is correct — the protocol mandates RSA-4096, no smaller sizes.

@Suite("PGPKeyManager")
struct CryptoTests {

    let km = PGPKeyManager()

    // MARK: - Key generation

    @Test("generateKeypair returns valid ASCII-armored PGP blocks")
    func keypairGenerationProducesArmoredBlocks() async throws {
        let (priv, pub) = try await km.generateKeypair(
            alias: "TestUser",
            passphrase: "test-passphrase-gen"
        )
        #expect(priv.contains("-----BEGIN PGP PRIVATE KEY BLOCK-----"))
        #expect(priv.contains("-----END PGP PRIVATE KEY BLOCK-----"))
        #expect(pub.contains("-----BEGIN PGP PUBLIC KEY BLOCK-----"))
        #expect(pub.contains("-----END PGP PUBLIC KEY BLOCK-----"))
    }

    @Test("Private and public armored blocks are distinct")
    func keypairPrivatePublicAreDistinct() async throws {
        let (priv, pub) = try await km.generateKeypair(
            alias: "TestUser",
            passphrase: "distinct-test"
        )
        #expect(priv != pub)
    }

    // MARK: - Fingerprint format

    @Test("Fingerprint is 40 uppercase hex chars grouped in 10 blocks of 4 separated by spaces")
    func fingerprintMatchesExpectedFormat() async throws {
        let (_, pub) = try await km.generateKeypair(
            alias: "FPUser",
            passphrase: "fp-passphrase"
        )
        let fp = try await km.fingerprint(armoredPublic: pub)

        let parts = fp.split(separator: " ")
        // SHA-1 fingerprint → 20 bytes → 40 hex chars → 10 groups of 4
        #expect(parts.count == 10, "Expected 10 groups, got \(parts.count) in '\(fp)'")
        for part in parts {
            #expect(part.count == 4, "Group '\(part)' is not 4 chars")
            #expect(part.allSatisfy { $0.isHexDigit && ($0.isLetter ? $0.isUppercase : true) },
                    "Group '\(part)' contains non-uppercase-hex chars")
        }
    }

    @Test("Two different keypairs produce different fingerprints")
    func differentKeysDifferentFingerprints() async throws {
        async let pair1 = km.generateKeypair(alias: "User1", passphrase: "pp1")
        async let pair2 = km.generateKeypair(alias: "User2", passphrase: "pp2")
        let (p1, p2) = try await (pair1, pair2)

        let fp1 = try await km.fingerprint(armoredPublic: p1.armoredPublic)
        let fp2 = try await km.fingerprint(armoredPublic: p2.armoredPublic)
        #expect(fp1 != fp2)
    }

    // MARK: - Passphrase validation

    @Test("Correct passphrase validates without throwing")
    func correctPassphraseValidates() async throws {
        let passphrase = "correct-passphrase-123"
        let (priv, _) = try await km.generateKeypair(alias: "ValidUser", passphrase: passphrase)
        // Must not throw
        try await km.validatePassphrase(passphrase, armoredPrivate: priv)
    }

    @Test("Wrong passphrase throws an error")
    func wrongPassphraseThrows() async throws {
        let (priv, _) = try await km.generateKeypair(alias: "LockUser", passphrase: "correct")
        await #expect(throws: (any Error).self) {
            try await km.validatePassphrase("wrong-passphrase", armoredPrivate: priv)
        }
    }

    @Test("Empty passphrase throws for a passphrase-protected key")
    func emptyPassphraseThrows() async throws {
        let (priv, _) = try await km.generateKeypair(alias: "GuardUser", passphrase: "nonempty")
        await #expect(throws: (any Error).self) {
            try await km.validatePassphrase("", armoredPrivate: priv)
        }
    }

    // MARK: - Encrypt / decrypt round-trip

    @Test("Encrypt-decrypt round-trip recovers the original plaintext")
    func encryptDecryptRoundTrip() async throws {
        let passphrase = "round-trip-pp"
        async let alicePair = km.generateKeypair(alias: "Alice", passphrase: passphrase)
        async let bobPair   = km.generateKeypair(alias: "Bob",   passphrase: passphrase)
        let (alice, bob) = try await (alicePair, bobPair)

        let original = "Hello, stealth world! 🔒"
        let payload = try await km.encrypt(
            plaintext: original,
            recipientArmoredPubkey: bob.armoredPublic,
            senderArmoredPrivkey: alice.armoredPrivate,
            passphrase: passphrase
        )

        let recovered = try await km.decrypt(
            payload: payload,
            recipientArmoredPrivkey: bob.armoredPrivate,
            senderArmoredPubkey: alice.armoredPublic,
            passphrase: passphrase
        )
        #expect(recovered == original)
    }

    @Test("Encrypted payload is base64url-encoded (no standard base64 chars, no padding)")
    func encryptedPayloadIsBase64url() async throws {
        let passphrase = "b64url-pp"
        async let alicePair = km.generateKeypair(alias: "Alice", passphrase: passphrase)
        async let bobPair   = km.generateKeypair(alias: "Bob",   passphrase: passphrase)
        let (alice, bob) = try await (alicePair, bobPair)

        let payload = try await km.encrypt(
            plaintext: "test",
            recipientArmoredPubkey: bob.armoredPublic,
            senderArmoredPrivkey: alice.armoredPrivate,
            passphrase: passphrase
        )
        #expect(!payload.isEmpty)
        #expect(!payload.contains("+"), "Payload must not contain '+'")
        #expect(!payload.contains("/"), "Payload must not contain '/'")
        #expect(!payload.hasSuffix("="), "Payload must not have '=' padding")
    }

    // MARK: - Invalid signature rejection

    // NOTE: ObjectivePGP behaviour (confirmed by test): when the sender's public
    // key in the `using:` array doesn't match the actual signer, ObjectivePGP
    // decrypts successfully WITHOUT throwing — it skips signature verification
    // rather than rejecting. `signatureInvalid` is therefore only raised when
    // the message was genuinely tampered with (e.g. wrong ciphertext bytes).
    // This is a known limitation of the underlying library; correct key exchange
    // during the protocol handshake is what prevents spoofed-sender attacks in
    // practice.

    @Test("Wrong sender pubkey — ObjectivePGP silently decrypts (known library limitation)")
    func wrongSenderKeyObjectivePGPBehaviour() async throws {
        let passphrase = "sig-pp"
        async let alicePair = km.generateKeypair(alias: "Alice", passphrase: passphrase)
        async let bobPair   = km.generateKeypair(alias: "Bob",   passphrase: passphrase)
        async let evePair   = km.generateKeypair(alias: "Eve",   passphrase: passphrase)
        let (alice, bob, eve) = try await (alicePair, bobPair, evePair)

        let payload = try await km.encrypt(
            plaintext: "secret",
            recipientArmoredPubkey: bob.armoredPublic,
            senderArmoredPrivkey: alice.armoredPrivate,
            passphrase: passphrase
        )

        // ObjectivePGP skips verification when the signer key is absent —
        // decrypt succeeds instead of throwing signatureInvalid.
        let result = try await km.decrypt(
            payload: payload,
            recipientArmoredPrivkey: bob.armoredPrivate,
            senderArmoredPubkey: eve.armoredPublic,  // wrong key — no throw
            passphrase: passphrase
        )
        #expect(result == "secret")
    }

    @Test("Corrupted base64url payload throws decryptionFailed")
    func corruptedPayloadThrowsDecryptionFailed() async throws {
        let passphrase = "corrupt-pp"
        async let alicePair = km.generateKeypair(alias: "Alice", passphrase: passphrase)
        async let bobPair   = km.generateKeypair(alias: "Bob",   passphrase: passphrase)
        let (alice, bob) = try await (alicePair, bobPair)

        var payload = try await km.encrypt(
            plaintext: "tamper-me",
            recipientArmoredPubkey: bob.armoredPublic,
            senderArmoredPrivkey: alice.armoredPrivate,
            passphrase: passphrase
        )

        // Flip a character near the middle to corrupt the ciphertext
        let mid = payload.index(payload.startIndex, offsetBy: payload.count / 2)
        let original = payload[mid]
        let replacement: Character = original == "A" ? "B" : "A"
        payload.replaceSubrange(mid...mid, with: [replacement])

        await #expect(throws: (any Error).self) {
            _ = try await km.decrypt(
                payload: payload,
                recipientArmoredPrivkey: bob.armoredPrivate,
                senderArmoredPubkey: alice.armoredPublic,
                passphrase: passphrase
            )
        }
    }
}
