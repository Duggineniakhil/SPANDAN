"""What the phone does to each window, in Python: features (contract C1, `frontend/src/lib/features.ts`)
and the v0 z-score detector (`frontend/src/lib/detector.ts`). The replay tool sends the cloud exactly
what a phone would, so the cloud can't tell a replay from a phone.

Keep in step with the TypeScript files; `tests/test_replay.py` checks the definitions on known signals.
"""
from dataclasses import dataclass, field

import numpy as np

MODEL_VERSION = "zscore-replay-v0"
BANDS = [(0, 25), (25, 75), (75, 150), (150, 300), (300, 600), (600, 1000), (1000, 1600)]
BPFO_RATIO = 3.585  # 6205 bearing, as on the phone
SIGNED = {"skew_y"}


# ---------- features (C1) ----------

def welch_amplitude(signal: np.ndarray, fs: float, seg_len: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided amplitude spectrum, Hann window, 50 % overlap, coherent-gain corrected (fft.ts)."""
    hop = seg_len // 2
    i = np.arange(seg_len)
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * i / (seg_len - 1))
    starts = range(0, len(signal) - seg_len + 1, hop)
    bins = seg_len // 2 + 1
    power = np.zeros(bins)
    n = 0
    for s in starts:
        spec = np.fft.rfft(signal[s:s + seg_len] * hann)
        power += spec.real ** 2 + spec.imag ** 2
        n += 1
    scale = np.full(bins, 2.0)
    scale[0] = scale[-1] = 1.0
    amp = scale * np.sqrt(power / max(n, 1)) / hann.sum()
    return np.arange(bins) * fs / seg_len, amp


def _moment(a: np.ndarray, k: int) -> float:
    d = a - a.mean()
    m2 = float(np.mean(d * d))
    return 0.0 if m2 == 0 else float(np.mean(d ** k)) / m2 ** (k / 2)


def _amp_at(freqs: np.ndarray, amp: np.ndarray, f: float, tol: float = 1.5) -> float:
    m = np.abs(freqs - f) <= tol
    return float(amp[m].max()) if m.any() else 0.0


def _envelope(signal: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    n = 1 << int(np.ceil(np.log2(len(signal))))
    spec = np.fft.fft(signal, n)
    f = np.arange(n) * fs / n
    keep = (np.arange(n) > 0) & (np.arange(n) < n / 2) & (f >= lo) & (f <= hi)
    spec = np.where(keep, 2 * spec, 0)
    return np.abs(np.fft.ifft(spec))[: len(signal)]


def phone_features(x: np.ndarray, y: np.ndarray, z: np.ndarray, fs: float, rpm: float) -> tuple[dict, float]:
    """(features, rpm estimate) for one window, as the phone computes them."""
    x, y, z = (np.asarray(a, dtype=float) - np.mean(a) for a in (x, y, z))
    rms = lambda a: float(np.sqrt(np.mean(a * a)))  # noqa: E731
    f: dict[str, float] = {"rms_x": rms(x), "rms_y": rms(y), "rms_z": rms(z), "peak_y": float(np.max(np.abs(y)))}
    f["crest_y"] = f["peak_y"] / f["rms_y"] if f["rms_y"] > 0 else 0.0
    f["kurtosis_x"], f["kurtosis_y"], f["skew_y"] = _moment(x, 4), _moment(y, 4), _moment(y, 3)

    freqs, amp = welch_amplitude(y, fs)
    for lo, hi in BANDS:
        m = (freqs >= lo) & (freqs < hi)
        f[f"band_{lo}_{hi}_y"] = float(np.sqrt(np.sum(amp[m] ** 2)))
    m = (freqs >= 15) & (freqs <= 55)
    rpm_est = float(freqs[m][np.argmax(amp[m])] * 60) if m.any() and amp[m].max() > 0 else float(rpm)
    f1 = rpm_est / 60
    f["amp_1x_y"], f["amp_2x_y"], f["amp_3x_y"] = (_amp_at(freqs, amp, k * f1) for k in (1, 2, 3))
    p = amp[1:] ** 2 + 1e-20
    f["spectral_centroid_y"] = float(np.sum(freqs[1:] * p) / np.sum(p))
    f["spectral_flatness_y"] = float(np.exp(np.mean(np.log(p))) / np.mean(p))
    env = _envelope(y, fs, 500, 1500)
    f["env_rms_y"] = rms(env)
    ef, ea = welch_amplitude(env - env.mean(), fs)
    f["env_bpfo_y"] = _amp_at(ef, ea, BPFO_RATIO * f1, 3)
    return f, rpm_est


# ---------- detector (z-score v0) ----------

def _vector(f: dict, names: list[str]) -> np.ndarray:
    return np.array([f[n] if n in SIGNED else np.log(abs(f[n]) + 1e-6) for n in names])


def _percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(np.ceil(p / 100 * len(s))) - 1))]


@dataclass
class Baseline:
    names: list[str]
    mean: np.ndarray
    std: np.ndarray
    p50: float = 0.0
    threshold: float = 0.0

    def score(self, f: dict) -> float:
        return float(np.mean(((_vector(f, self.names) - self.mean) / self.std) ** 2))

    def health(self, s: float, k: float = 3) -> float:
        """100 = like the baseline, 0 = far beyond the threshold."""
        return 100 * min(1.0, max(0.0, 1 - (s - self.p50) / (k * (self.threshold - self.p50))))


def fit_baseline(samples: list[dict]) -> Baseline:
    if len(samples) < 5:
        raise ValueError("need at least 5 baseline windows")
    names = sorted(samples[0])
    vecs = np.array([_vector(s, names) for s in samples])
    b = Baseline(names, vecs.mean(axis=0), np.maximum(vecs.std(axis=0, ddof=1), 0.05))
    scores = [b.score(s) for s in samples]
    b.p50 = _percentile(scores, 50)
    b.threshold = max(_percentile(scores, 99.5) * 2, b.p50 * 6)
    return b


@dataclass
class AlertRule:
    """Raise after `need` readings in a row over the threshold; clear after `need` under 0.8 × it."""
    need: int = 3
    active: bool = False
    _over: int = field(default=0, repr=False)
    _under: int = field(default=0, repr=False)

    def update(self, score: float, threshold: float) -> str | None:
        if score > threshold:
            self._over, self._under = self._over + 1, 0
        else:
            self._under = self._under + 1 if score < 0.8 * threshold else 0
            self._over = 0
        if not self.active and self._over >= self.need:
            self.active = True
            return "raised"
        if self.active and self._under >= self.need:
            self.active = False
            return "cleared"
        return None
