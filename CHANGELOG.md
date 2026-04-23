# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the project uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Fixed
### Added
- `windows/StealthMessage/Views/JoinView` — **Switch room** panel: the server sends a
  `roomlist` frame right after the handshake containing all available group rooms.  The
  panel lists them with a "Switch" button each; clicking it disconnects from the current
  room and reconnects to the selected one (host approval flow applies for group rooms).
- `windows/StealthMessage/Views/JoinView` — **auto-scroll**: the message log now scrolls
  to the newest message automatically whenever one is added.

### Fixed
- `windows/StealthMessage/ViewModels/JoinViewModel.cs` — message log and room state are
  now cleared at the start of every new connection, so history from a previous room is
  never shown after a room switch or a host-initiated move.
- `windows/StealthMessage.Core/Network/WireMessage.cs` — `roomsinfo` parser threw
  `KeyNotFoundException` on group-room entries because it called `GetProperty("available")`
  unconditionally.  The CLI server omits `available` for group rooms; switched to
  `TryGetProperty` with a `false` default so group rooms parse correctly.
- `windows/StealthMessage/ViewModels/JoinViewModel.cs` — peer fingerprint was never shown
  for 1:1 rooms.  The CLI server only broadcasts a `peerlist` frame in group rooms, so
  `OnPeerList` never fired for 1:1 rooms.  Fingerprint is now computed directly from the
  host's public key received in `server-hello`.
- `windows/StealthMessage/ViewModels/HubViewModel.cs` — `BuildServerUri` produced an
  invalid URL in two cases: (1) `!addr.Contains(':')` matched the `ws:` scheme colon so the
  default port was never appended when the user omitted it; (2) `host/port` shorthand
  (e.g. `192.168.1.30/8765`) was left as a URL path instead of being converted to a port.
  Both forms now produce the correct `ws://host:port` URI.
- `windows/StealthMessage/ViewModels/JoinViewModel.cs` — `NormaliseUri` had the same
  `host/port`-as-path defect; fixed with the same heuristic (slash before all-digit
  segment → treat segment as port number).
- `windows/StealthMessage/ViewModels/JoinViewModel.cs`: room-move (host moves peer) now works
  reliably.  Two bugs were present:
  1. **UI-thread violation** — `ConnectAsync` was called from the receive-loop background thread,
     silently failing when updating UI-bound properties.  Fixed by dispatching reconnection to the
     UI thread via `_dispatcher.TryEnqueue`.
  2. **Async self-deadlock** — `await oldClient.DisposeAsync()` inside `OnMoved` called
     `await _receiveTask` inside `DisconnectAsync`, which is the currently-running receive loop,
     creating a circular wait that froze all involved tasks indefinitely.  Fixed by switching to
     fire-and-forget (`_ = oldClient.DisposeAsync().AsTask()`) so the receive loop can complete
     its current iteration and exit via cancellation token check before the dispose runs.

### Added
- `windows/StealthMessage`: navigation between Hub ↔ Host and Hub ↔ Join now works correctly.
  - `HostView` and `JoinView` each have a **← Hub** button that returns to the Hub screen
    without destroying the running server or active connection (mirrors macOS behaviour).
  - `AppViewModel` now preserves `HostViewModel` and `JoinViewModel` instances across navigation
    (`??=` reuse pattern). A running server survives the round-trip to Hub and back.
  - `HubView` shows a green "Server is running" / "Connected" status indicator when returning
    from an active session, and replaces the action buttons with "Resume server" / "Resume chat".
  - `HubViewModel.JoinAsync` now pre-fills `JoinViewModel.ServerUri` and `RoomId` with the
    address entered in Hub, so the user does not have to re-enter them in JoinView.
  - Active ViewModels are cleared on a new login (Setup / Unlock) so each session starts clean.

### Added
- `windows/StealthMessage`: messages in the chat now include a `[HH:mm]` timestamp prefix
  (local time captured at the moment of receipt/send). Applies to user messages, system messages,
  and error notices in both host mode (`HostViewModel`) and peer mode (`JoinViewModel`).

### Changed
- `windows/StealthMessage/MainWindow.xaml.cs`: window now opens at 900×660 logical pixels
  (DPI-aware, using `RasterizationScale`) and is centered on the working area of the display
  it appears on.

### Fixed
- `windows/StealthMessage.Core/Network/StealthServer.cs`: group room join now completes correctly.
  `HandleHelloAsync` now sends `server-hello` **before** the `pending` frame. The previous order
  (pending → approved → server-hello) violated the protocol handshake expected by the CLI client,
  which raised `"expected hello, got 'pending'"` and aborted the join.
- `windows/StealthMessage.Core/Network/StealthClient.cs`: updated handshake to match corrected
  server order — always reads `server-hello` as the first frame, then peeks 600 ms for an optional
  `pending` frame (group rooms). Any non-pending frame received during the peek (e.g. peer-list for
  1:1 rooms) is buffered and dispatched at the start of the receive loop.
- `windows/StealthMessage/Views/HostView.xaml`, `HostView.xaml.cs`: added **Move** action to the
  selected-peer context area — a `ComboBox` bound to `Rooms` lets the host pick a target room and
  a Move button invokes `MoveCommand` on the selected peer.

### Fixed
- `windows/StealthMessage`: room switching now works correctly in host mode.
  - `StealthServer`: added room name to all callbacks (`OnPeerConnected`, `OnPeerDisconnected`, `OnMessage`, `OnJoinRequest`).
  - `HostViewModel`: per-room message logs and peer lists; `Messages` and `ConnectedPeers` properties now return the selected room's collections; `SelectedRoom` property switches the active room and refreshes both lists; `SendMessageAsync` targets only peers in the selected room; single `_peersLock` guards both alias dictionaries.
  - `HostView.xaml`: rooms `ListView` has `SelectedItem="{Binding SelectedRoom, Mode=TwoWay}"` so clicking a room activates it; added active-room header above the message log; pending approval items now show the room name.

### Fixed
- `windows/StealthMessage.Core`: protocol compliance — `pubkey` JSON field name (was `pub_key`; caused 1011 internal error on all incoming connections) and protocol version string `"1"` (was `"0.8"`). Affected `WireMessage.cs` (parse + serialize), `StealthServer.cs`, and `StealthClient.cs`. Updated `WireMessageTests.cs` to match.
- `windows/StealthMessage.Core`: `pubkey` wire encoding — server hello was sending the raw ASCII-armored key instead of `base64url(armored_bytes)` as required by protocol §2. Fixed in `StealthServer.cs` (encode on send, decode on receive) and `StealthClient.cs` (encode on send).
- `windows/StealthMessage.Core/Network/StealthServer.cs`: base64url decode used naive `+ "=="` padding causing `FormatException` when key bytes are divisible by 3 (length % 4 == 0), producing 1011 internal error on every connection. Added correct padding helper (`switch (length % 4)`). Also: `SendPeerListToRoomAsync` now sends each peer a list of OTHER peers only (protocol §3); `HandleListRoomsAsync` now emits `"1:1"` in the wire kind field (protocol §1); `OnPeerConnected` and `OnMessage` callbacks now carry the peer's armoredPub; added `SendToAsync` and `GetPeerArmoredPub` host-send methods.
- `windows/StealthMessage.Core/Network/StealthClient.cs`: server hello pubkey is now decoded and stored as `PeerArmoredPubkey`/`PeerAlias` after the handshake, making it available for encryption and decryption by the caller.
- `windows/StealthMessage/ViewModels/HostViewModel.cs`: `OnMessage` now decrypts incoming messages instead of showing `<encrypted>`; `SendMessageAsync` now encrypts per-peer and sends via server; `OnPeerConnected` stores each peer's armoredPub.
- `windows/StealthMessage/ViewModels/JoinViewModel.cs`: callbacks set after handshake so `PeerArmoredPubkey` is available; `OnMessage` uses host pubkey for signature verification; `SendMessageAsync` encrypts for the host's pubkey instead of own pubkey.
- `windows/StealthMessage/ViewModels/HostViewModel.cs`: fixed lambda parameter name collision (`_` used as both a discard and a named parameter in `OnPeerConnected`; renamed to `_fp`) causing CS0029 compile error.
- `windows/StealthMessage.Core/Crypto/PgpManager.cs`: replaced PgpCore key generation with direct BouncyCastle call that omits the `KeyExpirationTime` subpacket. PgpCore's `GenerateKeyAsync` added a `KeyExpirationTime=0` subpacket which pgpy (Python CLI) interprets as "already expired at creation time", causing it to discard all messages signed by the Windows host.
- `windows/StealthMessage/Views/HostView.xaml`, `JoinView.xaml`: added `UpdateSourceTrigger=PropertyChanged` to message TextBox bindings — the WinUI 3 default is `LostFocus`, which prevented the Send button from becoming active while typing.

### Added
- `windows/`: initial Windows client implementation (C# 12 / WinUI 3).
  - Solution scaffolding: `StealthMessage.slnx`, three projects (`StealthMessage`, `StealthMessage.Core`, `StealthMessage.Tests`).
  - `StealthMessage.Core` (net10.0): `Crypto/` layer — `PgpManager`, `KeyStore`, `CryptoException` types. RSA-4096 key generation, sign-then-encrypt, decrypt-then-verify, DPAPI private key storage, fingerprint formatting.
  - `StealthMessage.Tests` (net10.0, no WinUI): 16 tests covering all crypto and key-store operations — all passing.
  - Phase 3 — ViewModels: AppViewModel (state machine), SetupViewModel, UnlockViewModel, HubViewModel, HostViewModel, JoinViewModel. RelayCommand / SyncRelayCommand / RelayCommand&lt;T&gt;.
  - Phase 4 — Views (XAML / Fluent Design): SetupView, UnlockView, HubView, HostView, JoinView. App.xaml with value converters (BoolToVisibility, InverseBoolToVisibility, NotEmptyToBool, CountToVisibility, RunningStatus, NotNullToVisibility). App.xaml.cs with Microsoft.Extensions.DependencyInjection container. MainWindow.xaml.cs with screen-switch via PropertyChanged.
  - WinUI app compiles clean (`dotnet build -r win-x64`, 0 errors, 0 warnings).
  - NuGet dependencies: `PgpCore 7.0.0`, `Microsoft.Extensions.Logging`, `System.Security.Cryptography.ProtectedData`.

### Changed
- `macos/make_dmg.sh`: added ad-hoc code signing step (`codesign --deep --force --sign -`) after the Xcode build and before DMG packaging. Ensures the app bundle can run on other machines without a paid Apple Developer account. Rebuilt `StealthMessage-1.0.dmg` distributed via syberiancode.com now includes the signed app.

---

## [macos/v1.0.0 — build 2] — 2026-04

### Changed
- `macos/make_dmg.sh`: added ad-hoc code signing — see above.

---

## [cli/v0.1.7 / macos/v1.0.0] — 2026-04

### Added
- GitHub Release `cli/v0.1.7` published with release notes and link to PyPI package.
- GitHub Release `macos/v1.0.0` published with `StealthMessage-1.0.dmg` attached and first-launch instructions.

### Changed
- `ARCHITECTURE.md`: macOS status updated from "In development" to "Functional" (monorepo tree and section header).
- `README.md`: CLI installation updated — `pip install stealth-message-cli` as primary method; all command examples updated from `python -m stealth_cli` to `stealth-cli`.
- `README.md`: macOS section restructured — user installation (DMG), first-launch Gatekeeper bypass instructions (macOS 13/14 and right-click method), security notes, build-from-source section separated.
- `CHANGELOG.md`: historical `[Unreleased]` content moved to `[cli 0.1.7 / macos 1.0.0] — 2026-04`; `[Future]` section added for pending Linux and Windows implementations.

---

## [cli 0.1.7 / macos 1.0.0] — 2026-04

### Added
- `macos/make_dmg.sh`: shell script that builds the Release app with `xcodebuild` and packages
  it as a distributable DMG (with custom background, icon layout, and Applications symlink).
- `macos/generate_dmg_bg.swift`: Swift script that generates the DMG background image (light
  gradient with arrow and "Drag to install" label) using AppKit.
- `macos/StealthMessage/StealthMessage/Assets.xcassets/AppIcon.appiconset/`: app icon PNG set
  (16×16, 32×32, 64×64, 128×128, 256×256, 512×512, 1024×1024).

### Changed
- `macos/StealthMessage/StealthMessage/UI/SetupView.swift`: refactored setup form UI from
  SwiftUI `Form` to custom `VStack`-based layout with individual text fields and improved
  spacing (28→32 header, 8→10 subtitle, +8 padding). Styled input fields with background,
  border, and shadow effects using `controlBackgroundColor` and `separatorColor`. Reorganized
  sections with dividers and better visual hierarchy. Fixed label font weight.
- `cli/stealth_cli/__main__.py`: updated built-in manual (`--manual`) to use the installed
  command `stealth-cli` in all examples instead of the development invocation
  `python -m stealth_cli`. Removed the "Running the tests" section (development-only
  content not relevant to end users). Removed unused `Rule` import.
- `cli/pyproject.toml`: bumped version to 0.1.7.

### Added
- `install.sh`: curl-based installer for Linux and macOS — detects Python 3.10+, prefers
  pipx, falls back to pip --user with PATH guidance.
- `install.ps1`: PowerShell installer for Windows — same logic, compatible with
  `irm | iex` one-liner.
- `cli/pyproject.toml`: bumped to 0.1.1, removed `<3.13` upper bound on `requires-python`
  to support Python 3.13+.


- `cli/README.md`: comprehensive installation and usage guide — curl-based installation for
  macOS/Linux and Windows (PowerShell), pip alternative, security features (RSA-4096,
  sign-then-encrypt, passphrase protection, no central server), requirements, and links
  to PyPI and GitHub.
- `cli/pyproject.toml`: PyPI metadata — license (GPL-3.0-only), keywords (chat, encryption,
  pgp, privacy, end-to-end), classifiers (Development Status, License, Python 3.10+/3.11/3.12),
  and project URLs (Homepage, Repository, Issues).
- `macos/StealthMessageTests/CryptoTests.swift`: full test suite for `PGPKeyManager` —
  keypair generation (armored block format, public/private distinctness), fingerprint
  format (10 groups of 4 uppercase hex chars), passphrase validation (correct, wrong,
  empty), encrypt/decrypt round-trip, base64url encoding of ciphertext, corrupted-payload
  rejection, and documented ObjectivePGP behaviour on wrong sender key.
- `macos/StealthMessageTests/NetworkTests.swift`: full test suite for the network layer —
  `IncomingFrame` parser (all frame types: `hello`, `roomsinfo`, `roomlist`, `message`,
  `peerlist`, `move`, `kick`, `error`, `pending`, `approved`, `ping`, `pong`, `bye`,
  `unknown`; malformed / missing-field cases), `wireJSON` serialiser, `base64urlEncode` /
  `base64urlDecodeString` helpers, and `withDeadline` timeout helper.

### Changed
- `macos/StealthMessage/Crypto/CryptoError.swift`: `CryptoError` now conforms to
  `Equatable` (required for `#expect(throws:)` in Swift Testing).
- `macos/StealthMessage/Network/Message.swift`: `ProtocolError` now conforms to
  `Equatable` (required for `#expect(throws:)` in Swift Testing).
- `README.md`: macOS implementation status table updated — Tests row changed from
  "Pending" to "Done"; summary line updated to reflect full completion.
- `macos/CLAUDE.md`: "What to implement next" section replaced with "Tests" section
  documenting the completed test suites and the `Equatable` conformance rationale.

### Changed (previous entry)
- `README.md`: macOS status updated to "Functional" in the clients table; implementation
  status table corrected — UI layer is complete, only tests remain pending.
- `macos/CLAUDE.md`: implementation state section updated to reflect completed UI layer
  (`AppViewModel`, `SetupView`, `UnlockView`, `HubView`, `HostView`, `JoinView`,
  `ContentView`, `StealthMessageApp`); "What to implement" section replaced with
  "What to implement next" focused on the remaining tests.

### Added
- `README.md`: expanded CLI section with installation, first run, room types,
  room name quoting rules, chat commands table, identity reset, and full macOS
  client section (requirements, how to open in Xcode, implementation status).
- `cli/stealth_cli/__main__.py`: added "Room names" section to the built-in
  manual documenting space support and when quotes are needed on the command
  line vs. inside chat commands.

### Fixed
- `cli/tests/test_network.py`: three group-room tests were deadlocking because
  the first peer (`cli1`) was awaited directly while the server held it in
  `pending` state — all group room peers require host approval, including the
  first one. Tests now connect `cli1` as an async task and approve it before
  proceeding with `cli2`.

### Added
- `README.md`: translated to English; updated features list (kick, reset, graceful
  shutdown, Tailscale); "Connecting over the internet" section; license (GPL-3.0).
- `ARCHITECTURE.md`: translated to English; full implementation status tables for
  CLI and macOS; updated protocol version to v0.8; kick flow diagram; reset identity
  section; graceful shutdown design decision; `peerlist` in group room flow.
- `CONTRIBUTING.md`: translated to English.
- `SECURITY.md`: translated to English; security contact email added.
- `CHANGELOG.md`: translated legacy Spanish entries to English.
- `CLAUDE.md` (root and `cli/`): added rule — all documentation must be written
  in English.
- `macos/StealthMessageApp.swift`: `AppDelegate` with `applicationShouldTerminate`
  — sends `bye` to all connected peers before the app quits (graceful shutdown).
- `macos/UI/AppViewModel.swift`: `gracefulShutdown()` — stops the running
  server or client and waits for cleanup before app termination.
- `macos/Network/StealthServer.swift`: `stop()` now sends a `bye` frame to
  every connected peer before cancelling connections.
- `macos/UI/SetupView.swift`: form redesigned with `Form.grouped` style;
  alias length validation (≤64 chars); copy-fingerprint button on the
  confirmation screen.
- `macos/UI/HubView.swift`: copy-fingerprint button on the identity card.
- `macos/UI/JoinView.swift`: copy-fingerprint button for the host's
  fingerprint; group peers shown in a popover instead of inline list;
  `/move` now correctly disconnects and reconnects to the new room
  (protocol §6) instead of only updating the label.
- `macos/UI/HostView.swift`: left panel rebuilt with native `List` — pending
  approvals surfaced at the top, rooms and peers in labelled sections.
- `macos/ContentView.swift`: `app: AppViewModel` promoted to a constructor
  parameter so `StealthMessageApp` owns the single instance.

### Changed
- `macos/UI/HostView.swift`: sidebar minimum width reduced (240 → 220 px).

---

- `macos/Network/Message.swift`: `kick` case added to `IncomingFrame` enum
  and parser (protocol.md §5 / v0.7).
- `macos/Network/StealthClient.swift`: `onKicked` callback + `kick` frame
  handler; `configure()` updated to include `onKicked`.
- `macos/Network/StealthServer.swift`: `kickPeer(alias:reason:)` method —
  sends `kick` frame and closes the peer connection.
- `macos/UI/AppViewModel.swift`: `resetIdentity()` — deletes Keychain keys
  and navigates back to setup screen (protocol.md §12).
- `macos/UI/UnlockView.swift`: "Reset identity" option on unlock screen.
- `macos/UI/HubView.swift`: hub screen redesign with identity card and
  reset identity action.
- `macos/UI/HostView.swift`: `/disconnect` button per peer; `kickPeer` wired
  through `HostViewModel`; various layout and reliability fixes.
- `macos/UI/JoinView.swift`: `onKicked` wired in `ClientViewModel` — shows
  "Disconnected by host" banner and returns to hub.
- `macos/ContentView.swift`: navigation updated to handle reset identity flow.
- `cli/stealth_cli/config.py`: `delete_keypair()` — removes saved keys and
  config, reverting to first-use state.
- `cli/stealth_cli/__main__.py`: `--reset` flag — deletes the saved identity
  and runs the setup wizard to create a new alias and keypair.
- `docs/protocol.md` v0.8: new §12 — identity model. Documents alias-in-key
  binding, fingerprint verification requirement, private key storage rules,
  and the reset implementation requirement for all clients.
- `docs/protocol.md` v0.7: new `kick` message (server → client) for
  host-initiated peer disconnect. Sections renumbered; `kick` added to
  message type reference table.
- `cli/network/server.py`: `kick_peer(alias, reason)` — sends `kick` frame
  and closes the WebSocket connection for the target peer.
- `cli/network/client.py`: `on_kicked` callback + `kick` frame handler —
  closes connection and fires callback with the reason string.
- `cli/ui/chat.py`: `/disconnect [alias]` host command — alias optional in
  1:1 rooms (auto-resolves the single peer); required in group rooms.
  Displays confirmation on kick. `on_kicked` wired in `_make_join_client`.
  Help table updated.

- `docs/protocol.md`: documented `peerlist` message type (v0.6). Sent by the
  server to all peers in a group room after each join/leave event; contains the
  alias and fingerprint of every other peer currently in the room.
- `macos/`: initial Xcode project scaffold for the native macOS client
  (SwiftUI, Swift 5.9+, macOS 13.0+). Includes ObjectivePGP 0.99.4 via SPM
  and Keychain Sharing entitlement configured.
- `macos/Crypto/`: crypto layer — `CryptoError`, `KeychainStore`, `PGPKeyManager`
  actor (RSA-4096 keygen, sign-then-encrypt, decrypt-then-verify, fingerprint
  formatting, Keychain storage).
- `macos/Network/`: full network layer — `Message.swift` (wire types, frame
  parser, base64url helpers, `withDeadline`), `StealthClient` actor
  (`URLSessionWebSocketTask`, all protocol.md message types, group room approval
  flow, ping/pong keepalive), `StealthServer` actor (`NWListener`/
  `NWProtocolWebSocket`, room management, host approval, peer relay, `peerlist`
  broadcast).
- `macos/UI/`: full UI layer — `AppViewModel` (navigation state machine, identity
  hold, passphrase in memory only), `SetupView` (first-launch wizard, RSA-4096
  keygen, Keychain save), `UnlockView` (passphrase validation), `HubView` (host
  or join choice), `HostView` (server management, room list, join requests,
  multi-room chat), `JoinView` (client connection, room discovery, group approval
  wait, chat).

### Fixed
- `macos/Crypto/PGPKeyManager.swift`: simplified keygen and encrypt — `Armor.armored`
  returns `String` directly (confirmed with ObjectivePGP 0.99.4 autocomplete).
- `macos/Network/Message.swift`: marked free functions (`wireJSON`, `withDeadline`,
  `base64urlEncode`, `base64urlDecodeString`, `IncomingFrame.parse`) as
  `nonisolated` to avoid `@MainActor` inference in SwiftUI module (Swift 5.9).
- `macos/Network/StealthClient.swift`: added `configure()` for batch callback
  assignment in a single actor hop.
- `macos/Network/StealthServer.swift`: replaced `CheckedContinuation` with
  `AsyncThrowingStream.makeStream()` to avoid stored-continuation `@MainActor`
  inference issue; added `configure()`; fixed double `wireJSON` call in
  `sendPeerlist`; fixed `pendingRequests` computation; fixed optional
  `localizedDescription` forced unwrap.
- `macos/UI/AppViewModel.swift`: refactored `MessageBubble` rendering into a
  `@ViewBuilder` computed property, removing `AnyShapeStyle` casting.

### Fixed
- `ui/chat.py`: `/switch <room>` in host mode now lists all connected peers one
  per line instead of showing only the last one.
- `ui/chat.py`: host-mode `on_disconnected` now also removes the peer from
  `peer_fingerprints`, preventing stale fingerprints from appearing in `/fp`
  after a peer moves to another room.
- `ui/chat.py`: `/fp` in a group room now shows the fingerprint of every peer
  in the room, not just the first one. This applies to both the host and to
  non-host peers: the server now broadcasts a `peerlist` message (alias +
  fingerprint of each other peer) to all group room members whenever someone
  joins or leaves, so every participant has an up-to-date view.
- `ui/chat.py`: `/rooms` in join mode now queries the server live via
  `query_rooms()` and shows all rooms with their real status (available,
  occupied, group), matching the room list shown during the connection wizard.
- `network/server.py`: group-room join approval now waits outside
  `HANDSHAKE_TIMEOUT` (10 s). Previously the host's 60 s approval window was
  inadvertently capped at 10 s, causing the server to close the connection
  before the host could type `/allow <alias>`.
- `network/server.py`: group rooms now require host approval for every peer,
  including the first one. Previously the approval gate was only triggered when
  the room already had peers, so the first peer bypassed approval entirely.

### Changed
- `network/server.py`: replaced deprecated `asyncio.get_event_loop()` with
  `asyncio.get_running_loop()` in `make_group_room()`.
- `ui/chat.py`: extracted `_make_join_client(room_id)` — single factory that
  creates a `StealthClient` and wires all six callbacks (`on_message`,
  `on_disconnected`, `on_pending`, `on_approved`, `on_move`, `on_roomlist`).
  Eliminates duplicated callback blocks in `run_join`, `_switch_join_room`, and
  `_reconnect_to_room`.
- `ui/chat.py`: extracted `_make_send_fn(room_id)` — replaces three identical
  inline closures.
- `ui/chat.py`: extracted `_dispatch_command(text)` — all command parsing moved
  out of `_input_loop` into a dedicated async method.

### Changed
- `README.md`: updated with current features, quick start, and usage examples.
- `ARCHITECTURE.md`: updated with room model, discovery flow, group room flow,
  and host relay design decision.
- `__main__.py` (`--manual`): manual updated — room discovery, `/rooms` with
  known rooms, examples with group/move, expanded security table, automatic
  `ws://` documented.

### Fixed
- `__main__.py`: URI entered without `ws://` prefix (e.g. `192.168.1.10:8765`)
  is normalised automatically — applies to both interactive mode and `--join` flag.

### Added
- **Room list on join (interactive mode)**: after entering the server URI, the
  available room list is automatically shown (type and status) before asking which
  room to join. Connected peer names are never disclosed.
  - `network/server.py`: handles `listrooms` before handshake; replies with `roomsinfo`.
  - `network/client.py`: standalone `query_rooms(uri)` function.
  - `__main__.py`: `_print_room_list(uri)` calls `query_rooms` and renders Rich table.
  - `docs/protocol.md`: `listrooms` / `roomsinfo` messages, version 0.5.
- **Group room discovery**: peers see in `/rooms` all group rooms on the server even
  if they are not in them — they can `/switch <room>` to request entry.
  - `network/server.py`: new `roomlist` message sent after handshake and each time
    a group room is created or converted.
  - `network/client.py`: handles `roomlist`, new `on_roomlist(list[str])` callback.
  - `ui/chat.py`: `_update_known_groups` updates `_room_states`.
  - `docs/protocol.md`: `roomlist` message, version 0.4.

### Fixed
- `network/client.py`, `ui/chat.py`: in group rooms, forwarded messages showed the
  host's name instead of the real sender — client now reads the `sender` field from
  the frame and uses it as the alias in the UI.
- `ui/chat.py`: the command list no longer appears every time a peer connects in host
  mode — only in the initial banner and when typing `/help`.
- `ui/chat.py`: `/move` was disconnecting the entire peer session — fixed by nulling
  out `on_disconnected` on the old client before calling `disconnect()`.

### Changed
- `ui/chat.py`: `_print_help` rewritten with a Rich `Table.grid` — commands displayed
  in two aligned columns (command + description).
- `__main__.py`: manual — replaced example names (Shorlo/Pepe/Juan) with generic
  names (Alice/Bob/Carol) and room `sala` with `team`.

### Added
- **Room system**: the host can create multiple independent rooms (`--rooms bob,carol`);
  each room admits exactly one peer at a time.
  - `network/server.py`: `StealthServer` accepts `rooms: list[str] | None`.
    New `_rooms: dict[room_id, PeerSession]` replacing the old `_peers`.
    New `send_to_room(room_id, plaintext)`. Callback signatures extended with `room_id`.
    Errors 4006 (room full) and 4007 (room not found).
  - `network/client.py`: `connect(uri, room_id="default")` sends the `room` field
    in hello. New `room_id` property. Detects server error responses during handshake.
  - `ui/chat.py`: multi-room UI — prompt shows active room (`[Alice@bob]`), messages
    labelled with room, commands `/switch <room>`, `/rooms`, `/next`.
  - `__main__.py`: `--rooms` (host) and `--room` (join) flags.
  - `docs/protocol.md`: `room` field in client hello, codes 4006 and 4007, version 0.2.
  - `tests/test_network.py`: 7 new tests.

### Fixed
- `ui/chat.py`: Rich markup `[dim]...[/dim]` was printed as literal text in the
  host connection banner — changed to `Text.from_markup()` in all affected places.
- `ui/chat.py`: the command list was not shown when a peer connected in host mode.
- `ui/chat.py`: `/rooms` was being sent as a message instead of consumed as a command.
- `ui/chat.py`: join banner showed `Connected to [room1] Shorlo`; now shows
  `Connected to Alice  [room: room1]`.
- `network/server.py`: `_allowed_rooms` changed from `frozenset` to `set` for mutability.
- `__main__.py`: user manual updated with rooms, group rooms, 3-participant examples,
  host vs all commands table, expanded security model.
- `ui/chat.py`: raw prompt line is erased with ANSI escape `\x1b[1A\x1b[2K` before
  printing the formatted outgoing message.

### Added
- **Group rooms**: multiple peers per room with host approval.
  - `network/server.py`: `StealthServer(group_rooms=[...])`, `make_group_room()`,
    `approve_join()`, `deny_join()`, `pending_requests`, `move_peer(alias, room)`.
    New `on_join_request(alias, fp, room_id)` callback. Messages `pending`, `approved`,
    `move`. Automatic forwarding between peers in the same group. Error code 4008.
  - `network/client.py`: `_approval_loop` — blocks `connect()` until the host
    approves or denies. Callbacks `on_pending`, `on_approved`, `on_move`.
  - `ui/chat.py`: host receives join request notification with fingerprint.
    Commands `/allow <alias>`, `/deny <alias>`, `/group <room>`, `/move <alias> <room>`,
    `/pending`. Client shows "Waiting for host approval…" and "Approved!" automatically.
  - `docs/protocol.md`: `pending`, `approved`, `move` messages; code 4008; version 0.3.
  - `tests/test_network.py`: 4 new tests (64/64 passing).

### Added
- `network/server.py`: `add_room(room_id)` — adds a room at runtime.
- `ui/chat.py`: `/switch <room>` in join mode — disconnects from current room and
  connects to the new one; if room is full (4006) shows "Room already occupied" and
  reconnects to the previous room.
- `ui/chat.py`: `/new <room>` command in host mode — creates a new room without restart.
- `ui/chat.py`: `/help` and `/rooms` always available in host mode.
- `ui/chat.py`: host startup banner shows the connection URL and commands.
- `__main__.py`: pgpy warnings suppressed from UI output (compression, self-sigs,
  revocation, flags, TripleDES) — internal pgpy limitations that do not affect
  encryption or signing.
- `ui/chat.py`: infinite prompt loop — replaced `asyncio.wait_for` with timeout
  cancelling `prompt_async` by `asyncio.wait(FIRST_COMPLETED)` with prompt task and
  stop-event task; the prompt is never interrupted.

### Added
- `.vscode/settings.json`: Python interpreter pointed to `cli/.venv` to resolve
  Pylance warnings.
- `--manual` flag in `__main__.py`: full user manual rendered with Rich.
- `cli/stealth_cli/ui/setup.py`: first-use wizard — alias, passphrase with
  confirmation, RSA-4096 with spinner, fingerprint display.
- `cli/stealth_cli/ui/chat.py`: Rich + prompt_toolkit chat screen — host and join
  modes, incoming messages without breaking input, `/fp`, `/help`, `/quit`.
- `cli/stealth_cli/__main__.py`: full entry point — first-use detection, passphrase
  validation, interactive or flag-based mode selection (`--host`/`--join`).
- `cli/stealth_cli/config.py`: key persistence with platformdirs — `save_keypair`,
  `load_*`, 0600 permissions on private key.
- `cli/stealth_cli/network/server.py`: `StealthServer` — WebSocket host with
  handshake (§1), encrypted messages (§2), ping/pong/bye (§3), error codes (§4),
  multiple simultaneous connections.
- `cli/stealth_cli/network/client.py`: `StealthClient` — WebSocket joiner with
  handshake, encrypted send, ping with RTT, clean disconnect.
- 21 integration tests in `tests/test_network.py`.
- `cli/stealth_cli/crypto/messages.py`: `encrypt` and `decrypt` (protocol §2.1) —
  sign-then-encrypt, Base64 URL-safe, `SignatureError` on invalid signature.
- `cli/stealth_cli/exceptions.py`: `StealthError`, `SignatureError`, `ProtocolError`
  with numeric code (protocol §4).
- `cli/stealth_cli/crypto/keys.py`: `generate_keypair`, `load_private_key`,
  `load_public_key`, `get_fingerprint` — 21 tests passing.
- `cli/pyproject.toml` with dependencies, dev-dependencies, entry point, and
  black/ruff/mypy/pytest configuration.
- `cli/stealth_cli/` directory structure with empty modules: `crypto/`, `network/`,
  `ui/`, `exceptions.py`, `config.py`, `__main__.py`.
- Empty tests in `cli/tests/`: `test_crypto.py`, `test_network.py`.

### Changed
- `test` branch established as the main working branch; `main` only receives changes
  via PR.
- Root `CLAUDE.md` updated with branch rule (always work on `test`).
- `CONTRIBUTING.md` updated with working branch instructions.

### Added
- Initial monorepo structure with directories `cli/`, `macos/`, `windows/`, `linux/`.
- Communication protocol specification v0.1 in `docs/protocol.md`.
- Root `CLAUDE.md` with architecture, global rules, and workflow guidelines.
- Per-sub-project `CLAUDE.md` with stack, structure, and specific conventions.
- `ARCHITECTURE.md` with system architecture description.
- `SECURITY.md` with security policy and vulnerability reporting.
- `CONTRIBUTING.md` with project contribution guide.
- `CHANGELOG.md` (this file).
- `.gitignore` for Python, Swift/SPM, C#/.NET, macOS, and IDEs.
- `README.md` with full project description.

---

## [Future]

### Planned
- Linux app (Python + GTK4): complete and integrated with libsecret.
- Windows app (C# + WinUI 3): complete and integrated with DPAPI.
