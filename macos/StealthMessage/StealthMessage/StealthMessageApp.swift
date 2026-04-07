import SwiftUI
import AppKit

@main
struct StealthMessageApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var app = AppViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(app: app)
                .task { appDelegate.appViewModel = app }
        }
    }
}

/// Handles macOS lifecycle events — specifically graceful shutdown so that
/// connected peers receive a `bye` frame instead of a silent connection drop.
final class AppDelegate: NSObject, NSApplicationDelegate, @unchecked Sendable {
    var appViewModel: AppViewModel?

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let vm = appViewModel,
              (vm.hostViewModel?.isRunning == true || vm.clientViewModel?.isConnected == true)
        else {
            // Nothing running — terminate immediately.
            return .terminateNow
        }

        // Defer termination until shutdown completes.
        Task { @MainActor in
            await vm.gracefulShutdown()
            NSApplication.shared.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
