"""SPANDAN ML: dataset loaders, features, diagnosis training and evaluation (Member 2, M2-19 – M2-25).

Signal processing and the physics rules are shared with the backend (`backend/app/analytics`), so the
model is trained on exactly the code that runs in production. This makes `backend/` importable.
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

TARGET_FS = 3200  # our sensor (ADXL345); every dataset is resampled to this
