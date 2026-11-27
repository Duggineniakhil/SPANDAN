"""NASA IMS run-to-failure loader (M2-19), Kaggle mirror `vinayak123tyagi/bearing-dataset`.

Layout: `1st_test/`, `2nd_test/`, `3rd_test/` (sometimes `4th_test/txt/`), one tab-separated text file
per 1-second snapshot taken every 10 minutes, named by timestamp `YYYY.MM.DD.HH.MM.SS`. 20 kHz,
2000 rpm, four Rexnord ZA-2115 bearings. Set 1 has two channels per bearing (x, y), sets 2 and 3 one.

Each bearing of each test is one unit (leave-one-bearing-out for RUL, M2-25).
"""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

FS = 20000
RPM = 2000
BEARING = "ZA-2115"
SNAPSHOT_NAME = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$")

# What failed at the end of each test (IMS readme)
FAILURES = {
    1: {3: "bearing_inner", 4: "bearing_ball"},
    2: {1: "bearing_outer"},
    3: {3: "bearing_outer"},
}
# Bearing → column(s) of the snapshot file
CHANNELS = {1: {1: [0, 1], 2: [2, 3], 3: [4, 5], 4: [6, 7]},
            2: {b: [b - 1] for b in range(1, 5)},
            3: {b: [b - 1] for b in range(1, 5)}}


@dataclass
class TestSet:
    number: int
    folder: Path
    snapshots: list[Path]

    def times(self) -> list[datetime]:
        return [datetime.strptime(p.name, "%Y.%m.%d.%H.%M.%S") for p in self.snapshots]


def _set_number(folder: Path) -> int | None:
    m = re.match(r"^(\d)(st|nd|rd|th)_test$", folder.name)
    if not m:
        return None
    n = int(m.group(1))
    return 3 if n == 4 else n  # some mirrors call set 3 "4th_test"


def discover(root: str | Path) -> list[TestSet]:
    sets: dict[int, TestSet] = {}
    for folder in sorted(Path(root).rglob("*_test")):
        n = _set_number(folder) if folder.is_dir() else None
        if n is None or n in sets:
            continue
        files = sorted(p for p in folder.rglob("*") if p.is_file() and SNAPSHOT_NAME.match(p.name))
        if files:
            sets[n] = TestSet(n, folder, files)
    return [sets[k] for k in sorted(sets)]


def load_snapshot(path: Path) -> np.ndarray:
    """(samples, channels) array in g."""
    data = np.loadtxt(path, dtype=np.float64)
    return data[:, None] if data.ndim == 1 else data


def bearing_signal(snapshot: np.ndarray, test: int, bearing: int) -> np.ndarray:
    """Radial signal for one bearing (set 1: the first of its two channels)."""
    return snapshot[:, CHANNELS[test][bearing][0]]


def unit_id(test: int, bearing: int) -> str:
    return f"ims-{test}-b{bearing}"
