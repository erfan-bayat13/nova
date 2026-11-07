// "Eyes on request": one still frame from the webcam (here) or the screen (desktop/main.cjs, over IPC).
// Frames are encoded in memory, sent once as a `see` message, and dropped. Nothing is written to disk.

export type Source = 'camera' | 'screen';

const MAX_SIDE = 1024;                 // longest side in pixels
const MAX_B64 = 1.5 * 1024 * 1024;     // the base64 image must stay under 1.5 MB
const QUALITY = 0.7;

/** Draws a frame scaled so its longest side is <= MAX_SIDE, returns base64 JPEG (no data: prefix). */
function encode(src: CanvasImageSource, w: number, h: number): string {
  const k = Math.min(1, MAX_SIDE / Math.max(w, h));
  const cv = document.createElement('canvas');
  cv.width = Math.round(w * k);
  cv.height = Math.round(h * k);
  cv.getContext('2d')!.drawImage(src, 0, 0, cv.width, cv.height);
  let url = '';
  for (const q of [QUALITY, 0.5, 0.35]) {
    url = cv.toDataURL('image/jpeg', q);
    if (url.length <= MAX_B64) break;
  }
  return url.slice(url.indexOf(',') + 1);
}

/**
 * Opens the webcam, grabs one frame after the exposure settles, and closes the camera again.
 * `alive` is checked after every await: if the user cancelled (pressed the orb), the stream is
 * closed right away and null comes back.
 */
export async function grabCamera(alive: () => boolean): Promise<string | null> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
  });
  try {
    if (!alive()) return null;
    const v = document.createElement('video');
    v.muted = true;
    v.playsInline = true;
    v.srcObject = stream;
    await v.play();
    await new Promise((r) => setTimeout(r, 400)); // let auto-exposure settle
    if (!alive() || !v.videoWidth) return null;
    return encode(v, v.videoWidth, v.videoHeight);
  } finally {
    stream.getTracks().forEach((t) => t.stop()); // the camera light goes off here
  }
}
