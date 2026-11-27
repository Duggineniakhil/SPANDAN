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

Training runs in **Kaggle notebooks** (`ml/notebooks/`, see `ml/README.md`) against the Kaggle mirrors (CWRU: `sufian79/cwru-mat-full-dataset` or `esraakhaled299/cwru-data`; IMS: `vinayak123tyagi/bearing-dataset`), so nothing is downloaded locally. The CWRU run writes `cwru_manifest.csv`: file, CWRU number, label, fault size, load, rpm, sampling rate, label source, split unit.

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
- Classifier inputs are **scale-free only** (energy shares, ratios, kurtosis, crest, rule prominences/scores). Absolute RMS/peak/1×–3× amplitudes and shaft speed are excluded. CWRU's normal data and fault data were recorded at different rates, so their noise floors differ after resampling and would be a shortcut. Speed leaks the load.
- Evaluation: leave-one-load-out (main), grouped 5-fold by recording, and the rules alone as a baseline.
- CWRU has no imbalance/misalignment classes → those come from the bench (and rules).
- Bearing geometry table in `backend/app/analytics/bearings.csv` (6205 and 6203 from CWRU, ZA-2115 from IMS; 6204, 6305, UC204 approximate until checked against datasheets), calculator in `bearings.py`. Computed orders match the published CWRU values (6205: BPFO 3.5848×, BPFI 5.4152×, 2×BSF 4.7135×, FTF 0.3983×).
- **Rule scorer** (`backend/app/analytics/rules.py`, `rules-v1`): envelope spectrum (500–1,500 Hz band, Hilbert) peaks at BPFO / BPFI / 2×BSF ±2 % with harmonics and sidebands, scored by prominence over the local noise floor; imbalance from 1× vs the machine's baseline; misalignment from 2×/1× and axial/radial; looseness from 3×–10× harmonics and half-orders. Each fault gets a score in [0, 1] plus an evidence sentence; `RuleReport.features()` feeds the classifier.
  - For a 6205, 3×BPFO (10.75×) and 2×BPFI (10.83×) fall inside the same ±2 % window, so the fundamental carries most of the weight and harmonics only confirm.
  - Thresholds were set on simulated windows (`backend/app/sim/vibration.py`): every fault ranked first from severity 0.3, 0/30 healthy windows flagged, mild faults never misread. **They must be re-checked on CWRU / IMS / bench data (M2-23).**
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

### Implementation and results (IMS, leave-one-bearing-out)
- Code: `backend/app/analytics/rul.py` (`rul-loglinear-v1`), evaluation `ml/spandan_ml/rul_eval.py`, settings `ml/results/rul_config_v1.json`, report `ml/results/rul_eval_report.json`, plot `ml/results/rul_ims.png`.
- **Indicator:** RMS ÷ the machine's own baseline RMS (in production: telemetry `rms_y` vs its baseline rows). Smoothed with a trailing 6-reading median.
- **Onset:** the ratio stays ≥ 1.5 for 6 readings. Before that the result is `no_degradation`, and no RUL is given (correct at 50 % and 70 % of life for all 4 failed bearings).
- **Fit:** a straight line on log(running maximum) since onset. Wear doesn't heal, and IMS shows transient dips that broke plain fits. The fit needs ≥ 12 points, a rising trend and R² ≥ 0.6, else `insufficient_data`.
- **Range:** 10–90 % of a moving-block bootstrap (correlated residuals) × failure levels seen in training (IMS: 2.7×–6.9× baseline).
- **Results over all points after onset (221 of 351 had a prediction):**

| Range | Coverage | Low end safe (bearing lasted ≥ low) | Mean width | MAE of median |
|-------|----------|-------------------------------------|-----------|---------------|
| **Bootstrap (chosen)** | 46 % | **93 %** | **2.9 days** | 1.7 days |
| Calibrated on training bearings | 85 % | 94 % | 24 days | 1.7 days |

  The bootstrap range misses mostly on the **safe side**: in 47 % of predictions the bearing lasted longer than the high end. The **low end becomes the repair deadline**, and it held in 93 % of predictions. Calibrating to 80 % coverage needed ~24-day ranges, which tell an owner nothing.
- **Per bearing (plot):** test 3 bearing 3 is predicted early (safe). Test 1 bearing 4 tracks for 2 days, then overestimates during a long plateau. Test 1 bearing 3 overestimates for the first day after onset (≈10 days predicted, 1.4 true). Test 2 bearing 1 is too irregular, so it is never predicted (`insufficient_data`).
- **Healthy bearings** cross the onset level only in the last 0.1–1.1 days of each test, when the whole rig shakes from the failed bearing. So RUL runs only for the machine whose alert fired.
- **Limits:** 4 failed bearings; the method choices (running maximum, block bootstrap) were compared on the same bearings, so the numbers are optimistic. IMS failure is days-scale and abrupt. The bench rig (hours-scale) needs its own check.

## 4. Evaluation report (deliverable)
`ml/REPORT.md` with, for each model: data used, split, metrics table, confusion matrix / ROC plot, failure cases, and limitations (MIMII is sound, CWRU is lab-seeded faults, IMS is a test rig, bench is small). Replace "RESULTS PENDING" on slide 9 with these numbers.

## 5. Artifacts & versioning
| Artifact | Format | Consumer |
|----------|--------|----------|
| `anomaly_ae_v{n}.tflite` + `scaler_v{n}.json` | TFLite + JSON | Android |
| `diagnosis_v{n}.joblib` + `bearings.csv` | joblib | Analytics worker |
| `rul_config_v{n}.json` | JSON (failure levels, onset rule, fit settings) | Analytics worker (`RulConfig.from_dict`) |
| `features_golden.json` | JSON | Python + Kotlin tests |

Every telemetry row and diagnosis records `model_version`.
