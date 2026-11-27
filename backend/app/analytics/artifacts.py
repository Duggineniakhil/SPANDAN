"""Load the trained diagnosis model and the RUL settings produced by the ML runs (ml/results/).

Both are optional: without the model, diagnosis uses the physics rules alone; without the RUL config, the
built-in defaults (fitted on the same IMS data) are used. The model file is a pickle (joblib), so it is
only ever loaded from the path in our own settings, never from uploaded data.
"""
import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.analytics.rul import RulConfig
from app.config import get_settings

log = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (_BACKEND_DIR / p).resolve()


@lru_cache
def diagnosis_model() -> dict | None:
    path = _resolve(get_settings().diagnosis_model_path)
    if not path.exists():
        log.warning("diagnosis model not found at %s: using the physics rules alone", path)
        return None
    import warnings

    import joblib
    import sklearn

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a version mismatch must not load silently
        try:
            artifact = joblib.load(path)
        except Exception as e:  # incompatible scikit-learn or corrupt file → rules only
            log.error("diagnosis model at %s not loaded (%s); using the physics rules alone", path, e)
            return None
    if artifact.get("sklearn_version") not in (None, sklearn.__version__):
        log.error("model trained with scikit-learn %s, running %s: not used", artifact["sklearn_version"], sklearn.__version__)
        return None
    return artifact


def classify(artifact: dict, features: dict[str, float]) -> dict[str, float]:
    """Class probabilities for one window's features."""
    x = np.array([[features.get(n, 0.0) for n in artifact["feature_names"]]], dtype=float)
    proba = artifact["model"].predict_proba(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0))[0]
    return {str(c): float(p) for c, p in zip(artifact["model"].classes_, proba)}


@lru_cache
def rul_config() -> RulConfig:
    path = _resolve(get_settings().rul_config_path)
    if not path.exists():
        log.warning("RUL config not found at %s: using defaults", path)
        return RulConfig()
    return RulConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
