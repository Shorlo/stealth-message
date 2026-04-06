import SwiftUI

// MARK: - Shared data types

/// A single chat message displayed in any chat view.
struct ChatMessage: Identifiable, Sendable {
    let id = UUID()
    let sender: String
    let text: String
    let timestamp: Date
    let isOwn: Bool
}

/// A peer currently connected to the host server.
struct ConnectedPeer: Identifiable, Sendable {
    let id = UUID()
    let alias: String
    let fingerprint: String
    let roomID: String
}

/// A peer waiting for host approval in a group room.
struct JoinRequest: Identifiable, Sendable {
    let id = UUID()
    let alias: String
    let fingerprint: String
    let roomID: String
}

// MARK: - App navigation

enum AppScreen {
    case setup      // First launch: generate keypair
    case unlock     // Returning user: enter passphrase
    case hub        // Identity shown, choose host or join
    case hosting    // Running a StealthServer
    case joining    // Connected as a StealthClient
}

// MARK: - AppViewModel

/// Top-level state machine. Holds identity after unlock.
/// Passphrase is held in memory only — never written to disk.
@Observable
final class AppViewModel {
    private(set) var screen: AppScreen
    private(set) var alias: String = ""
    private(set) var armoredPrivkey: String = ""
    private(set) var armoredPubkey: String = ""
    private(set) var fingerprint: String = ""
    private(set) var passphrase: String = ""

    init() {
        if KeychainStore.exists(account: "alias") &&
           KeychainStore.exists(account: "privkey") &&
           KeychainStore.exists(account: "pubkey") {
            screen = .unlock
        } else {
            screen = .setup
        }
    }

    /// Called by SetupView after successful key generation + Keychain save.
    func setupComplete(
        alias: String,
        privkey: String,
        pubkey: String,
        fingerprint: String,
        passphrase: String
    ) {
        self.alias          = alias
        self.armoredPrivkey = privkey
        self.armoredPubkey  = pubkey
        self.fingerprint    = fingerprint
        self.passphrase     = passphrase
        screen = .hub
    }

    /// Called by UnlockView after passphrase is verified.
    func unlockComplete(
        passphrase: String,
        privkey: String,
        pubkey: String,
        alias: String,
        fingerprint: String
    ) {
        self.passphrase     = passphrase
        self.armoredPrivkey = privkey
        self.armoredPubkey  = pubkey
        self.alias          = alias
        self.fingerprint    = fingerprint
        screen = .hub
    }

    func returnToHub() { screen = .hub }
    func goHosting()   { screen = .hosting }
    func goJoining()   { screen = .joining }
}

// MARK: - Shared view component

/// Chat bubble used by both HostView and JoinView.
struct MessageBubble: View {
    let message: ChatMessage

    /// System messages (sender == "•") are rendered as italic status lines.
    private var isSystem: Bool { message.sender == "•" }

    @ViewBuilder
    private var messageBubbleText: some View {
        if isSystem {
            Text(message.text)
                .italic()
                .font(.caption)
                .foregroundStyle(Color.secondary)
        } else if message.isOwn {
            Text(message.text)
                .padding(8)
                .background(Color.accentColor.opacity(0.85), in: RoundedRectangle(cornerRadius: 8))
                .foregroundStyle(Color.white)
        } else {
            Text(message.text)
                .padding(8)
                .background(Color.secondary.opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
                .foregroundStyle(Color.primary)
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if message.isOwn { Spacer(minLength: 60) }

            VStack(alignment: message.isOwn ? .trailing : .leading, spacing: 2) {
                if !message.isOwn && !isSystem {
                    Text(message.sender)
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                }
                messageBubbleText
                if !isSystem {
                    Text(message.timestamp, style: .time)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            if !message.isOwn { Spacer(minLength: 60) }
        }
    }
}
