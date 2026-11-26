# 05 · ML Models Spec

Three models, each validated separately. All code in `ml/`, Python 3.11, NumPy/SciPy, scikit-learn, TensorFlow/Keras (for TFLite export), pandas, matplotlib. Track experiments in a simple `results/` CSV + MLflow (optional).

## 0. Datasets

| Dataset | Use | Notes |
|---------|-----|-------|
| **MIMII** (Hitachi, machine sounds: fan, pump, slider, valve; normal + abnormal; 4 machine IDs each) | Anomaly-detection method development & benchmark | Audio at 16 kHz, not vibration. Use it to validate the *method* (AE vs IF, split by machine ID). Alternative/extra: MIMII DUE / DCASE 2020 Task 2 |
| **CWRU Bearing Data** (Case Western, drive-end accelerometer, 12 kHz & 48 kHz, inner/outer/ball faults, 0–3 HP loads) | Fault classifier training/eval | Resample to 3.2 kHz to match our sensor. Split by load + recording, **not** windows |
| **NASA IMS Bearing** (run-to-failure, 3 test sets, 20 kHz, 1 s snapshots every 10 min) | RUL trend + interval evaluation | Each bearing is one unit; leave-one-bearing-out |
| **Our bench recordings** (doc 03 §5) | Domain check for all three models, live demo | Split by session |
| **Real mill recording** (optional) | Normal-only; false-alarm rate | |

Download scripts in `ml/data/get_*.py`; data is gitignored. Keep a `ml/data/MANIFEST.csv`: file, dataset, unit/machine ID, session, label, split.

### Leakage rule (non-negotiable)
Every window carries `unit_id` and `session_id`. Splits are made at that level using `GroupKFold`/explicit lists. No window from a test unit/session appears in training, including scaler fitting.

## 1. Model 1 — Anomaly detection

| Item | Spec |
|------|------|
| Question | Is this machine behaving abnormally vs its own normal? |
| Input | Standardised feature vector (doc 04 §4), ~30 dims, one per minute |
| Model | Dense autoencoder 30→16→8→16→30, ReLU, MSE, Adam, early stopping; trained on normal only |
| Baseline | Isolation Forest (sklearn, 200 trees) on the same features |
| Output | Anomaly score (recon. error) → health index (doc 04 §5) |
| Export | Keras → TFLite (float32; int8 optional), < 50 KB |
| Metrics | ROC-AUC and pAUC (FPR ≤ 0.1) per machine ID; **false alarms per machine per week** at the chosen threshold on held-out normal sessions |

Protocol:
- **MIMII:** compute log-mel / spectral band features (same family of statistics as our vibration features, applied to audio); train on normal of IDs {00,02,04}, test on ID 06 normal+abnormal; rotate. Report AE vs IF.
- **Bench:** train on normal sessions 1–4, test on normal sessions 5–6 + all fault sessions. Report AUC per fault type and false alarms/week (scale per-minute false positives × 10,080).

## 2. Model 2 — Fault diagnosis

| Item | Spec |
|------|------|
| Question | What is most likely wrong? |
| Input | Spectrum + envelope spectrum of the anomalous windows, shaft speed, bearing geometry |
| Method | (a) **Physics rules**: compute BPFO/BPFI/BSF/FTF from bearing geometry and RPM, score peak prominence at those frequencies ±2 % and harmonics in the envelope spectrum; 1×/2×/harmonic ratios for imbalance/misalignment/looseness. (b) **Classifier**: gradient boosting (LightGBM or sklearn HistGB) on features + rule scores |
| Classes | normal, imbalance, misalignment, looseness, bearing_outer, bearing_inner, bearing_ball, unknown |
| Output | Top-3 faults with calibrated confidence + human-readable evidence string ("Peak at 172 Hz = BPFO, 3.6× noise floor") |
| Metrics | Accuracy, macro-F1, confusion matrix; separate tables for CWRU (bearing classes) and bench (all classes) |

Notes:
- CWRU has no imbalance/misalignment classes → those come from the bench (and rules).
- Bearing geometry table in `ml/bearings.csv` (6204, 6205, 6305, UCP204…: n balls, Bd, Pd, contact angle).
- If top-1 confidence < 0.5 → output `unknown` and recommend an inspection (no RUL).

## 3. Model 3 — Remaining useful life (RUL)

| Item | Spec |
|------|------|
| Question | How many days until the health index crosses the danger limit? |
| Input | Health-index (or RMS/kurtosis) time series since the anomaly began |
| Method | Fit exponential degradation `h(t) = a + b·e^{c t}` (or linear on log-scale) with bootstrap / Bayesian updating → distribution of crossing time of the danger threshold; report 10th–90th percentile range |
| Output | `{rul_days_low, rul_days_high}` or `insufficient_data` (fewer than N points or poor fit, R² < 0.6) |
| Metrics | On IMS (leave-one-bearing-out): MAE of median RUL in days at checkpoints (e.g. 50 %, 70 %, 90 % of life); **interval coverage** (fraction of true RULs inside the 10–90 % band, target ≈ 80 %); interval width |
| Time scaling | IMS life is days-scale; bench progressive-wear runs are hours-scale → for the demo, show RUL in hours on the bench and explain scaling |

## 4. Evaluation report (deliverable)
`ml/REPORT.md` with, for each model: data used, split, metrics table, confusion matrix / ROC plot, failure cases, and limitations (MIMII is sound, CWRU is lab-seeded faults, IMS is a test rig, bench is small). Replace "RESULTS PENDING" on slide 9 with these numbers.

## 5. Artifacts & versioning
| Artifact | Format | Consumer |
|----------|--------|----------|
| `anomaly_ae_v{n}.tflite` + `scaler_v{n}.json` | TFLite + JSON | Android |
| `diagnosis_v{n}.joblib` + `bearings.csv` | joblib | Analytics worker |
| `rul_config_v{n}.json` | JSON (thresholds, priors) | Analytics worker |
| `features_golden.json` | JSON | Python + Kotlin tests |

Every telemetry row and diagnosis records `model_version`.
