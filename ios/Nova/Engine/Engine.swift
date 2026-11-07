import Foundation

/// One spoken turn, entirely on the phone: PCM16 16 kHz in, PCM16 24 kHz chunks out.
protocol VoiceEngine: AnyObject {
    /// Loads the model and the audio projector. Throws if the files are missing or memory runs out.
    func load(modelPath: String, mmprojPath: String) async throws
    /// Runs one turn. `emit` is called with each chunk of speech as it is made.
    /// Returns when speech ends or `cancel()` is called.
    func respond(to pcm16k: [Int16], emit: @escaping ([Int16]) -> Void) async throws -> TurnStats
    func cancel()
}

struct TurnStats {
    var timeToFirstAudio: TimeInterval?   // seconds from end of input to first sound
    var audioSeconds: Double
    var wallSeconds: Double
    var realTimeFactor: Double { audioSeconds > 0 ? wallSeconds / audioSeconds : 0 }
}

enum EngineError: LocalizedError {
    case notWired
    var errorDescription: String? {
        "The model engine isn't linked yet. Build llama.xcframework (ios/scripts/build-llama.sh) and replace StubEngine with LlamaEngine."
    }
}

/// Placeholder until llama.xcframework exists. Lets the app, the download and the audio path be tested first.
final class StubEngine: VoiceEngine {
    func load(modelPath: String, mmprojPath: String) async throws { throw EngineError.notWired }
    func respond(to pcm16k: [Int16], emit: @escaping ([Int16]) -> Void) async throws -> TurnStats { throw EngineError.notWired }
    func cancel() {}
}
