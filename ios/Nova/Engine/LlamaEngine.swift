import Foundation

/// The real engine: LFM3-Omni through llama.cpp + mtmd (see NovaBridge.cpp). All model work runs on one
/// serial background queue, never on the main thread.
final class LlamaEngine: VoiceEngine {
    static let systemPrompt = """
    You are Nova, a warm, casual friend the user talks to by voice on their phone. Everything you say is spoken aloud.
    Answer naturally, like a friend on a call: usually one to three short sentences. Go longer only if they ask for detail, and never more than about 80 words.
    No markdown, lists, emojis, sound effects or stage directions. Say numbers and units the way people speak them.
    If you didn't hear or understand something, say so and ask them to repeat instead of guessing.
    """
    static let contextSize: Int32 = 3072
    static let maxReplySeconds = 35.0

    private let queue = DispatchQueue(label: "nova.llama", qos: .userInitiated)
    private var handle: NovaEngineRef?

    deinit { if let h = handle { nova_engine_free(h) } }

    func load(modelPath: String, mmprojPath: String) async throws {
        let h: NovaEngineRef? = try await withCheckedThrowingContinuation { cont in
            queue.async {
                var err = [CChar](repeating: 0, count: 256)
                let h = nova_engine_load(modelPath, mmprojPath, Self.contextSize, Self.systemPrompt, &err, err.count)
                if h == nil { cont.resume(throwing: LlamaError.failed(String(cString: err))) }
                else { cont.resume(returning: h) }
            }
        }
        handle = h
    }

    func respond(to pcm16k: [Int16], emit: @escaping ([Int16]) -> Void) async throws -> TurnStats {
        guard let h = handle else { throw LlamaError.failed("model not loaded") }
        let start = Date()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (cont: CheckedContinuation<TurnStats, Error>) in
                queue.async {
                    let box = Unmanaged.passRetained(EmitBox(emit))
                    defer { box.release() }
                    var err = [CChar](repeating: 0, count: 256)
                    var samples: Int64 = 0
                    let rc = pcm16k.withUnsafeBufferPointer { buf in
                        nova_engine_respond(h, buf.baseAddress, buf.count, Self.maxReplySeconds,
                                            { p, n, user in
                                                guard let p, let user else { return }
                                                let box = Unmanaged<EmitBox>.fromOpaque(user).takeUnretainedValue()
                                                box.emit(Array(UnsafeBufferPointer(start: p, count: n)))
                                            },
                                            box.toOpaque(), &samples, &err, err.count)
                    }
                    if rc == 1 { cont.resume(throwing: CancellationError()) }
                    else if rc < 0 { cont.resume(throwing: LlamaError.failed(String(cString: err))) }
                    else {
                        cont.resume(returning: TurnStats(timeToFirstAudio: nil,
                                                         audioSeconds: Double(samples) / 24000.0,
                                                         wallSeconds: Date().timeIntervalSince(start)))
                    }
                }
            }
        } onCancel: { [weak self] in self?.cancel() }
    }

    func cancel() { if let h = handle { nova_engine_cancel(h) } }
}

private final class EmitBox {
    let emit: ([Int16]) -> Void
    init(_ emit: @escaping ([Int16]) -> Void) { self.emit = emit }
}

enum LlamaError: LocalizedError {
    case failed(String)
    var errorDescription: String? { if case .failed(let m) = self { return m }; return nil }
}
