// Microphone: loudness for the orb, plus PCM16 16 kHz mono frames for the orchestrator
// (docs/PROTOCOL.md: binary frames between orb_down and orb_up).
//
// The AudioContext runs at the device rate (usually 48 kHz); we resample to 16 kHz here with
// linear interpolation, carrying the fractional position across chunks so there are no clicks.

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600; // 100 ms at 16 kHz → 3,200-byte binary frames

// Tiny worklet that forwards raw mic samples to the main thread.
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor('mic-tap', Tap);
`;

export type Mic = {
  level: () => number;                        // 0..1 loudness for the orb
  start: (sink: (frame: ArrayBuffer) => void) => void; // begin sending frames to sink
  stop: () => void;                           // flush the last partial frame, stop sending
};

export async function startMic(): Promise<Mic | null> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const ac = new AudioContext();
    const src = ac.createMediaStreamSource(stream);

    const an = ac.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    const buf = new Float32Array(an.fftSize);

    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
    await ac.audioWorklet.addModule(url);
    const tap = new AudioWorkletNode(ac, 'mic-tap');
    src.connect(tap);
    // a muted path to the destination keeps the worklet running in every browser
    const mute = ac.createGain();
    mute.gain.value = 0;
    tap.connect(mute).connect(ac.destination);

    const step = ac.sampleRate / TARGET_RATE; // input samples per output sample
    let sink: ((f: ArrayBuffer) => void) | null = null;
    let pos = 0;                               // fractional read position into `prev + chunk`
    let prev = 0;                              // last input sample of the previous chunk
    let out = new Int16Array(FRAME_SAMPLES);
    let n = 0;

    const push = (v: number) => {
      const s = Math.max(-1, Math.min(1, v));
      out[n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (n === FRAME_SAMPLES) {
        sink?.(out.buffer);
        out = new Int16Array(FRAME_SAMPLES);
        n = 0;
      }
    };

    tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
      if (!sink) return;
      const chunk = e.data;
      // virtual input = [prev, ...chunk]; index 0 is prev
      while (pos <= chunk.length - 1 + 1e-9) {
        const i = Math.floor(pos);
        const f = pos - i;
        const a = i === 0 ? prev : chunk[i - 1];
        const b = chunk[Math.min(i, chunk.length - 1)];
        push(a + (b - a) * f);
        pos += step;
      }
      pos -= chunk.length;
      prev = chunk[chunk.length - 1];
    };

    return {
      level: () => {
        an.getFloatTimeDomainData(buf);
        let s = 0;
        for (const v of buf) s += v * v;
        return Math.min(1, Math.sqrt(s / buf.length) * 6);
      },
      start: (fn) => {
        if (ac.state === 'suspended') void ac.resume();
        pos = 0; prev = 0; n = 0; out = new Int16Array(FRAME_SAMPLES);
        sink = fn;
      },
      stop: () => {
        if (sink && n > 0) sink(out.slice(0, n).buffer);
        sink = null;
        n = 0;
      },
    };
  } catch (err) {
    console.warn('mic unavailable', err);
    return null;
  }
}
