import Foundation
import Security

/// Read/write ASCII-armored PGP keys to the macOS Keychain.
///
/// Keys are stored as generic passwords under the "com.stealth-message" service.
/// Access is restricted to `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` —
/// they never leave the device and are unavailable when the screen is locked.
enum KeychainStore {

    private static let service = "com.stealth-message"

    // MARK: - Write

    /// Saves (or replaces) a string value in the Keychain.
    static func save(_ value: String, account: String) throws {
        guard let data = value.data(using: .utf8) else {
            throw CryptoError.encodingFailed
        }

        // Remove any existing item first to avoid errSecDuplicateItem.
        let deleteQuery: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        SecItemDelete(deleteQuery as CFDictionary)

        let addQuery: [CFString: Any] = [
            kSecClass:                   kSecClassGenericPassword,
            kSecAttrService:             service,
            kSecAttrAccount:             account,
            kSecValueData:               data,
            kSecAttrAccessible:          kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let status = SecItemAdd(addQuery as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw CryptoError.invalidKey("Keychain write failed (OSStatus \(status))")
        }
    }

    // MARK: - Read

    /// Loads a previously saved string value from the Keychain.
    static func load(account: String) throws -> String {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData:  true,
            kSecMatchLimit:  kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8)
        else {
            throw CryptoError.invalidKey("Keychain read failed (OSStatus \(status))")
        }
        return value
    }

    // MARK: - Existence check

    /// Returns `true` if a value exists for the given account.
    static func exists(account: String) -> Bool {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData:  false,
        ]
        return SecItemCopyMatching(query as CFDictionary, nil) == errSecSuccess
    }

    // MARK: - Delete

    /// Removes a stored value. A no-op if the account does not exist.
    static func delete(account: String) {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
