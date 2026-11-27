"""Dataset → C4 replay sessions (the window format the phone, the replay tool and later the sensor share;
see `backend/app/replay/sources.py`). Resampled to our 3.2 kHz sensor rate.

    python -m spandan_ml.c4 cwru <cwru_root> <out_dir> [--load 1] [--fault bearing_outer] [--size 007]
    python -m spandan_ml.c4 ims  <ims_root>  <out_dir> [--test 2] [--bearing 1] [--every 5]

CWRU is not run-to-failure: a session is the normal recordings, then one fault recording (a step change),
cut into short windows. IMS is: a session is one bearing's whole life, one window per snapshot, with
`severity` = fraction of life used (the true wear is unknown) and the label of what finally failed.
Then replay it:  cd backend && python -m app.replay <out_dir>/<session>
"""
import argparse
from pathlib import Path

import numpy as np

from app.replay.sources import ReplayWindow, write_session
from spandan_ml import TARGET_FS, cwru, ims


def _cut(y: np.ndarray, x: np.ndarray | None, seconds: float, hop: float, fs: int = TARGET_FS):
    n, h = int(seconds * fs), int(hop * fs)
    for i in range(0, len(y) - n + 1, h):
        yield y[i:i + n], (x[i:i + n] if x is not None else np.zeros(n))


def cwru_session(root: str | Path, out: str | Path, *, load: int = 1, fault: str = "bearing_outer",
                 size: str = "007", seconds: float = 2.0, hop: float = 1.0) -> Path:
    from scipy.io import loadmat

    recs = cwru.discover(root)
    normals = [r for r in recs if r.label == "normal"]
    faulty = [r for r in recs if r.label == fault and r.load_hp == load and r.fault_size.startswith(size)]
    if not normals or not faulty:
        raise SystemExit(f"need normal recordings and a {fault} {size} recording at load {load} under {root}")
    # the normal recording at the same load first (the "machine" in this session), then the others
    normals.sort(key=lambda r: r.load_hp != load)
    windows: list[ReplayWindow] = []
    for rec, label in [(r, "normal") for r in normals] + [(faulty[0], fault)]:
        mat = loadmat(rec.path)
        y = cwru.resample_to(np.ravel(mat[rec.key]).astype(float), rec.fs)
        fe = rec.key.replace("_DE_", "_FE_")
        x = cwru.resample_to(np.ravel(mat[fe]).astype(float), rec.fs) if fe in mat else None
        for yy, xx in _cut(y, x, seconds, hop):
            windows.append(ReplayWindow(xx, yy, np.zeros_like(yy), TARGET_FS, rec.rpm, label,
                                        None if label == "normal" else 1.0))
    name = f"cwru-{fault}-{size}-load{load}"
    return write_session(Path(out) / name, windows, unit=f"cwru-load{load}", session=name, bearing_model="6205-2RS",
                         interval_s=hop, extra={"source": "CWRU drive end", "recordings": [str(r.path.name) for r in normals + faulty[:1]]})


def ims_session(root: str | Path, out: str | Path, *, test: int = 2, bearing: int = 1, every: int = 1) -> Path:
    sets = {s.number: s for s in ims.discover(root)}
    if test not in sets:
        raise SystemExit(f"IMS test {test} not found under {root}")
    snaps = sets[test].snapshots[::every]
    failed = ims.FAILURES.get(test, {}).get(bearing)
    cols = ims.CHANNELS[test][bearing]
    windows = []
    for i, path in enumerate(snaps):
        snap = ims.load_snapshot(path)
        y = cwru.resample_to(snap[:, cols[0]], ims.FS)
        x = cwru.resample_to(snap[:, cols[1]], ims.FS) if len(cols) > 1 else np.zeros_like(y)
        life = i / max(len(snaps) - 1, 1)
        windows.append(ReplayWindow(x, y, np.zeros_like(y), TARGET_FS, ims.RPM, failed or "normal",
                                    round(life, 4) if failed else None))
    name = f"{ims.unit_id(test, bearing)}-every{every}"
    return write_session(Path(out) / name, windows, unit=ims.unit_id(test, bearing), session=name,
                         bearing_model=ims.BEARING, interval_s=600 * every,
                         extra={"source": "NASA IMS", "failed": failed, "severity_meaning": "fraction of life"})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="dataset", required=True)
    c = sub.add_parser("cwru")
    c.add_argument("root"), c.add_argument("out")
    c.add_argument("--load", type=int, default=1)
    c.add_argument("--fault", default="bearing_outer", choices=["bearing_outer", "bearing_inner", "bearing_ball"])
    c.add_argument("--size", default="007")
    i = sub.add_parser("ims")
    i.add_argument("root"), i.add_argument("out")
    i.add_argument("--test", type=int, default=2)
    i.add_argument("--bearing", type=int, default=1)
    i.add_argument("--every", type=int, default=1, help="keep every n-th snapshot")
    a = p.parse_args()
    if a.dataset == "cwru":
        path = cwru_session(a.root, a.out, load=a.load, fault=a.fault, size=a.size)
    else:
        path = ims_session(a.root, a.out, test=a.test, bearing=a.bearing, every=a.every)
    print("wrote", path)


if __name__ == "__main__":
    main()
