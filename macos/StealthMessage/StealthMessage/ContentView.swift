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
                    HostView(app: app)
                case .joining:
                    JoinView(app: app)
                }
            }
        }
        .frame(minWidth: 600, minHeight: 500)
    }
}

#Preview {
    ContentView()
}
