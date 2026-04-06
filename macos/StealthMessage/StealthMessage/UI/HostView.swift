import SwiftUI
import Darwin

// MARK: - ViewModel

/// All state and logic for the host (server) side.
/// `@unchecked Sendable` is safe because all mutations happen on @MainActor.
@Observable
final class HostViewModel: @unchecked Sendable {

    // MARK: Configuration (pre-start)
    var portText: String = "8765"
    var newRoomName: String = ""
    var newGroupRoomName: String = ""
    var oneToOneRooms: [String] = ["default"]
    var groupRooms: [String] = []

    // MARK: Running state
    var isRunning: Bool = false
    var serverPort: UInt16 = 0
    var localIP: String = ""
    var errorMessage: String?

    // MARK: Live data
    var peers: [ConnectedPeer] = []
    var pendingRequests: [JoinRequest] = []
    var messages: [ChatMessage] = []
    var inputText: String = ""
    var sendToAlias: String = ""  // "" = broadcast to all

    // MARK: Private
    private var server: StealthServer?
    private let alias: String
    private let armoredPrivkey: String
    private let armoredPubkey: String
    private let passphrase: String

    init(app: AppViewModel) {
        alias          = app.alias
        armoredPrivkey = app.armoredPrivkey
        armoredPubkey  = app.armoredPubkey
        passphrase     = app.passphrase
    }

    var serverURL: String { "ws://\(localIP):\(serverPort)" }

    var canStart: Bool {
        !isRunning && (!oneToOneRooms.isEmpty || !groupRooms.isEmpty)
    }

    // MARK: - Room management

    func addRoom() {
        let name = newRoomName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !oneToOneRooms.contains(name), !groupRooms.contains(name) else { return }
        oneToOneRooms.append(name)
        newRoomName = ""
    }

    func removeRoom(_ name: String) {
        oneToOneRooms.removeAll { $0 == name }
    }

    func addGroupRoom() {
        let name = newGroupRoomName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !groupRooms.contains(name), !oneToOneRooms.contains(name) else { return }
        groupRooms.append(name)
        newGroupRoomName = ""
    }

    func removeGroupRoom(_ name: String) {
        groupRooms.removeAll { $0 == name }
    }

    // MARK: - Server lifecycle

    func startServer() async {
        errorMessage = nil
        let portNum = UInt16(portText) ?? 8765

        let srv = StealthServer(
            alias: alias,
            armoredPrivkey: armoredPrivkey,
            armoredPubkey: armoredPubkey,
            passphrase: passphrase,
            rooms: oneToOneRooms.isEmpty ? nil : oneToOneRooms,
            groupRooms: groupRooms.isEmpty ? nil : groupRooms
        )

        // Wire callbacks via the single-hop configure() method.
        await srv.configure(
            onPeerConnected: { [weak self] peerAlias, fp, roomID in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.peers.append(ConnectedPeer(alias: peerAlias, fingerprint: fp, roomID: roomID))
                    self.systemMessage("\(peerAlias) joined \(roomID)")
                }
            },
            onMessage: { [weak self] peerAlias, text, roomID in
                Task { @MainActor [weak self] in
                    self?.messages.append(ChatMessage(
                        sender: peerAlias, text: text, timestamp: Date(), isOwn: false
                    ))
                }
            },
            onPeerDisconnected: { [weak self] peerAlias, roomID in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.peers.removeAll { $0.alias == peerAlias && $0.roomID == roomID }
                    self.systemMessage("\(peerAlias) left \(roomID)")
                }
            },
            onJoinRequest: { [weak self] peerAlias, fp, roomID in
                Task { @MainActor [weak self] in
                    self?.pendingRequests.append(
                        JoinRequest(alias: peerAlias, fingerprint: fp, roomID: roomID)
                    )
                }
            }
        )

        do {
            let port = try await srv.start(on: portNum)
            server    = srv
            serverPort = port
            localIP   = hostLocalIPAddress()
            isRunning = true
        } catch {
            errorMessage = "Could not start server: \(error.localizedDescription)"
        }
    }

    func stopServer() async {
        await server?.stop()
        server    = nil
        isRunning = false
        peers.removeAll()
        pendingRequests.removeAll()
        systemMessage("Server stopped")
    }

    // MARK: - Join approval

    func approve(_ request: JoinRequest) async {
        do {
            try await server?.approveJoin(alias: request.alias)
            pendingRequests.removeAll { $0.id == request.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deny(_ request: JoinRequest) async {
        do {
            try await server?.denyJoin(alias: request.alias)
            pendingRequests.removeAll { $0.id == request.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Messaging

    func sendMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, let srv = server else { return }
        inputText = ""

        do {
            if sendToAlias.isEmpty {
                await srv.broadcast(text)
            } else {
                try await srv.sendTo(alias: sendToAlias, plaintext: text)
            }
            messages.append(ChatMessage(sender: alias, text: text, timestamp: Date(), isOwn: true))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func systemMessage(_ text: String) {
        messages.append(ChatMessage(sender: "•", text: text, timestamp: Date(), isOwn: false))
    }
}

// MARK: - Local IP helper

/// Returns the first private-range IPv4 address (en0/en1), or 127.0.0.1.
nonisolated func hostLocalIPAddress() -> String {
    var address = "127.0.0.1"
    var ifaddr: UnsafeMutablePointer<ifaddrs>?
    guard getifaddrs(&ifaddr) == 0 else { return address }
    defer { freeifaddrs(ifaddr) }
    var ptr = ifaddr
    while let iface = ptr {
        let family = iface.pointee.ifa_addr.pointee.sa_family
        if family == UInt8(AF_INET) {
            let name = String(cString: iface.pointee.ifa_name)
            if name.hasPrefix("en") {
                var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                getnameinfo(
                    iface.pointee.ifa_addr,
                    socklen_t(iface.pointee.ifa_addr.pointee.sa_len),
                    &hostname, socklen_t(hostname.count),
                    nil, 0, NI_NUMERICHOST
                )
                let candidate = String(cString: hostname)
                if candidate.hasPrefix("192.") || candidate.hasPrefix("10.") || candidate.hasPrefix("172.") {
                    address = candidate
                    break
                }
            }
        }
        ptr = iface.pointee.ifa_next
    }
    return address
}

// MARK: - Root view

struct HostView: View {
    @State private var vm: HostViewModel
    var app: AppViewModel

    init(app: AppViewModel) {
        self.app = app
        _vm = State(initialValue: HostViewModel(app: app))
    }

    var body: some View {
        Group {
            if vm.isRunning {
                RunningServerView(vm: vm)
            } else {
                ServerConfigView(vm: vm)
            }
        }
        .navigationTitle(vm.isRunning ? "Server Running" : "Configure Server")
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button("← Hub") { app.returnToHub() }
            }
            ToolbarItem(placement: .primaryAction) {
                if vm.isRunning {
                    Button("Stop") {
                        Task { await vm.stopServer() }
                    }
                    .foregroundStyle(.red)
                } else {
                    Button("Start Server") {
                        Task { await vm.startServer() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!vm.canStart)
                }
            }
        }
    }
}

// MARK: - Configuration view (pre-start)

private struct ServerConfigView: View {
    @Bindable var vm: HostViewModel

    var body: some View {
        Form {
            Section("Connection") {
                HStack {
                    Text("Port")
                    Spacer()
                    TextField("8765", text: $vm.portText)
                        .multilineTextAlignment(.trailing)
                        .frame(maxWidth: 80)
                }
            }

            Section {
                ForEach(vm.oneToOneRooms, id: \.self) { room in
                    HStack {
                        Label(room, systemImage: "person.2")
                        Spacer()
                        if vm.oneToOneRooms.count > 1 {
                            Button("Remove") { vm.removeRoom(room) }
                                .foregroundStyle(.red)
                                .buttonStyle(.borderless)
                        }
                    }
                }
                HStack {
                    TextField("Add 1:1 room…", text: $vm.newRoomName)
                        .onSubmit { vm.addRoom() }
                    Button("Add") { vm.addRoom() }
                        .buttonStyle(.borderless)
                        .disabled(vm.newRoomName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } header: {
                Text("1:1 Rooms")
            } footer: {
                Text("Each 1:1 room allows exactly one peer.")
                    .font(.caption)
            }

            Section {
                ForEach(vm.groupRooms, id: \.self) { room in
                    HStack {
                        Label(room, systemImage: "person.3")
                        Spacer()
                        Button("Remove") { vm.removeGroupRoom(room) }
                            .foregroundStyle(.red)
                            .buttonStyle(.borderless)
                    }
                }
                HStack {
                    TextField("Add group room…", text: $vm.newGroupRoomName)
                        .onSubmit { vm.addGroupRoom() }
                    Button("Add") { vm.addGroupRoom() }
                        .buttonStyle(.borderless)
                        .disabled(vm.newGroupRoomName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } header: {
                Text("Group Rooms")
            } footer: {
                Text("Group rooms allow multiple peers. Each joiner requires your approval.")
                    .font(.caption)
            }

            if let err = vm.errorMessage {
                Section {
                    Text(err).foregroundStyle(.red)
                }
            }
        }
        .formStyle(.grouped)
        .frame(minWidth: 480, minHeight: 440)
    }
}

// MARK: - Running server view

private struct RunningServerView: View {
    @Bindable var vm: HostViewModel

    var body: some View {
        HSplitView {
            sidePanel
                .frame(minWidth: 240, idealWidth: 280, maxWidth: 360)
            chatPanel
        }
        .frame(minWidth: 640, minHeight: 440)
    }

    // MARK: Side panel

    private var sidePanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            serverInfoHeader
            Divider()
            peersSection
            if !vm.pendingRequests.isEmpty {
                Divider()
                pendingSection
            }
            Spacer()
        }
    }

    private var serverInfoHeader: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Circle().fill(.green).frame(width: 8, height: 8)
                Text("Running").font(.caption).foregroundStyle(.secondary)
            }
            Text(vm.serverURL)
                .font(.system(.callout, design: .monospaced))
                .textSelection(.enabled)
            Text("Share this address with peers")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding()
    }

    private var peersSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Connected (\(vm.peers.count))")
                .font(.caption.bold())
                .foregroundStyle(.secondary)
                .padding(.horizontal)
                .padding(.vertical, 6)

            if vm.peers.isEmpty {
                Text("No peers connected yet")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .padding(.horizontal)
            } else {
                ForEach(vm.peers) { peer in
                    PeerRowView(peer: peer)
                }
            }
        }
    }

    private var pendingSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Awaiting approval (\(vm.pendingRequests.count))")
                .font(.caption.bold())
                .foregroundStyle(.orange)
                .padding(.horizontal)
                .padding(.vertical, 6)

            ForEach(vm.pendingRequests) { req in
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(req.alias).font(.callout.bold())
                        Text(req.fingerprint)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Text("→ \(req.roomID)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(spacing: 4) {
                        Button("✓") { Task { await vm.approve(req) } }
                            .foregroundStyle(.green)
                        Button("✕") { Task { await vm.deny(req) } }
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.borderless)
                    .font(.headline)
                }
                .padding(.horizontal)
                .padding(.vertical, 4)
            }
        }
    }

    // MARK: Chat panel

    private var chatPanel: some View {
        VStack(spacing: 0) {
            messagesArea
            Divider()
            sendBar
            if let err = vm.errorMessage {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.horizontal)
                    .padding(.bottom, 4)
            }
        }
    }

    private var messagesArea: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(vm.messages) { msg in
                        MessageBubble(message: msg).id(msg.id)
                    }
                }
                .padding()
            }
            .onChange(of: vm.messages.count) { _, _ in
                if let last = vm.messages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var sendBar: some View {
        HStack(spacing: 8) {
            Picker("To", selection: $vm.sendToAlias) {
                Text("All peers").tag("")
                ForEach(vm.peers) { peer in
                    Text(peer.alias).tag(peer.alias)
                }
            }
            .labelsHidden()
            .frame(maxWidth: 130)

            TextField("Message…", text: $vm.inputText)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await vm.sendMessage() } }

            Button("Send") { Task { await vm.sendMessage() } }
                .disabled(
                    vm.inputText.trimmingCharacters(in: .whitespaces).isEmpty ||
                    vm.peers.isEmpty
                )
        }
        .padding(8)
    }
}

// MARK: - Peer row

private struct PeerRowView: View {
    let peer: ConnectedPeer

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(peer.alias).font(.callout.bold())
                Spacer()
                Text(peer.roomID)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.quaternary, in: Capsule())
            }
            Text(peer.fingerprint)
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .padding(.horizontal)
        .padding(.vertical, 4)
    }
}
