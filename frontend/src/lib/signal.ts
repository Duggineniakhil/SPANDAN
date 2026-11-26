/**
 * Simulated clip-on accelerometer (stands in for the ESP32 + ADXL345 sensor until
 * the hardware exists). Produces 3-axis windows in g, sampled like the real sensor.
 *
 * Physics used (doc 03 §3): shaft 1× and 2×, 100 Hz electrical line, broadband noise,
 * and for an outer-race defect, impacts at BPFO that ring a ~1.2 kHz structural resonance.
 */
export const FS = 3200; // Hz, ADXL345 max output data rate
export const WINDOW_SECONDS = 2; // demo windows (the real sensor uses 10 s)
export const WINDOW_SAMPLES = FS * WINDOW_SECONDS;

export type FaultType = "none" | "imbalance" | "bearing_outer" | "looseness";

export const FAULT_LABELS: Record<FaultType, string> = {
  none: "Healthy",
  imbalance: "Imbalance",
  bearing_outer: "Bearing outer-race wear",
  looseness: "Mechanical looseness",
};

/** 6205 bearing: BPFO ≈ 3.585 × shaft frequency. */
export const BPFO_RATIO = 3.585;

export interface Window {
  x: Float64Array;
  y: Float64Array; // radial — most sensitive axis
  z: Float64Array; // axial
  fs: number;
  rpm: number;
}

function gaussian(rand: () => number): number {
  // Box–Muller
  let u = 0;
  while (u === 0) u = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

/** Small seeded PRNG (mulberry32) so tests are repeatable. */
export function makeRng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * @param severity 0 (healthy) … 1 (about to fail)
 */
export function generateWindow(
  fault: FaultType,
  severity: number,
  rpm = 2880,
  rand: () => number = Math.random,
): Window {
  const n = WINDOW_SAMPLES;
  const f1 = rpm / 60;
  const s = Math.max(0, Math.min(1, severity));
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  const z = new Float64Array(n);

  // Load wobble: real machines are never perfectly steady
  const load = 1 + 0.04 * gaussian(rand);
  const phase1 = rand() * 2 * Math.PI;
  const phase2 = rand() * 2 * Math.PI;

  const a1 = 0.05 * load * (fault === "imbalance" ? 1 + 7 * s : 1);
  const a2 = 0.015 * (fault === "looseness" ? 1 + 6 * s : 1);
  const looseHarmonics = fault === "looseness" ? 0.03 * s : 0;
  const noise = 0.02 * (fault === "looseness" ? 1 + 1.5 * s : 1);

  for (let i = 0; i < n; i++) {
    const t = i / FS;
    let base =
      a1 * Math.sin(2 * Math.PI * f1 * t + phase1) +
      a2 * Math.sin(2 * Math.PI * 2 * f1 * t + phase2) +
      0.01 * Math.sin(2 * Math.PI * 100 * t);
    if (looseHarmonics > 0) {
      for (let h = 3; h <= 6; h++) base += (looseHarmonics / (h - 2)) * Math.sin(2 * Math.PI * h * f1 * t + h);
      // half-order component typical of looseness
      base += looseHarmonics * 0.6 * Math.sin(2 * Math.PI * 0.5 * f1 * t);
    }
    y[i] = base + noise * gaussian(rand);
    x[i] = 0.8 * base + noise * gaussian(rand);
    z[i] = 0.35 * base + 0.6 * noise * gaussian(rand);
  }

  if (fault === "bearing_outer" && s > 0) {
    // Repeating impacts at BPFO, each ringing a decaying resonance.
    const bpfo = BPFO_RATIO * f1;
    const resonance = 1200;
    const decay = 900; // 1/s — rings die out well before the next impact
    const impact = 0.9 * s * s + 0.15 * s;
    const ringLen = Math.floor(FS * 0.004);
    let tImpact = rand() / bpfo;
    while (tImpact < n / FS) {
      const start = Math.floor(tImpact * FS);
      const amp = impact * (0.7 + 0.6 * rand());
      for (let k = 0; k < ringLen && start + k < n; k++) {
        const tt = k / FS;
        const v = amp * Math.exp(-decay * tt) * Math.sin(2 * Math.PI * resonance * tt);
        y[start + k] += v;
        x[start + k] += 0.6 * v;
        z[start + k] += 0.25 * v;
      }
      // small slip jitter, as in real bearings
      tImpact += (1 / bpfo) * (1 + 0.01 * gaussian(rand));
    }
  }

  return { x, y, z, fs: FS, rpm };
}
