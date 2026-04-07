import SwiftUI
import AppKit
import Darwin

// MARK: - Supporting types

struct RoomInfo: Identifiable, Sendable {
    let id: String          // room name
    var isGroup: Bool
    var peerCount: Int
}

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
    /// Messages keyed by room ID — only the active room is displayed.
    var messagesByRoom: [String: [ChatMessage]] = [:]
    /// Unread count for rooms that are not currently active.
    var unreadByRoom: [String: Int] = [:]
    var allRooms: [RoomInfo] = []          // live room list while running

    /// Messages for the room the host is currently viewing.
    var activeRoomMessages: [ChatMessage] {
        messagesByRoom[activeRoom] ?? []
    }

    // MARK: Active room (host sends here)
    var activeRoom: String = ""

    // MARK: Message input
    var inputText: String = ""

    // MARK: Runtime room management (while running)
    var newRoomNameRuntime: String = ""
    var newGroupRoomNameRuntime: String = ""
    var showAddRoomSheet: Bool = false

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

    /// Peers in the currently active room only.
    var peersInActiveRoom: [ConnectedPeer] {
        peers.filter { $0.roomID == activeRoom }
    }

    /// All room IDs (for move destination picker).
    var allRoomIDs: [String] { allRooms.map(\.id) }

    /// Selects a room and clears its unread badge.
    func selectRoom(_ id: String) {
        activeRoom = id
        unreadByRoom[id] = 0
    }

    // MARK: - Pre-start room config

    func addRoom() {
        let name = newRoomName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !oneToOneRooms.contains(name), !groupRooms.contains(name) else { return }
        oneToOneRooms.append(name)
        newRoomName = ""
    }

    func removeRoom(_ name: String) { oneToOneRooms.removeAll { $0 == name } }

    func addGroupRoom() {
        let name = newGroupRoomName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !groupRooms.contains(name), !oneToOneRooms.contains(name) else { return }
        groupRooms.append(name)
        newGroupRoomName = ""
    }

    func removeGroupRoom(_ name: String) { groupRooms.removeAll { $0 == name } }

    // MARK: - Runtime room management

    func addRoomAtRuntime(_ name: String? = nil, group: Bool = false) async {
        let n = (name ?? newRoomNameRuntime).trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty else { return }
        newRoomNameRuntime = ""
        await server?.addRoom(n, group: group)
        await refreshRooms()
    }

    func makeGroupRoom(_ roomID: String) async {
        await server?.makeGroupRoom(roomID)
        await refreshRooms()
        systemMessage("Room '\(roomID)' is now a group room", room: roomID)
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

        await srv.configure(
            onPeerConnected: { [weak self] peerAlias, fp, roomID in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.peers.append(ConnectedPeer(alias: peerAlias, fingerprint: fp, roomID: roomID))
                    self.systemMessage("\(peerAlias) joined \(roomID)", room: roomID)
                    await self.refreshRooms()
                }
            },
            onMessage: { [weak self] peerAlias, text, roomID in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.appendMessage(
                        ChatMessage(sender: peerAlias, text: text, timestamp: Date(), isOwn: false),
                        to: roomID
                    )
                }
            },
            onPeerDisconnected: { [weak self] peerAlias, roomID in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.peers.removeAll { $0.alias == peerAlias && $0.roomID == roomID }
                    self.systemMessage("\(peerAlias) left \(roomID)", room: roomID)
                    await self.refreshRooms()
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
            server     = srv
            serverPort = port
            localIP    = hostLocalIPAddress()
            isRunning  = true
            await refreshRooms()
            activeRoom = allRooms.first?.id ?? ""
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
        allRooms.removeAll()
        messagesByRoom.removeAll()
        unreadByRoom.removeAll()
        activeRoom = ""
    }

    // MARK: - Rooms

    private func refreshRooms() async {
        guard let srv = server else { return }
        let infos = await srv.allRoomInfos
        allRooms = infos.map { RoomInfo(id: $0.id, isGroup: $0.isGroup, peerCount: $0.peerCount) }
        if !allRooms.contains(where: { $0.id == activeRoom }) {
            activeRoom = allRooms.first?.id ?? ""
        }
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

    // MARK: - Peer management

    func kickPeer(_ peer: ConnectedPeer) async {
        do {
            try await server?.kickPeer(alias: peer.alias)
            let room = peer.roomID
            peers.removeAll { $0.id == peer.id }
            systemMessage("\(peer.alias) was kicked", room: room)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func movePeer(_ peer: ConnectedPeer, to roomID: String) async {
        do {
            try await server?.movePeer(alias: peer.alias, to: roomID)
            systemMessage("Asked \(peer.alias) to move to \(roomID)", room: peer.roomID)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Messaging

    func sendMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, let srv = server, !activeRoom.isEmpty else { return }
        inputText = ""

        do {
            try await srv.sendToRoom(activeRoom, plaintext: text)
        } catch { /* room may be empty — still record locally */ }
        appendMessage(
            ChatMessage(sender: alias, text: text, timestamp: Date(), isOwn: true),
            to: activeRoom,
            countsAsUnread: false
        )
    }

    /// Appends a message to `room`'s list. Increments the unread badge only when
    /// `countsAsUnread` is true and the room is not the one currently being viewed.
    private func appendMessage(_ msg: ChatMessage, to room: String, countsAsUnread: Bool = true) {
        if messagesByRoom[room] == nil { messagesByRoom[room] = [] }
        messagesByRoom[room]?.append(msg)
        if countsAsUnread && room != activeRoom {
            unreadByRoom[room, default: 0] += 1
        }
    }

    /// Posts an informational system message to `room` (defaults to `activeRoom`).
    /// Never increments the unread badge.
    private func systemMessage(_ text: String, room: String? = nil) {
        let target = room ?? activeRoom
        appendMessage(
            ChatMessage(sender: "•", text: text, timestamp: Date(), isOwn: false),
            to: target,
            countsAsUnread: false
        )
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
    @Bindable var vm: HostViewModel
    var app: AppViewModel

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
                    Button("Stop") { Task { await vm.stopServer() } }
                        .foregroundStyle(.red)
                } else {
                    Button("Start Server") { Task { await vm.startServer() } }
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
                                .foregroundStyle(.red).buttonStyle(.borderless)
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
                            .foregroundStyle(.red).buttonStyle(.borderless)
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
                Section { Text(err).foregroundStyle(.red) }
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
            leftPanel
                .frame(minWidth: 220, idealWidth: 260, maxWidth: 320)
            rightPanel
        }
        .frame(minWidth: 680, minHeight: 480)
    }

    // MARK: Left panel

    private var leftPanel: some View {
        VStack(spacing: 0) {
            serverInfoHeader
            Divider()
            List {
                // Pending approvals first — they require immediate host action
                if !vm.pendingRequests.isEmpty {
                    Section {
                        ForEach(vm.pendingRequests) { req in
                            pendingRowView(req)
                        }
                    } header: {
                        Label("Approval Needed (\(vm.pendingRequests.count))",
                              systemImage: "person.badge.clock")
                            .foregroundStyle(.orange)
                    }
                }

                Section {
                    ForEach(vm.allRooms) { room in
                        RoomRowView(
                            room: room,
                            isActive: room.id == vm.activeRoom,
                            unreadCount: vm.unreadByRoom[room.id, default: 0]
                        ) {
                            vm.selectRoom(room.id)
                        } onMakeGroup: {
                            if !room.isGroup { Task { await vm.makeGroupRoom(room.id) } }
                        }
                        .listRowBackground(
                            room.id == vm.activeRoom
                                ? Color.accentColor.opacity(0.12)
                                : nil
                        )
                    }
                } header: {
                    HStack {
                        Text("Rooms")
                        Spacer()
                        Button { vm.showAddRoomSheet = true } label: {
                            Image(systemName: "plus.circle.fill")
                                .symbolRenderingMode(.palette)
                                .foregroundStyle(Color.white, Color.accentColor)
                                .font(.callout)
                        }
                        .buttonStyle(.plain)
                        .help("Add room")
                    }
                }

                Section {
                    if vm.peers.isEmpty {
                        Text("No peers connected yet")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    } else {
                        ForEach(vm.peers) { peer in
                            PeerRowView(peer: peer, allRooms: vm.allRoomIDs) { room in
                                Task { await vm.movePeer(peer, to: room) }
                            } onKick: {
                                Task { await vm.kickPeer(peer) }
                            }
                        }
                    }
                } header: {
                    Text("Peers (\(vm.peers.count))")
                }
            }
            .listStyle(.sidebar)
            .sheet(isPresented: $vm.showAddRoomSheet) {
                AddRoomSheet(vm: vm)
            }
        }
    }

    // MARK: Pending row (SF Symbols approve / deny)

    @ViewBuilder
    private func pendingRowView(_ req: JoinRequest) -> some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(req.alias).font(.callout.bold())
                Text(req.fingerprint)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
                Text("→ \(req.roomID)").font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            Button { Task { await vm.approve(req) } } label: {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.title3)
            }
            .buttonStyle(.borderless)
            .help("Approve \(req.alias)")

            Button { Task { await vm.deny(req) } } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.red)
                    .font(.title3)
            }
            .buttonStyle(.borderless)
            .help("Deny \(req.alias)")
        }
        .padding(.vertical, 2)
    }

    private var serverInfoHeader: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Circle().fill(.green).frame(width: 8, height: 8)
                Text("Running").font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 6) {
                Text(vm.serverURL)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .lineLimit(1)
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(vm.serverURL, forType: .string)
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .buttonStyle(.borderless)
                .help("Copy server URL")
            }
            Text("Share this address with peers").font(.caption2).foregroundStyle(.secondary)
        }
        .padding()
    }

    // MARK: Right panel (chat)

    private var rightPanel: some View {
        VStack(spacing: 0) {
            messagesArea
            Divider()
            sendBar
            if let err = vm.errorMessage {
                Text(err).font(.caption).foregroundStyle(.red)
                    .padding(.horizontal).padding(.bottom, 4)
            }
        }
    }

    private var messagesArea: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(vm.activeRoomMessages) { msg in
                        MessageBubble(message: msg).id(msg.id)
                    }
                }
                .padding()
            }
            .onChange(of: vm.activeRoomMessages.count) { _, _ in
                if let last = vm.activeRoomMessages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            .onChange(of: vm.activeRoom) { _, _ in
                // Scroll to bottom when switching rooms
                if let last = vm.activeRoomMessages.last {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }

    private var sendBar: some View {
        HStack(spacing: 8) {
            // Active room indicator — change room by clicking in the sidebar
            if !vm.activeRoom.isEmpty {
                let isGroup = vm.allRooms.first(where: { $0.id == vm.activeRoom })?.isGroup == true
                Label(vm.activeRoom, systemImage: isGroup ? "person.3" : "person.2")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .frame(maxWidth: 130, alignment: .leading)
            }

            TextField("Message…", text: $vm.inputText)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await vm.sendMessage() } }

            Button("Send") { Task { await vm.sendMessage() } }
                .disabled(vm.inputText.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(8)
    }
}

// MARK: - Room row

private struct RoomRowView: View {
    let room: RoomInfo
    let isActive: Bool
    let unreadCount: Int
    let onSelect: () -> Void
    let onMakeGroup: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 6) {
                Image(systemName: room.isGroup ? "person.3" : "person.2")
                    .font(.caption)
                    .foregroundStyle(isActive ? .primary : .secondary)

                Text(room.id)
                    .font(isActive ? .callout.bold() : .callout)
                    .foregroundStyle(isActive ? .primary : .secondary)

                Spacer()

                // Unread badge takes precedence over peer count
                if unreadCount > 0 {
                    Text("\(unreadCount)")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(Color.accentColor, in: Capsule())
                } else {
                    Text("\(room.peerCount)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .contextMenu {
            if !room.isGroup {
                Button("Convert to group room") { onMakeGroup() }
            }
        }
    }
}

// MARK: - Peer row with actions

private struct PeerRowView: View {
    let peer: ConnectedPeer
    let allRooms: [String]
    let onMove: (String) -> Void
    let onKick: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(peer.alias).font(.callout.bold())
                    Text("· \(peer.roomID)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text(peer.fingerprint)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1).truncationMode(.middle)
            }
            Spacer()

            // ZStack: transparent Menu handles interactions; white icon is purely visual.
            // menuStyle(.borderlessButton) overrides any foregroundStyle on the label,
            // so we separate interaction from appearance.
            ZStack {
                Menu {
                    let destinations = allRooms.filter { $0 != peer.roomID }
                    if !destinations.isEmpty {
                        Section("Move to…") {
                            ForEach(destinations, id: \.self) { room in
                                Button {
                                    onMove(room)
                                } label: {
                                    Label(room, systemImage: "arrow.right")
                                }
                            }
                        }
                    }
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(peer.fingerprint, forType: .string)
                    } label: {
                        Label("Copy fingerprint", systemImage: "doc.on.doc")
                    }
                    Divider()
                    Button("Disconnect \(peer.alias)", role: .destructive) {
                        onKick()
                    }
                } label: {
                    Color.clear.frame(width: 22, height: 22)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)

                Image(systemName: "ellipsis.circle")
                    .font(.body)
                    .foregroundStyle(Color.white)
                    .allowsHitTesting(false)
            }
            .fixedSize()
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Add room sheet

private struct AddRoomSheet: View {
    var vm: HostViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var oneToOneName = ""
    @State private var groupName = ""

    var body: some View {
        VStack(spacing: 20) {
            Text("Add Room").font(.title2.bold())

            VStack(alignment: .leading, spacing: 8) {
                Text("1:1 Room").font(.caption.bold()).foregroundStyle(.secondary)
                HStack {
                    TextField("Room name…", text: $oneToOneName)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            guard !oneToOneName.trimmingCharacters(in: .whitespaces).isEmpty else { return }
                            Task { await vm.addRoomAtRuntime(oneToOneName, group: false); dismiss() }
                        }
                    Button("Add") {
                        Task { await vm.addRoomAtRuntime(oneToOneName, group: false); dismiss() }
                    }
                    .disabled(oneToOneName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Group Room").font(.caption.bold()).foregroundStyle(.secondary)
                HStack {
                    TextField("Group room name…", text: $groupName)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            guard !groupName.trimmingCharacters(in: .whitespaces).isEmpty else { return }
                            Task { await vm.addRoomAtRuntime(groupName, group: true); dismiss() }
                        }
                    Button("Add") {
                        Task { await vm.addRoomAtRuntime(groupName, group: true); dismiss() }
                    }
                    .disabled(groupName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
            }
        }
        .padding(24)
        .frame(width: 360)
    }
}
