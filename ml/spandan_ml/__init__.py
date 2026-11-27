"""SPANDAN ML: dataset loaders, features, diagnosis training and evaluation (Member 2, M2-19 – M2-25).

Signal processing and the physics rules are shared with the backend (`backend/app/analytics`), so the
model is trained on exactly the code that runs in production. This makes `backend/` importable.
"""
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

TARGET_FS = 3200  # our sensor (ADXL345); every dataset is resampled to this


def pinned_sklearn() -> str:
    """scikit-learn version pinned in ml/requirements.txt (the backend pins the same one)."""
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    return re.search(r"^scikit-learn==([\d.]+)", req, re.M).group(1)


def check_sklearn() -> None:
    """A model saved with another scikit-learn version may not load in the backend: refuse to train."""
    import sklearn

    pin = pinned_sklearn()
    if sklearn.__version__ != pin:
        raise RuntimeError(f"scikit-learn {sklearn.__version__} is installed but {pin} is pinned in ml/requirements.txt; "
                           f"run `pip install scikit-learn=={pin}` (on Kaggle: restart the kernel and run all)")
