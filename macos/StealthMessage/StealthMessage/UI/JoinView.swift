import SwiftUI

// MARK: - ViewModel

/// All state and logic for the client (joiner) side.
/// `@unchecked Sendable` is safe because all mutations happen on @MainActor.
@Observable
final class ClientViewModel: @unchecked Sendable {

    // MARK: Connection setup
    var serverURLString: String = ""
    var isLoadingRooms: Bool = false
    var availableRooms: [WireRoomInfo] = []
    var isConnecting: Bool = false

    // MARK: Connected state
    var isConnected: Bool = false
    var isPending: Bool = false      // waiting for host approval
    var selectedRoom: String = ""
    var statusMessage: String = ""

    // MARK: Peer info
    var peerAlias: String?
    var peerFingerprint: String?
    var groupPeers: [WirePeerInfo] = []
    var groupRoomList: [String] = []

    // MARK: Chat
    var messages: [ChatMessage] = []
    var inputText: String = ""
    var errorMessage: String?

    // MARK: Private
    private var client: StealthClient?
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

    var canBrowse: Bool {
        !serverURLString.trimmingCharacters(in: .whitespaces).isEmpty && !isConnecting
    }

    // MARK: - URL helpers

    private func normalizedURL() -> URL? {
        var s = serverURLString.trimmingCharacters(in: .whitespaces)
        if !s.hasPrefix("ws://") && !s.hasPrefix("wss://") { s = "ws://" + s }
        return URL(string: s)
    }

    // MARK: - Room discovery

    func browseRooms() async {
        guard let url = normalizedURL() else {
            errorMessage = "Invalid server URL"
            return
        }
        isLoadingRooms = true
        errorMessage   = nil
        defer { isLoadingRooms = false }

        availableRooms = await StealthClient.queryRooms(url: url)
        if availableRooms.isEmpty {
            errorMessage = "No rooms found — check the URL or try again."
        }
    }

    // MARK: - Connect

    func connect(roomID: String) async {
        guard let url = normalizedURL() else {
            errorMessage = "Invalid server URL"
            return
        }
        isConnecting  = true
        isPending     = false
        errorMessage  = nil
        statusMessage = "Connecting…"
        defer { isConnecting = false }

        let cl = StealthClient(
            alias: alias,
            armoredPrivkey: armoredPrivkey,
            armoredPubkey: armoredPubkey,
            passphrase: passphrase
        )

        await cl.configure(
            onMessage: { [weak self] text, sender in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    let displaySender = sender ?? self.peerAlias ?? "Peer"
                    self.messages.append(ChatMessage(
                        sender: displaySender, text: text, timestamp: Date(), isOwn: false
                    ))
                }
            },
            onDisconnected: { [weak self] in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.isConnected  = false
                    self.statusMessage = "Disconnected"
                    self.systemMessage("Disconnected from server")
                }
            },
            onPending: { [weak self] in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.isPending     = true
                    self.statusMessage = "Waiting for host approval…"
                    self.systemMessage("Waiting for host to approve your join request…")
                }
            },
            onApproved: { [weak self] in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.isPending     = false
                    self.statusMessage = "Connected"
                    self.systemMessage("Approved — you are now in the room")
                }
            },
            onMove: { [weak self] newRoom in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.selectedRoom = newRoom
                    self.systemMessage("Moved to room: \(newRoom)")
                }
            },
            onRoomList: { [weak self] groups in
                Task { @MainActor [weak self] in
                    self?.groupRoomList = groups
                }
            },
            onPeerList: { [weak self] peers in
                Task { @MainActor [weak self] in
                    self?.groupPeers = peers
                }
            },
            onKicked: { [weak self] reason in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.isConnected  = false
                    self.errorMessage = "Kicked by host: \(reason)"
                    self.systemMessage("You were kicked by the host: \(reason)")
                }
            }
        )

        do {
            try await cl.connect(to: url, roomID: roomID)
            client           = cl
            selectedRoom     = roomID
            peerAlias        = await cl.peerAlias
            peerFingerprint  = await cl.peerFingerprint
            isConnected      = true
            statusMessage    = "Connected"
        } catch {
            errorMessage  = error.localizedDescription
            statusMessage = "Connection failed"
        }
    }

    // MARK: - Disconnect

    func disconnect() async {
        await client?.disconnect()
        client        = nil
        isConnected   = false
        isPending     = false
        statusMessage = ""
    }

    // MARK: - Switch room

    /// Cleanly disconnects from the current room and reconnects to `roomID`
    /// on the same server. Preserves chat history with a system message separator.
    func switchRoom(to roomID: String) async {
        guard roomID != selectedRoom, !isConnecting else { return }
        isConnecting  = true
        statusMessage = "Switching to \(roomID)…"

        await client?.disconnect()
        client          = nil
        isConnected     = false
        isPending       = false
        peerAlias       = nil
        peerFingerprint = nil
        groupPeers      = []

        systemMessage("──── Switching to room: \(roomID) ────")
        await connect(roomID: roomID)
    }

    // MARK: - Send

    func sendMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, let cl = client else { return }
        inputText = ""

        do {
            try await cl.send(text)
            messages.append(ChatMessage(sender: alias, text: text, timestamp: Date(), isOwn: true))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func systemMessage(_ text: String) {
        messages.append(ChatMessage(sender: "•", text: text, timestamp: Date(), isOwn: false))
    }
}

// MARK: - Root view

struct JoinView: View {
    @Bindable var vm: ClientViewModel
    var app: AppViewModel

    var body: some View {
        Group {
            if vm.isConnected {
                connectedView
            } else {
                connectView
            }
        }
        .navigationTitle(vm.isConnected ? "Chat — \(vm.selectedRoom)" : "Join Server")
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button("← Hub") {
                    Task {
                        await vm.disconnect()
                        app.returnToHub()
                    }
                }
            }
            if vm.isConnected {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        // Group rooms the server advertised
                        if !vm.groupRoomList.isEmpty {
                            Section("Switch Room") {
                                ForEach(vm.groupRoomList, id: \.self) { room in
                                    Button {
                                        Task { await vm.switchRoom(to: room) }
                                    } label: {
                                        if room == vm.selectedRoom {
                                            Label(room, systemImage: "checkmark")
                                        } else {
                                            Text(room)
                                        }
                                    }
                                    .disabled(room == vm.selectedRoom)
                                }
                                Divider()
                            }
                        }
                        Button("Browse all rooms…") {
                            Task { await vm.disconnect(); await vm.browseRooms() }
                        }
                        Divider()
                        Button("Disconnect", role: .destructive) {
                            Task { await vm.disconnect() }
                        }
                    } label: {
                        Label(vm.selectedRoom, systemImage: "door.right.hand.open")
                    }
                }
            }
        }
    }

    // MARK: - Connect view (not yet connected)

    private var connectView: some View {
        VStack(spacing: 0) {
            // URL bar
            HStack(spacing: 8) {
                TextField("ws://192.168.x.x:8765", text: $vm.serverURLString)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await vm.browseRooms() } }
                Button("Browse Rooms") {
                    Task { await vm.browseRooms() }
                }
                .disabled(!vm.canBrowse || vm.isLoadingRooms)
            }
            .padding()

            Divider()

            if vm.isLoadingRooms {
                Spacer()
                ProgressView("Loading rooms…")
                Spacer()
            } else if vm.isConnecting {
                Spacer()
                VStack(spacing: 12) {
                    ProgressView()
                    Text(vm.statusMessage)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            } else if !vm.availableRooms.isEmpty {
                roomsList
            } else {
                Spacer()
                VStack(spacing: 8) {
                    Image(systemName: "network.slash")
                        .font(.system(size: 36))
                        .foregroundStyle(.secondary)
                    Text("Enter the server address and tap Browse Rooms")
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                Spacer()
            }

            if let err = vm.errorMessage {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding()
            }
        }
        .frame(minWidth: 480, minHeight: 400)
    }

    private var roomsList: some View {
        List(vm.availableRooms, id: \.id) { room in
            RoomRowView(room: room) {
                Task { await vm.connect(roomID: room.id) }
            }
            .disabled(
                room.kind == "1:1" && room.available == false
            )
        }
    }

    // MARK: - Connected chat view

    private var connectedView: some View {
        VStack(spacing: 0) {
            peerInfoBar
            Divider()
            messagesArea
            Divider()
            inputBar
        }
        .frame(minWidth: 480, minHeight: 440)
    }

    private var peerInfoBar: some View {
        HStack(spacing: 16) {
            if let alias = vm.peerAlias {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Host: \(alias)")
                        .font(.caption.bold())
                    if let fp = vm.peerFingerprint {
                        Text(fp)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
            }

            if !vm.groupPeers.isEmpty {
                Divider().frame(height: 32)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Peers in room:")
                        .font(.caption.bold())
                    ForEach(vm.groupPeers, id: \.alias) { peer in
                        Text("\(peer.alias)  \(peer.fingerprint)")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer()

            if !vm.statusMessage.isEmpty {
                Text(vm.statusMessage)
                    .font(.caption)
                    .foregroundStyle(vm.isPending ? .orange : .secondary)
            }
        }
        .padding(10)
        .background(.quaternary.opacity(0.5))
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

    private var inputBar: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField("Message…", text: $vm.inputText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await vm.sendMessage() } }
                    .disabled(vm.isPending)
                Button("Send") { Task { await vm.sendMessage() } }
                    .disabled(
                        vm.inputText.trimmingCharacters(in: .whitespaces).isEmpty ||
                        vm.isPending
                    )
            }
            .padding(8)

            if vm.isPending {
                Text("⏳  Waiting for host to approve your join request…")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.bottom, 6)
            }
            if let err = vm.errorMessage {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.bottom, 6)
            }
        }
    }
}

// MARK: - Room row

private struct RoomRowView: View {
    let room: WireRoomInfo
    let onConnect: () -> Void

    private var isAvailable: Bool {
        room.kind == "group" || room.available == true
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(room.id).font(.headline)
                HStack(spacing: 8) {
                    Label(room.kind, systemImage: room.kind == "group" ? "person.3" : "person.2")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if room.kind == "1:1" {
                        Text(room.available == true ? "available" : "occupied")
                            .font(.caption)
                            .foregroundStyle(room.available == true ? .green : .red)
                    } else {
                        Text("\(room.peers) peer(s)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Spacer()
            Button("Connect", action: onConnect)
                .buttonStyle(.bordered)
                .disabled(!isAvailable)
        }
        .padding(.vertical, 4)
    }
}
