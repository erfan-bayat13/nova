import SwiftUI

enum OrbState: String { case idle, loading, listening, thinking, speaking, error }

/// The conversation: hold the orb, talk, let go, the phone answers out loud.
@MainActor
final class Nova: ObservableObject {
    @Published var state: OrbState = .idle
    @Published var message = ""          // tiny status line for testing, e.g. timings
    @Published var lastStats: TurnStats?

    private let audio = AudioIO()
    private let engine: VoiceEngine = LlamaEngine()
    private var mic: [Int16] = []
    private var loaded = false
    private var turn: Task<Void, Never>?

    func load(_ store: ModelStore) async {
        guard !loaded else { return }
        state = .loading
        do {
            try audio.configureSession()
            guard await audio.requestMic() else { fail("Microphone is off for Nova (Settings > Nova)"); return }
            try await engine.load(modelPath: store.modelPath, mmprojPath: store.mmprojPath)
            loaded = true
            state = .idle
        } catch { fail(error.localizedDescription) }
    }

    func pressDown() {
        guard loaded else { return }
        turn?.cancel(); engine.cancel(); audio.stopPlayback()   // barge-in
        mic.removeAll(keepingCapacity: true)
        do {
            try audio.startMic { [weak self] chunk in Task { @MainActor in self?.mic.append(contentsOf: chunk) } }
            state = .listening
        } catch { fail(error.localizedDescription) }
    }

    func pressUp() {
        guard state == .listening else { return }
        audio.stopMic()
        let samples = mic
        guard samples.count > Int(0.3 * AudioIO.micRate) else { state = .idle; return }   // ignore taps
        state = .thinking
        let start = Date()
        turn = Task {
            var first: TimeInterval?
            do {
                let stats = try await engine.respond(to: samples) { [weak self] chunk in
                    Task { @MainActor in
                        guard let self else { return }
                        if first == nil { first = Date().timeIntervalSince(start); self.state = .speaking }
                        self.audio.play(chunk)
                    }
                }
                var s = stats; s.timeToFirstAudio = first
                lastStats = s
                message = String(format: "first sound %.1fs · %.1fs of speech in %.1fs", first ?? 0, s.audioSeconds, s.wallSeconds)
                audio.onPlaybackIdle = { [weak self] in Task { @MainActor in if self?.state == .speaking { self?.state = .idle } } }
                if first == nil { state = .idle }
            } catch is CancellationError { state = .idle }
            catch { fail(error.localizedDescription) }
        }
    }

    private func fail(_ text: String) { message = text; state = .error }
}
