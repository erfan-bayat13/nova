import SwiftUI

struct DownloadView: View {
    @ObservedObject var store: ModelStore
    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Text("Nova runs on this phone").font(.title2.weight(.semibold))
            Text("One-time download, about 1.4 GB. Use Wi-Fi.").foregroundStyle(.secondary)
            if store.downloading {
                ProgressView(value: store.progress).padding(.horizontal, 40)
                Text("\(Int(store.progress * 100))%  ·  \(store.status)").font(.footnote).foregroundStyle(.secondary)
            } else {
                Button(store.failure == nil ? "Download" : "Try again") { store.start() }
                    .buttonStyle(.borderedProminent)
            }
            if let f = store.failure { Text(f).font(.footnote).foregroundStyle(.red).padding(.horizontal) }
            Spacer()
        }
    }
}

struct OrbView: View {
    @ObservedObject var nova: Nova
    @ObservedObject var store: ModelStore
    @GestureState private var held = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 24) {
                Spacer()
                Circle()
                    .fill(RadialGradient(colors: [.white.opacity(0.9), .gray.opacity(0.35), .black], center: .topLeading, startRadius: 4, endRadius: 90))
                    .frame(width: 120, height: 120)
                    .overlay(Circle().stroke(.white.opacity(0.25), lineWidth: 1))
                    .scaleEffect(scale)
                    .animation(.easeInOut(duration: 0.35), value: nova.state)
                    .gesture(DragGesture(minimumDistance: 0)
                        .updating($held) { _, s, _ in s = true }
                        .onChanged { _ in if nova.state != .listening { nova.pressDown() } }
                        .onEnded { _ in nova.pressUp() })
                Text(label).font(.footnote).foregroundStyle(.secondary)
                Text(nova.message).font(.caption2.monospaced()).foregroundStyle(.tertiary).multilineTextAlignment(.center).padding(.horizontal)
                Spacer()
            }
        }
        .task { await nova.load(store) }
    }

    private var scale: CGFloat {
        switch nova.state { case .listening: 1.15; case .speaking: 1.08; case .thinking: 0.95; default: 1 }
    }
    private var label: String {
        switch nova.state {
        case .idle: "Hold and talk"; case .loading: "Loading the model…"; case .listening: "Listening"
        case .thinking: "Thinking"; case .speaking: "Speaking"; case .error: "Something went wrong"
        }
    }
}
