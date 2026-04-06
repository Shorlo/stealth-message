//
//  ContentView.swift
//  StealthMessage
//
//  Created by Sirius on 06/04/2026.
//

import SwiftUI

struct ContentView: View {
    @State private var app = AppViewModel()

    var body: some View {
        NavigationStack {
            Group {
                switch app.screen {
                case .setup:
                    SetupView(app: app)
                case .unlock:
                    UnlockView(app: app)
                case .hub:
                    HubView(app: app)
                case .hosting:
                    // Guaranteed non-nil: AppViewModel.goHosting() always creates it.
                    if let vm = app.hostViewModel {
                        HostView(vm: vm, app: app)
                    }
                case .joining:
                    if let vm = app.clientViewModel {
                        JoinView(vm: vm, app: app)
                    }
                }
            }
        }
        .frame(minWidth: 600, minHeight: 500)
    }
}

#Preview {
    ContentView()
}
