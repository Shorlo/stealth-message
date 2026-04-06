import SwiftUI

struct HubView: View {
    var app: AppViewModel

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
                    Text(app.fingerprint)
                        .font(.system(.caption, design: .monospaced))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                        .textSelection(.enabled)
                }
            }

            Divider().frame(maxWidth: 400)

            // Action buttons
            HStack(spacing: 32) {
                VStack(spacing: 8) {
                    Button {
                        app.goHosting()
                    } label: {
                        modeLabel(icon: "server.rack", title: "Host Server")
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Text("Start a chat server\nfor others to join")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                VStack(spacing: 8) {
                    Button {
                        app.goJoining()
                    } label: {
                        modeLabel(icon: "network", title: "Join Server")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)

                    Text("Connect to an existing\nchat server")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }
        }
        .padding(40)
        .frame(minWidth: 540, minHeight: 440)
    }

    @ViewBuilder
    private func modeLabel(icon: String, title: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 32))
            Text(title)
                .font(.headline)
        }
        .frame(width: 150, height: 90)
    }
}
