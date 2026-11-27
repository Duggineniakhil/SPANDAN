"""Window sources for the replay tool (the server-side twin of the phone's `WindowSource`).

C4 window format (doc 10, contract C4), one folder per session:

    <session>/meta.json        {"format": "spandan-c4", "version": 1, "unit": "...", "session": "...",
                                "fs": 3200, "rpm": 2880, "scale_g": 0.0039, "bearing_model": "6205-2RS",
                                "interval_s": 60, "windows": [{"file": "w0000.npy", "label": "normal",
                                                               "severity": 0.0}, ...]}
    <session>/w0000.npy        int16 [N × 3] (x, y, z); g = counts × scale_g. y = the radial axis.

`scale_g` 0.0039 g/LSB is the ADXL345 at full resolution, so the hardware sensor writes the same files.
Labels are "normal" or a fault name; `severity` (0–1) is optional. CWRU / IMS converters are in
`ml/spandan_ml/c4.py`.
"""
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.sim.vibration import FAULTS, generate_window

FORMAT = "spandan-c4"
ADXL345_G_PER_LSB = 0.0039


@dataclass
class ReplayWindow:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    fs: int
    rpm: float
    label: str = "normal"
    severity: float | None = None


# ---------- C4 files ----------

def write_session(folder: str | Path, windows: list[ReplayWindow], *, unit: str, session: str,
                  bearing_model: str = "6205-2RS", interval_s: float = 60,
                  scale_g: float = ADXL345_G_PER_LSB, extra: dict | None = None) -> Path:
    """Write windows as a C4 session (int16 counts, clipped to the int16 range)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, w in enumerate(windows):
        counts = np.stack([w.x, w.y, w.z], axis=1) / scale_g
        name = f"w{i:04d}.npy"
        np.save(folder / name, np.clip(np.round(counts), -32768, 32767).astype("<i2"))
        entries.append({"file": name, "label": w.label,
                        **({"severity": round(float(w.severity), 4)} if w.severity is not None else {})})
    first = windows[0]
    meta = {"format": FORMAT, "version": 1, "unit": unit, "session": session, "fs": first.fs, "rpm": first.rpm,
            "scale_g": scale_g, "bearing_model": bearing_model, "interval_s": interval_s, "windows": entries,
            **(extra or {})}
    (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return folder


def read_meta(folder: str | Path) -> dict:
    meta = json.loads((Path(folder) / "meta.json").read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT:
        raise ValueError(f"{folder}: not a {FORMAT} session")
    return meta


def c4_windows(folder: str | Path) -> Iterator[ReplayWindow]:
    folder = Path(folder)
    meta = read_meta(folder)
    scale = float(meta.get("scale_g", ADXL345_G_PER_LSB))
    for e in meta["windows"]:
        a = np.load(folder / e["file"], allow_pickle=False)
        if a.ndim != 2 or a.shape[1] != 3:
            raise ValueError(f"{e['file']}: expected [N x 3], got {a.shape}")
        g = a.astype(float) * scale
        yield ReplayWindow(g[:, 0], g[:, 1], g[:, 2], int(meta["fs"]), float(e.get("rpm", meta["rpm"])),
                           e.get("label", "normal"), e.get("severity"))


# ---------- simulated run to failure ----------

def sim_run_to_failure(fault: str, *, normal: int = 40, developing: int = 60, rpm: float = 2880,
                       seconds: float = 10, seed: int = 0, repaired: int = 0) -> Iterator[ReplayWindow]:
    """`normal` healthy windows, then the fault growing to failure over `developing` windows
    (severity rises exponentially, as wear does), then `repaired` healthy windows after a repair."""
    if fault not in FAULTS:
        raise ValueError(f"fault must be one of {FAULTS}")
    rng = np.random.default_rng(seed)

    def win(f: str, sev: float) -> ReplayWindow:
        w = generate_window(f, sev, rpm=rpm * (1 + 0.003 * rng.standard_normal()), seconds=seconds,
                            seed=int(rng.integers(1 << 31)))
        return ReplayWindow(w.x, w.y, w.z, w.fs, w.rpm, "normal" if f == "none" else f, w.severity)

    for _ in range(normal):
        yield win("none", 0.0)
    for i in range(developing):
        # 0.02 → 1.0, slow at first then fast
        sev = 0.02 * np.exp(np.log(50) * (i + 1) / developing) if fault != "none" else 0.0
        yield win(fault, float(min(sev, 1.0)))
    for _ in range(repaired):
        yield win("none", 0.0)


def open_source(spec: str, **sim_args) -> tuple[Iterator[ReplayWindow], dict]:
    """`sim:<fault>` or a C4 session folder. Returns (windows, info)."""
    if spec.startswith("sim:"):
        fault = spec[4:]
        return sim_run_to_failure(fault, **sim_args), {"unit": f"sim-{fault}", "session": spec,
                                                       "bearing_model": "6205-2RS", "rpm": sim_args.get("rpm", 2880)}
    meta = read_meta(spec)
    return c4_windows(spec), {k: meta.get(k) for k in ("unit", "session", "bearing_model", "rpm", "fs")}
