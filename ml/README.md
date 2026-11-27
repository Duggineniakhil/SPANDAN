# SPANDAN ML (Member 2: diagnosis + RUL)

Training runs on **Kaggle** (free CPU, datasets already hosted there). The notebooks clone this public repo,
so the model is trained on the same signal-processing and rule code the backend runs
(`backend/app/analytics/`).

| Notebook | Kaggle data to attach | Output → copy into `ml/results/` | Tasks |
|----------|----------------------|----------------------------------|-------|
| `notebooks/01_cwru_diagnosis.ipynb` | [`sufian79/cwru-mat-full-dataset`](https://www.kaggle.com/datasets/sufian79/cwru-mat-full-dataset) or [`esraakhaled299/cwru-data`](https://www.kaggle.com/datasets/esraakhaled299/cwru-data) | `diagnosis-hgb-v1.joblib`, `diagnosis-hgb-v1_report.json`, `cwru_manifest.csv`, `confusion_*.png` | M2-19, M2-22, M2-23 |
| `notebooks/02_ims_indicators.ipynb` | [`vinayak123tyagi/bearing-dataset`](https://www.kaggle.com/datasets/vinayak123tyagi/bearing-dataset) (6.5 GB) | `ims_test{1,2,3}_indicators.csv` | M2-19 (input for M2-24, M2-25) |

## On Kaggle
1. New notebook → *File → Import notebook* → upload the `.ipynb` from `ml/notebooks/`.
2. *Add data* → the dataset in the table.
3. *Settings* → **Internet on**. CPU is enough.
4. *Run all*, then download the files from `/kaggle/working/results/` (Output panel) into `ml/results/`.

Check `cwru_manifest.csv` after the run. It holds one row per recording, with its label, load, rpm and sampling
rate, and says where each label came from (`filename` or the `cwru_number` inside the file).

## Layout
| File | What |
|------|------|
| `spandan_ml/cwru.py` | CWRU loader: labels from file name or CWRU number, DE channel, rpm, resample to 3.2 kHz. Normal files' sampling rate is measured from the signal (sources disagree on 12 vs 48 kHz) |
| `spandan_ml/ims.py` | IMS loader: test sets, snapshots, channels per bearing, which bearing failed how |
| `spandan_ml/features.py` | Window features (doc 04 §4 statistics, band shares) + physics rule scores |
| `spandan_ml/diagnosis.py` | Classifier (calibrated HistGradientBoosting), leave-one-load-out + grouped-by-recording evaluation, rules-only baseline, top-3 + `unknown` inference |
| `spandan_ml/pipelines.py` | The two end-to-end runs (also a CLI: `python -m spandan_ml.pipelines cwru <root> <out>`) |
| `tests/` | Loaders and pipelines on small fake datasets laid out like the Kaggle mirrors |

## Rules that keep the numbers honest
- **Split unit = recording** (CWRU) / **bearing** (IMS). Windows of one recording are never in both train and test.
  The main CWRU number is **leave-one-load-out**.
- **Scale-free inputs only.** Absolute levels (RMS, peak, 1×–3× amplitudes) and shaft speed are not given to
  the classifier. CWRU's normal data was recorded at a different rate than its fault data, so after resampling its
  noise floor differs, and the model could learn that instead of the physics. Speed would leak the load. This also helps
  transfer to our own sensor.
- **The rules-only baseline** is reported next to the classifier, so we can see what training adds.
- Resampling to 3.2 kHz cuts CWRU's high-frequency bearing resonances. Expect lower numbers than papers that use 12 kHz;
  this is the cost of matching our sensor.

## Locally
```bash
cd ml
../backend/.venv/Scripts/python -m pip install -r requirements.txt
../backend/.venv/Scripts/python -m pytest -q tests
```
