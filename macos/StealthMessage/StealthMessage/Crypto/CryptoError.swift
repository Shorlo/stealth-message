import Foundation

/// Errors produced by the crypto layer.
///
/// `signatureInvalid` maps directly to protocol.md §4:
/// "If the signature is not valid, discard the message."
/// Callers must never display plaintext when this error is thrown.
enum CryptoError: Error, LocalizedError, Equatable {
    case signatureInvalid
    case decryptionFailed(String)
    case keyGenerationFailed(String)
    case invalidKey(String)
    case encodingFailed

    var errorDescription: String? {
        switch self {
        case .signatureInvalid:
            return "PGP signature is invalid — message discarded (protocol.md §4)"
        case .decryptionFailed(let reason):
            return "Decryption failed: \(reason)"
        case .keyGenerationFailed(let reason):
            return "Key generation failed: \(reason)"
        case .invalidKey(let reason):
            return "Invalid key: \(reason)"
        case .encodingFailed:
            return "Encoding failed"
        }
    }
}
