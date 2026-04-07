import SwiftUI
import AppKit

struct HubView: View {
    var app: AppViewModel
    @State private var showResetConfirm = false

    var body: some View {
        VStack(spacing: 36) {
            // Identity card
            VStack(spacing: 10) {
                Image(systemName: "person.badge.key.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.tint)

                Text(app.alias)
                    .font(.title.bold())

                VStack(spacing: 4) {
                    Text("Your fingerprint — verify with peers out-of-band")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        Text(app.fingerprint)
                            .font(.system(.caption, design: .monospaced))
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                            .textSelection(.enabled)
                        Button {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(app.fingerprint, forType: .string)
                        } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .buttonStyle(.borderless)
                        .help("Copy fingerprint")
                    }
                }
            }

            Divider().frame(maxWidth: 400)

            // Action buttons
            HStack(spacing: 32) {
                VStack(spacing: 8) {
                    Button {
                        app.goHosting()
                    } label: {
                        modeLabel(
                            icon: "server.rack",
                            title: app.hostViewModel?.isRunning == true ? "Resume Server" : "Host Server",
                            badge: app.hostViewModel?.isRunning == true
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    if app.hostViewModel?.isRunning == true {
                        Text("Server running · \(app.hostViewModel?.peers.count ?? 0) peer(s)")
                            .font(.caption)
                            .foregroundStyle(.green)
                    } else {
                        Text("Start a chat server\nfor others to join")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                }

                VStack(spacing: 8) {
                    Button {
                        app.goJoining()
                    } label: {
                        modeLabel(
                            icon: "network",
                            title: app.clientViewModel?.isConnected == true ? "Resume Chat" : "Join Server",
                            badge: app.clientViewModel?.isConnected == true
                        )
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)

                    if app.clientViewModel?.isConnected == true {
                        Text("Connected · \(app.clientViewModel?.selectedRoom ?? "")")
                            .font(.caption)
                            .foregroundStyle(.green)
                    } else {
                        Text("Connect to an existing\nchat server")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                }
            }
        }
        .padding(40)
        .frame(minWidth: 540, minHeight: 440)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Reset identity…") { showResetConfirm = true }
                    .foregroundStyle(.secondary)
                    .font(.callout)
            }
        }
        .confirmationDialog(
            "Reset identity?",
            isPresented: $showResetConfirm,
            titleVisibility: .visible
        ) {
            Button("Delete keypair and start over", role: .destructive) {
                Task { await app.resetIdentity() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This permanently deletes your private key and fingerprint. Any peer who had your old fingerprint must re-verify the new one.")
        }
    }

    @ViewBuilder
    private func modeLabel(icon: String, title: String, badge: Bool = false) -> some View {
        VStack(spacing: 10) {
            ZStack(alignment: .topTrailing) {
                Image(systemName: icon)
                    .font(.system(size: 32))
                if badge {
                    Circle()
                        .fill(.green)
                        .frame(width: 10, height: 10)
                        .offset(x: 4, y: -4)
                }
            }
            Text(title)
                .font(.headline)
        }
        .frame(width: 160, height: 90)
    }
}
