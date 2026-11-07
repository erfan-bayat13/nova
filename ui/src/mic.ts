// Microphone loudness for the orb while listening. Returns null if the mic is unavailable.
export async function startMic(): Promise<(() => number) | null> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ac = new AudioContext();
    const an = ac.createAnalyser();
    an.fftSize = 512;
    ac.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    return () => {
      an.getFloatTimeDomainData(buf);
      let s = 0;
      for (const v of buf) s += v * v;
      return Math.min(1, Math.sqrt(s / buf.length) * 6);
    };
  } catch {
    return null;
  }
}
