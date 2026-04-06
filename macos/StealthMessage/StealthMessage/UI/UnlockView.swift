import SwiftUI

// MARK: - ViewModel

@Observable
final class UnlockViewModel {
    var passphrase: String = ""
    var isUnlocking: Bool = false
    var errorMessage: String?

    private let crypto = PGPKeyManager()

    var storedAlias: String {
        (try? KeychainStore.load(account: "alias")) ?? "Unknown"
    }

    func unlock(app: AppViewModel) async {
        guard !passphrase.isEmpty else { return }
        isUnlocking = true
        errorMessage = nil
        defer { isUnlocking = false }

        do {
            let privkey = try KeychainStore.load(account: "privkey")
            let pubkey  = try KeychainStore.load(account: "pubkey")
            let alias   = try KeychainStore.load(account: "alias")

            // Validates passphrase by attempting a dummy sign operation.
            try await crypto.validatePassphrase(passphrase, armoredPrivate: privkey)

            let fp = try await crypto.fingerprint(armoredPublic: pubkey)

            app.unlockComplete(
                passphrase: passphrase,
                privkey: privkey,
                pubkey: pubkey,
                alias: alias,
                fingerprint: fp
            )
        } catch {
            errorMessage = "Incorrect passphrase."
            passphrase = ""
        }
    }
}

// MARK: - View

struct UnlockView: View {
    @State private var vm = UnlockViewModel()
    var app: AppViewModel

    var body: some View {
        VStack(spacing: 28) {
            Image(systemName: "lock.shield.fill")
                .font(.system(size: 52))
                .foregroundStyle(.tint)

            VStack(spacing: 6) {
                Text("Welcome back")
                    .font(.title2)
                    .foregroundStyle(.secondary)
                Text(vm.storedAlias)
                    .font(.largeTitle.bold())
            }

            VStack(spacing: 12) {
                SecureField("Passphrase", text: $vm.passphrase)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 300)
                    .onSubmit { Task { await vm.unlock(app: app) } }

                if let err = vm.errorMessage {
                    Text(err)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }

            if vm.isUnlocking {
                ProgressView("Unlocking…")
            } else {
                Button("Unlock") {
                    Task { await vm.unlock(app: app) }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(vm.passphrase.isEmpty)
            }
        }
        .padding(40)
        .frame(minWidth: 400, minHeight: 360)
    }
}
