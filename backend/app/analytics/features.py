"""Window features for the diagnosis classifier: statistics + spectral bands (doc 04 §4, radial axis)
plus the physics rule measurements and scores (rules.py).

Used both for training (ml/spandan_ml imports this module) and live diagnosis, so the model always sees
features computed by the same code. Computed from raw windows on the server side; the phone's own
feature module (M1-07) is separate.
"""
import numpy as np
from scipy.stats import skew

from app.analytics.rules import score_window
from app.analytics.signal import amplitude_spectrum, envelope, kurtosis

BANDS = [(0, 25), (25, 75), (75, 150), (150, 300), (300, 600), (600, 1000), (1000, 1600)]

# Kept for reports but not given to the classifier: absolute levels depend on the machine, sensor
# mounting and (in CWRU) on the recording rate. CWRU's normal data was recorded at a different rate
# than its fault data, so after resampling its noise floor differs, and a model could learn that
# instead of the fault physics. Speed would leak the motor load. Only scale-free features are used.
NOT_FOR_MODEL = {"rms", "peak", "env_rms", "amp_1x", "amp_2x", "amp_3x", "shaft_hz"}


def windows(x: np.ndarray, fs: int, seconds: float = 2.0, hop_seconds: float = 1.0) -> list[np.ndarray]:
    n, hop = int(fs * seconds), int(fs * hop_seconds)
    return [x[i:i + n] for i in range(0, len(x) - n + 1, hop)]


def window_features(y: np.ndarray, fs: int, *, rpm: float, bearing_model: str) -> dict[str, float]:
    y = np.asarray(y, dtype=float) - np.mean(y)
    rms = float(np.sqrt(np.mean(y * y)))
    peak = float(np.max(np.abs(y)))
    spec = amplitude_spectrum(y, fs)
    total = float(np.sum(spec.amp ** 2)) or 1e-12
    f: dict[str, float] = {
        "rms": rms, "peak": peak, "crest": peak / rms if rms else 0.0,
        "kurtosis": kurtosis(y), "skew": float(skew(y)),
        "env_rms": float(np.sqrt(np.mean(envelope(y, fs) ** 2))),
        "spectral_centroid": float(np.sum(spec.freqs * spec.amp ** 2) / total),
        "spectral_flatness": float(np.exp(np.mean(np.log(spec.amp ** 2 + 1e-20))) / np.mean(spec.amp ** 2 + 1e-20)),
    }
    for lo, hi in BANDS:
        m = (spec.freqs >= lo) & (spec.freqs < hi)
        f[f"band_{lo}_{hi}"] = float(np.sum(spec.amp[m] ** 2) / total)  # share of energy: scale-free
    report = score_window(y, fs, rpm=rpm, bearing_model=bearing_model)
    f.update({k: float(v) for k, v in report.features().items()})
    f["env_to_rms"] = f["env_rms"] / rms if rms else 0.0
    return f
