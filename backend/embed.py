"""Small text embedder for memory retrieval. Optional: without one, retrieve.py falls back to keywords only.

Backends, first that works:
  1. a llama.cpp server started with --embeddings (EMBED_URL, default http://127.0.0.1:8081). Lightest: a 36 MB
     bge-small GGUF, ~100 MB of RAM next to the voice model.
        llama serve -hf ggml-org/bge-small-en-v1.5-Q8_0-GGUF --embeddings --pooling mean --port 8081
  2. sentence-transformers in this process (EMBED_MODEL, default all-MiniLM-L6-v2, 22 M parameters, ~18 ms a query).
     Heavier (torch), but it needs nothing else running.
EMBED_BACKEND=off disables both.
"""
from __future__ import annotations

import json, os, threading, urllib.request

import numpy as np

URL = os.environ.get("EMBED_URL", "http://127.0.0.1:8081")
MODEL = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


class Embedder:
    def __init__(self):
        self.name = ""             # tag stored next to each vector, so a model change never mixes vectors
        self._st = None
        self._lock = threading.Lock()
        self._ready: bool | None = None

    def start(self) -> bool:
        """Pick a backend (may take seconds for torch: call it off the voice path). True if one works."""
        with self._lock:
            if self._ready is not None:
                return self._ready
            self._ready = False
            if os.environ.get("EMBED_BACKEND", "") == "off":
                return False
            try:
                with urllib.request.urlopen(f"{URL}/health", timeout=1):
                    pass
                self.name, self._ready = f"llama:{URL}", True
                self._llama(["warmup"])
                return True
            except Exception:
                pass
            try:
                from sentence_transformers import SentenceTransformer
                self._st = SentenceTransformer(MODEL)
                self.name, self._ready = f"st:{MODEL}", True
            except Exception:
                self._ready = False
            return self._ready

    @property
    def available(self) -> bool:
        return bool(self._ready)

    def _llama(self, texts: list[str]) -> np.ndarray:
        req = urllib.request.Request(f"{URL}/v1/embeddings", json.dumps({"input": texts, "model": "embed"}).encode(),
                                     {"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            vecs = [d["embedding"] for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]
        return _unit(np.array(vecs, dtype=np.float32))

    def encode(self, texts: list[str]) -> np.ndarray | None:
        """Unit-length float32 vectors, one row per text, or None if no backend."""
        if not texts or not self.start():
            return None
        try:
            if self._st is not None:
                return _unit(np.asarray(self._st.encode(texts, normalize_embeddings=False), dtype=np.float32))
            return self._llama(texts)
        except Exception:
            return None


def _unit(a: np.ndarray) -> np.ndarray:
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


def to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)
