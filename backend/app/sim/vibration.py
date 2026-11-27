"""Simulated accelerometer windows for tests and server-side replay (Python port of the web simulator,
frontend/src/lib/signal.ts, extended with inner-race, ball and misalignment faults).

Physics: shaft 1× and 2×, 100 Hz electrical line, broadband noise; bearing defects are impacts at the
defect frequency that ring a ~1.2 kHz structural resonance. Inner-race impacts are amplitude-modulated
at shaft speed (the defect rotates through the load zone); ball impacts at 2×BSF are modulated at the
cage frequency.
"""
from dataclasses import dataclass

import numpy as np

from app.analytics.bearings import fault_orders, lookup

FS = 3200  # Hz, ADXL345 max output data rate
FAULTS = ("none", "imbalance", "misalignment", "looseness", "bearing_outer", "bearing_inner", "bearing_ball")


@dataclass
class SimWindow:
    x: np.ndarray
    y: np.ndarray  # radial, most sensitive axis
    z: np.ndarray  # axial
    fs: int
    rpm: float
    fault: str
    severity: float


def _impacts(n: int, fs: int, rate_hz: float, amp: float, rng: np.random.Generator,
             mod_hz: float | None = None, mod_depth: float = 0.0) -> np.ndarray:
    """Impulse train at `rate_hz` with slip jitter, ringing a decaying resonance."""
    train = np.zeros(n)
    t = rng.random() / rate_hz
    while t < n / fs:
        a = amp * (0.7 + 0.6 * rng.random())
        if mod_hz:
            a *= (1 + mod_depth * np.cos(2 * np.pi * mod_hz * t)) / (1 + mod_depth)
        train[int(t * fs)] += a
        t += (1 / rate_hz) * (1 + 0.01 * rng.standard_normal())
    tt = np.arange(int(fs * 0.004)) / fs
    ring = np.exp(-900 * tt) * np.sin(2 * np.pi * 1200 * tt)
    return np.convolve(train, ring)[:n]


def generate_window(fault: str = "none", severity: float = 0.0, rpm: float = 2880, *, seconds: float = 10,
                    fs: int = FS, bearing: str = "6205", seed: int | None = None) -> SimWindow:
    if fault not in FAULTS:
        raise ValueError(f"fault must be one of {FAULTS}")
    rng = np.random.default_rng(seed)
    s = float(np.clip(severity, 0, 1)) if fault != "none" else 0.0
    n = int(fs * seconds)
    t = np.arange(n) / fs
    f1 = rpm / 60
    load = 1 + 0.04 * rng.standard_normal()

    a1 = 0.05 * load * (1 + 7 * s if fault == "imbalance" else 1)
    a2 = 0.015 * (1 + 6 * s if fault == "looseness" else 1 + 8 * s if fault == "misalignment" else 1)
    noise = 0.02 * (1 + 1.5 * s if fault == "looseness" else 1)
    base = (a1 * np.sin(2 * np.pi * f1 * t + rng.random() * 2 * np.pi)
            + a2 * np.sin(2 * np.pi * 2 * f1 * t + rng.random() * 2 * np.pi)
            + 0.01 * np.sin(2 * np.pi * 100 * t))
    if fault == "misalignment":
        base += 0.01 * s * np.sin(2 * np.pi * 3 * f1 * t)
    if fault == "looseness" and s > 0:
        h = 0.03 * s
        for k in range(3, 7):
            base += h / (k - 2) * np.sin(2 * np.pi * k * f1 * t + k)
        base += 0.6 * h * np.sin(2 * np.pi * 0.5 * f1 * t)  # half-order component

    y = base + noise * rng.standard_normal(n)
    x = 0.8 * base + noise * rng.standard_normal(n)
    z = (1.2 if fault == "misalignment" else 0.35) * base + 0.6 * noise * rng.standard_normal(n)

    if fault.startswith("bearing_") and s > 0:
        orders = fault_orders(lookup(bearing))
        amp = 0.9 * s * s + 0.15 * s
        if fault == "bearing_outer":
            v = _impacts(n, fs, orders.bpfo * f1, amp, rng)
        elif fault == "bearing_inner":
            v = _impacts(n, fs, orders.bpfi * f1, amp, rng, mod_hz=f1, mod_depth=0.8)
        else:
            v = _impacts(n, fs, 2 * orders.bsf * f1, amp * 0.8, rng, mod_hz=orders.ftf * f1, mod_depth=0.6)
        y += v
        x += 0.6 * v
        z += 0.25 * v
    return SimWindow(x, y, z, fs, rpm, fault, s)
