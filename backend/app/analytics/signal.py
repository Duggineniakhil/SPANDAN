"""Spectra for diagnosis: Welch amplitude spectrum and envelope (demodulated) spectrum."""
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps


@dataclass
class Spectrum:
    freqs: np.ndarray
    amp: np.ndarray  # peak amplitude per bin (a sine of amplitude A shows ≈ A)

    @property
    def resolution(self) -> float:
        return float(self.freqs[1] - self.freqs[0])

    def peak(self, f: float, tol_hz: float) -> tuple[float, float]:
        """Highest bin within f ± tol → (frequency, amplitude)."""
        tol = max(tol_hz, self.resolution)
        m = (self.freqs >= f - tol) & (self.freqs <= f + tol)
        if not m.any():
            return f, 0.0
        i = np.flatnonzero(m)[np.argmax(self.amp[m])]
        return float(self.freqs[i]), float(self.amp[i])

    def floor(self, lo: float, hi: float, exclude: list[tuple[float, float]] = ()) -> float:
        """Median amplitude in [lo, hi] (robust noise floor), leaving out the given ranges."""
        m = (self.freqs >= lo) & (self.freqs <= hi)
        for a, b in exclude:
            m &= ~((self.freqs >= a) & (self.freqs <= b))
        vals = self.amp[m]
        return float(np.median(vals)) if vals.size else float(np.median(self.amp))


def amplitude_spectrum(x: np.ndarray, fs: float, seg_seconds: float = 2.0) -> Spectrum:
    """Welch-averaged amplitude spectrum with a Hann window (doc 04 §4 uses the same idea on the phone)."""
    x = np.asarray(x, dtype=float) - np.mean(x)
    nper = min(len(x), int(fs * seg_seconds))
    f, p = sps.welch(x, fs=fs, window="hann", nperseg=nper, noverlap=nper // 2, scaling="spectrum", detrend=False)
    return Spectrum(f, np.sqrt(2 * p))


def envelope_band(fs: float) -> tuple[float, float]:
    """Default demodulation band: the phone's 500–1,500 Hz, kept below Nyquist."""
    return 500.0, min(1500.0, 0.45 * fs)


def envelope(x: np.ndarray, fs: float, band: tuple[float, float] | None = None) -> np.ndarray:
    lo, hi = band or envelope_band(fs)
    sos = sps.butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    xb = sps.sosfiltfilt(sos, np.asarray(x, dtype=float) - np.mean(x))
    return np.abs(sps.hilbert(xb))


def envelope_spectrum(x: np.ndarray, fs: float, band: tuple[float, float] | None = None,
                      seg_seconds: float = 2.0) -> Spectrum:
    """Spectrum of the envelope: repeating impacts (bearing defects) show as peaks at their rate."""
    return amplitude_spectrum(envelope(x, fs, band), fs, seg_seconds)


def estimate_shaft_hz(spec: Spectrum, nominal_hz: float | None) -> float:
    """Strongest peak near the nominal speed (±10 %), or in 15–55 Hz (motor 1×) if no nominal is known."""
    if nominal_hz:
        f, a = spec.peak(nominal_hz, 0.1 * nominal_hz)
        return f if a > 0 else nominal_hz
    m = (spec.freqs >= 15) & (spec.freqs <= 55)
    return float(spec.freqs[m][np.argmax(spec.amp[m])])


def kurtosis(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float) - np.mean(x)
    v = np.mean(x * x)
    return float(np.mean(x ** 4) / (v * v)) if v > 0 else 0.0
