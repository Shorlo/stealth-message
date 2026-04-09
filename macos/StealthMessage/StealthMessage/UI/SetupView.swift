import SwiftUI
import AppKit

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

    var aliasExceedsLimit: Bool {
        alias.trimmingCharacters(in: .whitespaces).count > 64
    }

    var canGenerate: Bool {
        let trimmed = alias.trimmingCharacters(in: .whitespaces)
        return !trimmed.isEmpty &&
               trimmed.count <= 64 &&
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
            VStack(spacing: 32) {
                // Header
                VStack(spacing: 10) {
                    Image(systemName: "shield.lefthalf.filled")
                        .font(.system(size: 52))
                        .foregroundStyle(.tint)
                    Text("Stealth Message")
                        .font(.largeTitle.bold())
                    Text("Create your encrypted identity")
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 8)

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
        VStack(alignment: .leading, spacing: 20) {

            // ── Display name ─────────────────────────────────────────────
            VStack(alignment: .leading, spacing: 6) {
                Text("Display name")
                    .font(.subheadline.weight(.medium))
                    .padding(.horizontal, 2)

                TextField("e.g. Alice", text: $vm.alias)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(Color(.controlBackgroundColor))
                            .shadow(color: .black.opacity(0.06), radius: 1, y: 1)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .strokeBorder(Color(.separatorColor), lineWidth: 0.5)
                    )

                Group {
                    if vm.aliasExceedsLimit {
                        Label("Alias must be 64 characters or fewer", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                    } else {
                        Text("Visible to peers you chat with.")
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.caption)
                .padding(.horizontal, 2)
            }

            // ── Passphrase ───────────────────────────────────────────────
            VStack(alignment: .leading, spacing: 6) {
                Text("Passphrase")
                    .font(.subheadline.weight(.medium))
                    .padding(.horizontal, 2)

                VStack(spacing: 0) {
                    SecureField("Minimum 8 characters", text: $vm.passphrase)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)

                    Divider()
                        .padding(.leading, 14)

                    SecureField("Confirm passphrase", text: $vm.confirmPassphrase)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                }
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color(.controlBackgroundColor))
                        .shadow(color: .black.opacity(0.06), radius: 1, y: 1)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(Color(.separatorColor), lineWidth: 0.5)
                )

                if !vm.confirmPassphrase.isEmpty {
                    Text(vm.passphrase == vm.confirmPassphrase
                         ? "✓ Passphrases match"
                         : "✗ Passphrases don't match")
                        .font(.caption)
                        .foregroundStyle(vm.passphrase == vm.confirmPassphrase ? Color.green : Color.red)
                        .padding(.horizontal, 2)
                }
            }

            // ── Error ────────────────────────────────────────────────────
            if let err = vm.errorMessage {
                Text(err)
                    .foregroundStyle(.red)
                    .font(.caption)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
            }

            // ── CTA ──────────────────────────────────────────────────────
            VStack(spacing: 12) {
                if vm.isGenerating {
                    VStack(spacing: 8) {
                        ProgressView()
                        Text("Generating RSA-4096 key pair — this takes a moment…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                } else {
                    Button("Generate Keys") {
                        Task { await vm.generate() }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(!vm.canGenerate)
                    .frame(maxWidth: .infinity)
                }

                Text("Your private key is stored only in your macOS Keychain and never leaves this device.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: 400)
        .frame(maxWidth: .infinity)
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
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    Text(vm.generatedFingerprint)
                        .font(.system(.body, design: .monospaced))
                        .multilineTextAlignment(.center)
                        .padding(12)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                        .textSelection(.enabled)
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(vm.generatedFingerprint, forType: .string)
                    } label: {
                        Image(systemName: "doc.on.doc")
                    }
                    .buttonStyle(.borderless)
                    .help("Copy fingerprint")
                }
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

}
