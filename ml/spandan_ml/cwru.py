"""CWRU bearing data loader (M2-19).

Works with the common Kaggle mirrors (e.g. `sufian79/cwru-mat-full-dataset`, `esraakhaled299/cwru-data`):
files are named either by CWRU number (`105.mat`) or by fault (`IR007_0.mat`, `OR007@6_1.mat`,
`Normal_0.mat`). Labels come from the file name if it says the fault, else from the CWRU number stored
inside the file (`X105_DE_time`). Drive-end (DE) channel only; the DE bearing is an SKF 6205-2RS.

Every recording is one unit of the split: windows of one recording never end up in both train and test.
"""
import re
from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.signal import resample_poly

from spandan_ml import TARGET_FS

BEARING = "6205"
RPM_BY_LOAD = {0: 1797, 1: 1772, 2: 1750, 3: 1730}
CLASSES = ("normal", "bearing_inner", "bearing_outer", "bearing_ball")
_CODE = {"IR": "bearing_inner", "OR": "bearing_outer", "B": "bearing_ball", "NORMAL": "normal"}


def _blocks(start_numbers: list[int], label: str, size: str, fs: int, extra: str = "") -> dict[int, tuple]:
    """CWRU numbers come in runs of 4 (loads 0–3 HP)."""
    out = {}
    for first in start_numbers:
        for hp in range(4):
            out[first + hp] = (label, size + extra, hp, fs)
    return out


# CWRU file numbers → (label, fault size, load HP, fs). From the CWRU Bearing Data Center tables.
NUMBERS: dict[int, tuple] = {
    **{97 + hp: ("normal", "", hp, 48000) for hp in range(4)},  # normal baseline was recorded at 48 kHz
    # 12 kHz drive end
    **_blocks([105], "bearing_inner", "007", 12000), **_blocks([169], "bearing_inner", "014", 12000),
    **_blocks([209], "bearing_inner", "021", 12000), **_blocks([3001], "bearing_inner", "028", 12000),
    **_blocks([118], "bearing_ball", "007", 12000), **_blocks([185], "bearing_ball", "014", 12000),
    **_blocks([222], "bearing_ball", "021", 12000), **_blocks([3005], "bearing_ball", "028", 12000),
    **_blocks([130], "bearing_outer", "007", 12000, "@6"), **_blocks([197], "bearing_outer", "014", 12000, "@6"),
    **_blocks([234], "bearing_outer", "021", 12000, "@6"), **_blocks([144], "bearing_outer", "007", 12000, "@3"),
    **_blocks([246], "bearing_outer", "021", 12000, "@3"), **_blocks([156], "bearing_outer", "007", 12000, "@12"),
    **_blocks([258], "bearing_outer", "021", 12000, "@12"),
    # 48 kHz drive end
    **_blocks([109], "bearing_inner", "007", 48000), **_blocks([174], "bearing_inner", "014", 48000),
    **_blocks([213], "bearing_inner", "021", 48000),
    **_blocks([122], "bearing_ball", "007", 48000), **_blocks([189], "bearing_ball", "014", 48000),
    **_blocks([226], "bearing_ball", "021", 48000),
    **_blocks([135], "bearing_outer", "007", 48000, "@6"), **_blocks([201], "bearing_outer", "014", 48000, "@6"),
    **_blocks([238], "bearing_outer", "021", 48000, "@6"),
}

NAME = re.compile(r"^(?P<code>IR|OR|B|NORMAL)(?P<size>\d{3})?(?P<pos>@\d+)?[_-](?P<hp>[0-3])$", re.I)


@dataclass
class Recording:
    path: Path
    label: str
    fault_size: str
    load_hp: int
    rpm: float
    fs: int
    number: int | None
    key: str                 # variable name of the DE channel inside the .mat
    label_source: str        # "filename" | "cwru_number"

    @property
    def recording_id(self) -> str:
        return f"cwru-{self.number or self.path.stem}-{self.fs // 1000}k"


def _de_keys(mat: dict) -> dict[int, str]:
    keys = {}
    for k in mat:
        m = re.fullmatch(r"X(\d+)_DE_time", k)
        if m:
            keys[int(m.group(1))] = k
    return keys


def _fs_hint(path: Path) -> int | None:
    s = str(path).lower()
    if "48k" in s or "48khz" in s:
        return 48000
    if "12k" in s or "12khz" in s:
        return 12000
    return None


def describe(path: Path) -> Recording | None:
    """Work out label, load, rpm and sampling rate of one .mat file (None if it is not a usable DE file)."""
    mat = loadmat(path)
    keys = _de_keys(mat)
    if not keys:
        return None
    stem = path.stem
    # Pick the DE channel: number in the file name if any, else the number with most variables
    # (99.mat also carries a stray X098_DE_time).
    if stem.isdigit() and int(stem) in keys:
        number = int(stem)
    else:
        counts = {n: sum(k.startswith(f"X{n:03d}") for k in mat) for n in keys}
        number = max(counts, key=counts.get)
    key = keys[number]

    m = NAME.match(stem)
    hint = _fs_hint(path)
    if m:
        label = _CODE[m["code"].upper()]
        size = (m["size"] or "") + (m["pos"] or "")
        hp = int(m["hp"])
        fs = hint or NUMBERS.get(number, (None, None, None, 12000))[3]
        source = "filename"
    elif number in NUMBERS:
        label, size, hp, fs = NUMBERS[number]
        fs = hint or fs
        source = "cwru_number"
    else:
        return None
    rpm_key = next((k for k in mat if re.fullmatch(rf"X{number:03d}RPM", k)), None)
    rpm = float(np.ravel(mat[rpm_key])[0]) if rpm_key else float(RPM_BY_LOAD[hp])
    if label == "normal":
        # Sources disagree on the normal baseline's rate (12 vs 48 kHz) and mirrors re-file it,
        # so measure it: the right rate puts the shaft harmonics where the rpm says.
        fs = detect_fs(np.ravel(mat[key]).astype(float), rpm)
    return Recording(path, label, size, hp, rpm, fs, number, key, source)


def detect_fs(x: np.ndarray, rpm: float, candidates: tuple[int, ...] = (12000, 48000)) -> int:
    """Sampling rate under which 1×–3× shaft peaks stand out most above the spectrum floor."""
    from app.analytics.signal import amplitude_spectrum

    def strength(fs: int) -> float:
        spec = amplitude_spectrum(x[: int(fs * 4)], fs, seg_seconds=1.0)
        f1 = rpm / 60
        floor = spec.floor(5, 300)
        return sum(spec.peak(k * f1, 0.02 * k * f1)[1] for k in (1, 2, 3)) / floor if floor > 0 else 0.0
    return max(candidates, key=strength)


def discover(root: str | Path) -> list[Recording]:
    """All usable drive-end recordings under `root` (searched recursively). If the same CWRU number
    appears twice (a mirror with duplicate folders), the first one found is kept."""
    seen: set[tuple] = set()
    out: list[Recording] = []
    for path in sorted(Path(root).rglob("*.mat")):
        try:
            rec = describe(path)
        except Exception:  # unreadable file: skip, don't crash a long Kaggle run
            continue
        if rec is None:
            continue
        ident = (rec.number, rec.fs, rec.label, rec.load_hp)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(rec)
    return out


def resample_to(x: np.ndarray, fs: int, target: int = TARGET_FS) -> np.ndarray:
    g = gcd(int(fs), int(target))
    return resample_poly(x, target // g, int(fs) // g)


def load(rec: Recording, target_fs: int = TARGET_FS) -> np.ndarray:
    """DE signal in g, resampled to our sensor rate (anti-aliased)."""
    x = np.ravel(loadmat(rec.path)[rec.key]).astype(float)
    return resample_to(x, rec.fs, target_fs)
