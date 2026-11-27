"""Window features: the code lives in the backend (`app.analytics.features`) so training and live
diagnosis use exactly the same implementation."""
import spandan_ml  # noqa: F401  (puts backend/ on sys.path)
from app.analytics.features import BANDS, NOT_FOR_MODEL, window_features, windows  # noqa: F401
