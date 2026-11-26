/** In-place iterative radix-2 FFT. `re` and `im` must have the same power-of-two length. */
export function fft(re: Float64Array, im: Float64Array): void {
  const n = re.length;
  if (n !== im.length || (n & (n - 1)) !== 0) throw new Error("FFT length must be a power of two");

  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }

  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wRe = Math.cos(ang);
    const wIm = Math.sin(ang);
    const half = len >> 1;
    for (let i = 0; i < n; i += len) {
      let curRe = 1;
      let curIm = 0;
      for (let k = 0; k < half; k++) {
        const aRe = re[i + k + half] * curRe - im[i + k + half] * curIm;
        const aIm = re[i + k + half] * curIm + im[i + k + half] * curRe;
        re[i + k + half] = re[i + k] - aRe;
        im[i + k + half] = im[i + k] - aIm;
        re[i + k] += aRe;
        im[i + k] += aIm;
        const nextRe = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
      }
    }
  }
}

export function ifft(re: Float64Array, im: Float64Array): void {
  for (let i = 0; i < im.length; i++) im[i] = -im[i];
  fft(re, im);
  const n = re.length;
  for (let i = 0; i < n; i++) {
    re[i] /= n;
    im[i] = -im[i] / n;
  }
}

/**
 * Welch amplitude spectrum: Hann-windowed segments (50 % overlap), averaged power,
 * returned as single-sided amplitude in g. Bin k is at k * fs / segLen Hz.
 */
export function welchAmplitude(signal: Float64Array, fs: number, segLen = 2048): { freqs: Float64Array; amp: Float64Array } {
  const hop = segLen >> 1;
  const hann = new Float64Array(segLen);
  let hannSum = 0;
  for (let i = 0; i < segLen; i++) {
    hann[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (segLen - 1));
    hannSum += hann[i];
  }
  const bins = segLen / 2 + 1;
  const power = new Float64Array(bins);
  let segments = 0;
  const re = new Float64Array(segLen);
  const im = new Float64Array(segLen);
  for (let start = 0; start + segLen <= signal.length; start += hop) {
    for (let i = 0; i < segLen; i++) {
      re[i] = signal[start + i] * hann[i];
      im[i] = 0;
    }
    fft(re, im);
    for (let k = 0; k < bins; k++) power[k] += re[k] * re[k] + im[k] * im[k];
    segments++;
  }
  const amp = new Float64Array(bins);
  const freqs = new Float64Array(bins);
  for (let k = 0; k < bins; k++) {
    // single-sided amplitude, corrected for the window's coherent gain
    const scale = k === 0 || k === bins - 1 ? 1 : 2;
    amp[k] = (scale * Math.sqrt(power[k] / Math.max(segments, 1))) / hannSum;
    freqs[k] = (k * fs) / segLen;
  }
  return { freqs, amp };
}
