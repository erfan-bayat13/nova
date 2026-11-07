import Foundation

/// Downloads the model on the phone itself (nothing is copied from the Mac).
/// Files live in Application Support and are excluded from iCloud backup.
@MainActor
final class ModelStore: NSObject, ObservableObject, URLSessionDownloadDelegate {
    struct Item: Identifiable {
        let id: String            // file name
        let url: URL
        let approxBytes: Int64
    }

    // Same files llama.cpp's `-hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M` pulls.
    static let items: [Item] = [
        .init(id: "LFM3-Omni-2B-Q4_K_M.gguf",
              url: URL(string: "https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF/resolve/main/LFM3-Omni-2B-Q4_K_M.gguf")!,
              approxBytes: 1_099_630_080),
        .init(id: "mmproj-LFM3-Omni-2B-Q4_0.gguf",
              url: URL(string: "https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF/resolve/main/mmproj-LFM3-Omni-2B-Q4_0.gguf")!,
              approxBytes: 270_576_544),
    ]

    @Published private(set) var isReady = false
    @Published private(set) var progress: Double = 0
    @Published private(set) var status = "Not downloaded"
    @Published private(set) var failure: String?
    @Published private(set) var downloading = false

    private var session: URLSession!
    private var queue: [Item] = []
    private var current: Item?
    private var doneBytes: Int64 = 0
    private let totalBytes = items.reduce(0) { $0 + $1.approxBytes }

    nonisolated static var dir: URL {
        let d = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("models", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }
    nonisolated static func path(_ name: String) -> URL { dir.appendingPathComponent(name) }
    var modelPath: String { Self.path(Self.items[0].id).path }
    var mmprojPath: String { Self.path(Self.items[1].id).path }

    override init() {
        super.init()
        session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        refresh()
    }

    private func refresh() {
        isReady = Self.items.allSatisfy { item in
            let size = (try? FileManager.default.attributesOfItem(atPath: Self.path(item.id).path)[.size] as? Int64) ?? 0
            return size >= item.approxBytes * 99 / 100
        }
        if isReady { status = "Ready" }
    }

    func start() {
        guard !downloading else { return }
        failure = nil
        downloading = true
        doneBytes = 0
        queue = Self.items.filter { !FileManager.default.fileExists(atPath: Self.path($0.id).path) }
        for item in Self.items where !queue.contains(where: { $0.id == item.id }) { doneBytes += item.approxBytes }
        next()
    }

    private func next() {
        guard let item = queue.first else { downloading = false; refresh(); return }
        queue.removeFirst()
        current = item
        status = "Downloading \(item.id)"
        session.downloadTask(with: item.url).resume()
    }

    nonisolated func urlSession(_ s: URLSession, downloadTask t: URLSessionDownloadTask, didWriteData _: Int64,
                                totalBytesWritten written: Int64, totalBytesExpectedToWrite _: Int64) {
        Task { @MainActor in
            self.progress = min(1, Double(self.doneBytes + written) / Double(self.totalBytes))
        }
    }

    nonisolated func urlSession(_ s: URLSession, downloadTask t: URLSessionDownloadTask, didFinishDownloadingTo tmp: URL) {
        // Move before this returns: the system deletes `tmp` afterwards.
        let name = t.originalRequest?.url?.lastPathComponent ?? "model.gguf"
        let dest = ModelStore.path(name)
        var err: String?
        if let http = t.response as? HTTPURLResponse, http.statusCode != 200 {
            err = "Download failed (HTTP \(http.statusCode))"
        } else {
            try? FileManager.default.removeItem(at: dest)
            do {
                try FileManager.default.moveItem(at: tmp, to: dest)
                var u = dest
                var rv = URLResourceValues(); rv.isExcludedFromBackup = true
                try? u.setResourceValues(rv)
            } catch { err = error.localizedDescription }
        }
        Task { @MainActor in
            if let err { self.failure = err; self.downloading = false; return }
            self.doneBytes += self.current?.approxBytes ?? 0
            self.next()
        }
    }

    nonisolated func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error else { return }
        Task { @MainActor in self.failure = error.localizedDescription; self.downloading = false }
    }
}
