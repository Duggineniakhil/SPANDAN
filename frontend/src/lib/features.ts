/**
 * Feature extraction (contract C1, doc 04 §4). Same definitions will be used in the
 * Python training code and, later, the Android app.
 */
import { fft, ifft, welchAmplitude } from "./fft";
import { BPFO_RATIO, type Window } from "./signal";

export const BANDS: [number, number][] = [
  [0, 25], [25, 75], [75, 150], [150, 300], [300, 600], [600, 1000], [1000, 1600],
];

export type Features = Record<string, number>;

function demean(a: Float64Array): Float64Array {
  let mean = 0;
  for (const v of a) mean += v;
  mean /= a.length;
  const out = new Float64Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = a[i] - mean;
  return out;
}

export function rms(a: Float64Array): number {
  let s = 0;
  for (const v of a) s += v * v;
  return Math.sqrt(s / a.length);
}

export function peak(a: Float64Array): number {
  let p = 0;
  for (const v of a) p = Math.max(p, Math.abs(v));
  return p;
}

/** Standardised moment of order `k` (3 = skewness, 4 = kurtosis; Gaussian kurtosis = 3). */
export function moment(a: Float64Array, k: 3 | 4): number {
  let mean = 0;
  for (const v of a) mean += v;
  mean /= a.length;
  let m2 = 0;
  let mk = 0;
  for (const v of a) {
    const d = v - mean;
    m2 += d * d;
    mk += d ** k;
  }
  m2 /= a.length;
  mk /= a.length;
  return m2 === 0 ? 0 : mk / m2 ** (k / 2);
}

/** Peak amplitude within ±tol Hz of `f`. */
function ampAt(freqs: Float64Array, amp: Float64Array, f: number, tol = 1.5): number {
  let best = 0;
  for (let k = 0; k < freqs.length; k++) {
    if (Math.abs(freqs[k] - f) <= tol) best = Math.max(best, amp[k]);
  }
  return best;
}

/** RMS of the envelope of `signal` band-passed to [lo, hi] Hz (FFT mask + analytic signal). */
export function envelope(signal: Float64Array, fs: number, lo: number, hi: number): Float64Array {
  let n = 1;
  while (n < signal.length) n <<= 1;
  const re = new Float64Array(n);
  const im = new Float64Array(n);
  re.set(signal);
  fft(re, im);
  // Keep positive frequencies in band, doubled; zero the rest → analytic band-passed signal.
  for (let k = 0; k < n; k++) {
    const f = (k * fs) / n;
    const keep = k > 0 && k < n / 2 && f >= lo && f <= hi;
    if (keep) {
      re[k] *= 2;
      im[k] *= 2;
    } else {
      re[k] = 0;
      im[k] = 0;
    }
  }
  ifft(re, im);
  const env = new Float64Array(signal.length);
  for (let i = 0; i < signal.length; i++) env[i] = Math.hypot(re[i], im[i]);
  return env;
}

export interface Spectrum {
  freqs: Float64Array;
  amp: Float64Array;
}

export interface FeatureResult {
  features: Features;
  spectrum: Spectrum; // Y axis, for display
  envSpectrum: Spectrum; // envelope spectrum of Y, shows bearing fault frequencies
  rpmEstimate: number;
}

export function extractFeatures(w: Window): FeatureResult {
  const x = demean(w.x);
  const y = demean(w.y);
  const z = demean(w.z);
  const f: Features = {};

  f.rms_x = rms(x);
  f.rms_y = rms(y);
  f.rms_z = rms(z);
  f.peak_y = peak(y);
  f.crest_y = f.rms_y > 0 ? f.peak_y / f.rms_y : 0;
  f.kurtosis_x = moment(x, 4);
  f.kurtosis_y = moment(y, 4);
  f.skew_y = moment(y, 3);

  const spectrum = welchAmplitude(y, w.fs);
  const { freqs, amp } = spectrum;
  for (const [lo, hi] of BANDS) {
    let e = 0;
    for (let k = 0; k < freqs.length; k++) if (freqs[k] >= lo && freqs[k] < hi) e += amp[k] * amp[k];
    f[`band_${lo}_${hi}_y`] = Math.sqrt(e);
  }

  // Shaft speed: strongest peak in 15–55 Hz, else nameplate rpm
  let rpmEstimate = w.rpm;
  let best = 0;
  for (let k = 0; k < freqs.length; k++) {
    if (freqs[k] >= 15 && freqs[k] <= 55 && amp[k] > best) {
      best = amp[k];
      rpmEstimate = freqs[k] * 60;
    }
  }
  const f1 = rpmEstimate / 60;
  f.amp_1x_y = ampAt(freqs, amp, f1);
  f.amp_2x_y = ampAt(freqs, amp, 2 * f1);
  f.amp_3x_y = ampAt(freqs, amp, 3 * f1);

  let num = 0;
  let den = 0;
  let logSum = 0;
  for (let k = 1; k < freqs.length; k++) {
    const p = amp[k] * amp[k] + 1e-20;
    num += freqs[k] * p;
    den += p;
    logSum += Math.log(p);
  }
  f.spectral_centroid_y = num / den;
  f.spectral_flatness_y = Math.exp(logSum / (freqs.length - 1)) / (den / (freqs.length - 1));

  const env = envelope(y, w.fs, 500, 1500);
  f.env_rms_y = rms(env);
  const envSpectrum = welchAmplitude(demean(env), w.fs);
  f.env_bpfo_y = ampAt(envSpectrum.freqs, envSpectrum.amp, BPFO_RATIO * f1, 3);

  return { features: f, spectrum, envSpectrum, rpmEstimate };
}
