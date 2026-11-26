/**
 * Per-machine anomaly detector (doc 04 §5–6).
 *
 * v0 uses a standardised-distance score (mean squared z-score of log features) learned
 * during the baseline. It has the same interface the TFLite autoencoder will have:
 * fit on normal windows → score → threshold → health index.
 */
import type { Features } from "./features";

export const MODEL_VERSION = "zscore-web-v0";

export interface Baseline {
  names: string[];
  mean: number[];
  std: number[];
  p50: number;
  threshold: number;
}

// Magnitudes are compared on a log scale; signed features (which cross zero) stay linear.
const SIGNED = new Set(["skew_y"]);
const toVector = (f: Features, names: string[]) =>
  names.map((n) => (SIGNED.has(n) ? f[n] : Math.log(Math.abs(f[n]) + 1e-6)));

function percentile(values: number[], p: number): number {
  const s = [...values].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1));
  return s[idx];
}

export function fitBaseline(samples: Features[]): Baseline {
  if (samples.length < 5) throw new Error("Need at least 5 baseline windows");
  const names = Object.keys(samples[0]).sort();
  const vecs = samples.map((s) => toVector(s, names));
  const mean = names.map((_, j) => vecs.reduce((a, v) => a + v[j], 0) / vecs.length);
  const std = names.map((_, j) => {
    const v = vecs.reduce((a, x) => a + (x[j] - mean[j]) ** 2, 0) / (vecs.length - 1);
    return Math.max(Math.sqrt(v), 0.05); // floor so near-constant features don't explode
  });
  const partial: Baseline = { names, mean, std, p50: 0, threshold: 0 };
  const scores = samples.map((s) => score(partial, s));
  const p50 = percentile(scores, 50);
  // In-sample scores underestimate the spread of new healthy readings (the baseline is
  // only ~30 windows), so the threshold gets a wide margin. Faults score 10–100× higher.
  const threshold = Math.max(percentile(scores, 99.5) * 2, p50 * 6);
  return { ...partial, p50, threshold };
}

export function score(b: Baseline, f: Features): number {
  const v = toVector(f, b.names);
  let s = 0;
  for (let j = 0; j < v.length; j++) s += ((v[j] - b.mean[j]) / b.std[j]) ** 2;
  return s / v.length;
}

/** 100 = like baseline, 0 = far beyond the threshold (k = 3, doc 04 §5). */
export function healthIndex(b: Baseline, s: number, k = 3): number {
  const h = 1 - (s - b.p50) / (k * (b.threshold - b.p50));
  return 100 * Math.min(1, Math.max(0, h));
}

/** Top contributing features, for explaining an alert. */
export function topContributors(b: Baseline, f: Features, n = 3): { name: string; z: number }[] {
  const v = toVector(f, b.names);
  return b.names
    .map((name, j) => ({ name, z: (v[j] - b.mean[j]) / b.std[j] }))
    .sort((a, c) => Math.abs(c.z) - Math.abs(a.z))
    .slice(0, n);
}

/** Raise after `need` consecutive windows over threshold; clear after `need` below 0.8 × threshold. */
export class AlertRule {
  private over = 0;
  private under = 0;
  active = false;

  constructor(private readonly need = 3) {}

  update(scoreValue: number, threshold: number): "raised" | "cleared" | null {
    if (scoreValue > threshold) {
      this.over++;
      this.under = 0;
    } else {
      this.under = scoreValue < 0.8 * threshold ? this.under + 1 : 0;
      this.over = 0;
    }
    if (!this.active && this.over >= this.need) {
      this.active = true;
      return "raised";
    }
    if (this.active && this.under >= this.need) {
      this.active = false;
      return "cleared";
    }
    return null;
  }
}

export function ema(prev: number | null, value: number, alpha = 0.3): number {
  return prev === null ? value : prev + alpha * (value - prev);
}
