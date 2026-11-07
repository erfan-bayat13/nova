import AVFoundation

/// Mic in as PCM16 mono 16 kHz, speech out from PCM16 mono 24 kHz chunks (what LFM3-Omni uses).
final class AudioIO {
    static let micRate: Double = 16_000
    static let speechRate: Double = 24_000

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let speechFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: speechRate, channels: 1, interleaved: false)!
    private var converter: AVAudioConverter?
    private var onMic: (([Int16]) -> Void)?
    private var scheduled = 0
    private let lock = NSLock()
    var onPlaybackIdle: (() -> Void)?

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: speechFormat)
    }

    func configureSession() throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
        try s.setActive(true)
    }

    func requestMic() async -> Bool {
        await withCheckedContinuation { c in AVAudioApplication.requestRecordPermission { c.resume(returning: $0) } }
    }

    // MARK: mic

    func startMic(_ handler: @escaping ([Int16]) -> Void) throws {
        onMic = handler
        let input = engine.inputNode
        let inFmt = input.outputFormat(forBus: 0)
        let outFmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Self.micRate, channels: 1, interleaved: true)!
        converter = AVAudioConverter(from: inFmt, to: outFmt)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: inFmt) { [weak self] buf, _ in
            guard let self, let conv = self.converter else { return }
            let cap = AVAudioFrameCount(Double(buf.frameLength) * Self.micRate / inFmt.sampleRate) + 16
            guard let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
            var fed = false
            var err: NSError?
            conv.convert(to: out, error: &err) { _, status in
                if fed { status.pointee = .noDataNow; return nil }
                fed = true; status.pointee = .haveData; return buf
            }
            guard err == nil, let p = out.int16ChannelData?[0] else { return }
            self.onMic?(Array(UnsafeBufferPointer(start: p, count: Int(out.frameLength))))
        }
        if !engine.isRunning { try engine.start() }
    }

    func stopMic() {
        engine.inputNode.removeTap(onBus: 0)
        onMic = nil
    }

    // MARK: speech out

    /// Queue one chunk of PCM16 24 kHz mono. Chunks play back to back.
    func play(_ pcm: [Int16]) {
        guard !pcm.isEmpty, let buf = AVAudioPCMBuffer(pcmFormat: speechFormat, frameCapacity: AVAudioFrameCount(pcm.count)) else { return }
        buf.frameLength = AVAudioFrameCount(pcm.count)
        let dst = buf.floatChannelData![0]
        for i in 0..<pcm.count { dst[i] = Float(pcm[i]) / 32768 }
        if !engine.isRunning { try? engine.start() }
        lock.lock(); scheduled += 1; lock.unlock()
        player.scheduleBuffer(buf, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            guard let self else { return }
            self.lock.lock(); self.scheduled -= 1; let idle = self.scheduled == 0; self.lock.unlock()
            if idle { self.onPlaybackIdle?() }
        }
        if !player.isPlaying { player.play() }
    }

    /// Barge-in: drop everything queued.
    func stopPlayback() {
        player.stop()
        lock.lock(); scheduled = 0; lock.unlock()
    }
}
