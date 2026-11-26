# 04 · Android App Spec (Phone Gateway + Owner App)

One APK with two roles: a **background gateway** (always on) and a **simple owner UI**. A setup mode for the JanAI Café operator.

## 1. Platform
- Kotlin, minSdk 28 (Android 9), targetSdk latest. Jetpack Compose UI.
- Libraries: Nordic Android BLE Library (or plain `BluetoothGatt`), Room, WorkManager, TensorFlow Lite (`org.tensorflow:tensorflow-lite`), JTransforms (FFT), Retrofit + OkHttp, Media3 ExoPlayer (voice notes), `MediaRecorder` (voice reply).
- Runs as a **foreground service** (persistent notification "SPANDAN monitoring") so Android doesn't kill it; request battery-optimisation exemption during setup.

## 2. Permissions
`BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `FOREGROUND_SERVICE`, `POST_NOTIFICATIONS`, `SEND_SMS`, `RECORD_AUDIO` (voice reply, optional mic channel), `INTERNET`. Each explained in Kannada/Hindi during setup.

## 3. Modules

| Module | Responsibility |
|--------|---------------|
| `ble/` | Scan, pair by name `SPANDAN-xxxx`, connect, request MTU 247, reassemble chunks into windows, CRC check, reconnect |
| `dsp/` | Feature extraction (spec below), identical to `ml/features/` |
| `ml/` | Load `anomaly_<machine>.tflite`, standardise with baseline stats, compute reconstruction error → anomaly score → health index |
| `detect/` | Alert rule: score > threshold for 3 consecutive windows → `anomaly` alert; hysteresis to clear |
| `store/` | Room DB (doc 07 §3), 30-day retention |
| `sync/` | WorkManager job every 15 min with network constraint; uploads unsynced rows in batches of 500; marks synced on 2xx |
| `sms/` | If anomaly and no network for > 2 min → SMS to owner number (and Café operator) in owner's language |
| `plan/` | Fetch pending plans, download voice note, show plan card, record reply, post decision |
| `setup/` | Operator wizard: pair sensor → machine details (name, RPM, bearing model) → baseline start → status |

## 4. Feature extraction spec (per 10 s window, per axis unless noted)

Pre-processing: convert to g, remove DC mean, Hann window for spectra, sub-windows of 1 s (3,200 samples) averaged (Welch).

| Feature | Definition |
|---------|-----------|
| `rms_{x,y,z}` | √mean(a²) |
| `peak_{x,y,z}` | max\|a\| |
| `crest_{x,y,z}` | peak / rms |
| `kurtosis_{x,y,z}` | 4th standardised moment (impulsiveness → bearing defects) |
| `skew_y` | 3rd standardised moment |
| `band_{lo}_{hi}_y` | Spectral energy in bands: 0–25, 25–75, 75–150, 150–300, 300–600, 600–1000, 1000–1600 Hz |
| `rpm_est` | Strongest peak in 15–55 Hz (motor 1×), or from config |
| `amp_1x_y`, `amp_2x_y`, `amp_3x_y` | Spectral amplitude at 1×, 2×, 3× shaft speed (±1 Hz) |
| `env_rms_y` | RMS of envelope (Hilbert) of 500–1,500 Hz band-passed signal |
| `spectral_centroid_y`, `spectral_flatness_y` | Shape of spectrum |

≈ 30 features. The phone uploads features only. During data collection a **debug mode** can additionally save raw windows to the SD card/USB for the ML team (with owner consent; never in production).

## 5. Anomaly score → health index
- Score = mean squared reconstruction error of the standardised feature vector.
- Threshold = 99.5th percentile of scores over the baseline period (per machine).
- Health index = `100 × clip(1 − (score − p50) / (k × (thr − p50)), 0, 1)`, with k = 3 (tunable). 100 = like baseline, ~0 = far beyond threshold. Smooth with an EMA over 10 windows for display.
- False-alarm feedback: each owner "false alarm" raises the threshold by 5 % (max +30 %) and is logged.

## 6. Baseline mode
- Machine state `baseline`: collect features, no alerts (only sensor-silent).
- Prototype: on-device fit of standardisation stats + threshold using a **pre-trained generic autoencoder** (trained on MIMII + bench normal data); the per-machine part is the scaler + threshold. Stretch: fine-tune per machine on the server and push a new `.tflite`.
- Production: 3–5 days covering all loads; Café technician confirms machine was healthy at setup.

## 7. Owner UI (Compose, big text, icons, colours, voice-first)

| Screen | Content |
|--------|---------|
| Home | Machine card: health % ring (green ≥ 70, amber 40–69, red < 40), "last reading 1 min ago", sensor status |
| Alert | Icon + one sentence + "Plan is being prepared" |
| Plan card | Fault, days left (range), part + price + dealer, mechanic + slot, total cost; ▶ play voice note; big ✅ Approve / ❌ Reject; 🎤 "Reply by voice" |
| History | Past alerts, plans, repairs |
| Settings | Language (ಕನ್ನಡ / हिन्दी / English), spending limit, idle hours, phone numbers (operator-assisted) |

Every owner-visible string lives in `strings.xml` for `kn`, `hi`, `en`.

## 8. Offline behaviour
| Situation | Behaviour |
|-----------|----------|
| No internet | Detection continues; rows queue; SMS on alert |
| No BLE for 5 min | "Sensor silent" notification + SMS if offline |
| Phone reboot | Foreground service restarts on `BOOT_COMPLETED` |
| Storage > 30 days | Delete synced rows older than 30 days; never delete unsynced rows < 60 days |

## 9. Tests
- Unit: feature golden test (same file as Python), score/threshold math, chunk reassembly with missing chunks.
- Instrumented: Room DAO, sync worker with MockWebServer, SMS path with fake `SmsManager`.
- Manual: 24 h soak on bench (no crash, no memory growth, < 5 % battery drain while charging).
