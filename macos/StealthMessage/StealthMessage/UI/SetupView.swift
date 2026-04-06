import SwiftUI

// MARK: - ViewModel

@Observable
final class SetupViewModel {
    var alias: String = ""
    var passphrase: String = ""
    var confirmPassphrase: String = ""
    var isGenerating: Bool = false
    var generatedFingerprint: String = ""
    var errorMessage: String?

    // Stored after generation, used in proceedToApp.
    private var pendingPrivkey: String = ""
    private var pendingPubkey: String = ""

    private let crypto = PGPKeyManager()

    var canGenerate: Bool {
        !alias.trimmingCharacters(in: .whitespaces).isEmpty &&
        passphrase.count >= 8 &&
        passphrase == confirmPassphrase
    }

    /// Generates an RSA-4096 keypair and saves it to Keychain.
    func generate() async {
        isGenerating = true
        errorMessage = nil
        defer { isGenerating = false }

        let trimmedAlias = alias.trimmingCharacters(in: .whitespaces)
        do {
            let (priv, pub) = try await crypto.generateKeypair(
                alias: trimmedAlias, passphrase: passphrase
            )
            let fp = try await crypto.fingerprint(armoredPublic: pub)

            try KeychainStore.save(trimmedAlias, account: "alias")
            try KeychainStore.save(priv,         account: "privkey")
            try KeychainStore.save(pub,           account: "pubkey")

            pendingPrivkey         = priv
            pendingPubkey          = pub
            generatedFingerprint   = fp
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func proceedToApp(_ app: AppViewModel) {
        guard !generatedFingerprint.isEmpty else { return }
        app.setupComplete(
            alias: alias.trimmingCharacters(in: .whitespaces),
            privkey: pendingPrivkey,
            pubkey: pendingPubkey,
            fingerprint: generatedFingerprint,
            passphrase: passphrase
        )
    }
}

// MARK: - View

struct SetupView: View {
    @State private var vm = SetupViewModel()
    var app: AppViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                // Header
                VStack(spacing: 8) {
                    Image(systemName: "shield.lefthalf.filled")
                        .font(.system(size: 52))
                        .foregroundStyle(.tint)
                    Text("Stealth Message")
                        .font(.largeTitle.bold())
                    Text("Create your encrypted identity")
                        .foregroundStyle(.secondary)
                }

                if vm.generatedFingerprint.isEmpty {
                    formSection
                } else {
                    fingerprintSection
                }
            }
            .padding(40)
        }
        .frame(minWidth: 480, minHeight: 440)
    }

    // MARK: - Form

    private var formSection: some View {
        VStack(spacing: 20) {
            VStack(alignment: .leading, spacing: 12) {
                labeledField("Display name", hint: "Visible to peers") {
                    TextField("e.g. Alice", text: $vm.alias)
                }
                labeledField("Passphrase", hint: "Min. 8 characters") {
                    SecureField("Choose a strong passphrase", text: $vm.passphrase)
                }
                labeledField("Confirm passphrase", hint: passphraseMismatchHint) {
                    SecureField("Repeat passphrase", text: $vm.confirmPassphrase)
                }
            }

            if let err = vm.errorMessage {
                Text(err)
                    .foregroundStyle(.red)
                    .font(.caption)
                    .multilineTextAlignment(.center)
            }

            if vm.isGenerating {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Generating RSA-4096 key pair — this takes a moment…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Button("Generate Keys") {
                    Task { await vm.generate() }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!vm.canGenerate)
            }

            Text("Your private key is stored only in your macOS Keychain and never leaves this device.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Fingerprint confirmation

    private var fingerprintSection: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 52))
                .foregroundStyle(.green)

            Text("Keys generated successfully")
                .font(.title2.bold())

            VStack(spacing: 8) {
                Text("Your PGP fingerprint")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Text(vm.generatedFingerprint)
                    .font(.system(.body, design: .monospaced))
                    .multilineTextAlignment(.center)
                    .padding(12)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                    .textSelection(.enabled)
            }

            Text("Share this fingerprint with your peers so they can verify your identity out-of-band (voice call, in person, etc.).")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)

            Button("Continue to App") {
                vm.proceedToApp(app)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    // MARK: - Helpers

    private var passphraseMismatchHint: String {
        guard !vm.confirmPassphrase.isEmpty else { return "" }
        return vm.passphrase == vm.confirmPassphrase ? "✓ Match" : "✗ Mismatch"
    }

    @ViewBuilder
    private func labeledField<F: View>(
        _ label: String, hint: String, @ViewBuilder field: () -> F
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.caption.bold())
                if !hint.isEmpty {
                    Text(hint)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            field()
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 360)
        }
    }
}
