import SwiftUI

@main
struct NovaApp: App {
    @StateObject private var store = ModelStore()
    @StateObject private var nova = Nova()

    var body: some Scene {
        WindowGroup {
            Group {
                if store.isReady {
                    OrbView(nova: nova, store: store)
                } else {
                    DownloadView(store: store)
                }
            }
            .preferredColorScheme(.dark)
        }
    }
}
