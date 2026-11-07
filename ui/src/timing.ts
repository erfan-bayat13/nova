// Latency marks for the desktop orb. Each turn starts at the key release (`turnStart`), and every
// `mark` logs how many ms after that it happened. Read them in the orb's DevTools console
// (right-click the orb → Open DevTools), filter on "[timing]".

let t0 = 0;

export function turnStart() {
  t0 = performance.now();
}

export function mark(label: string) {
  console.log(`[timing] ${label}: +${(performance.now() - t0).toFixed(0)} ms`);
}
