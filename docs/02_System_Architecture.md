# 02 · System Architecture

## 1. Block diagram

```
 ON THE SHOP FLOOR (works offline)                 CLOUD                                   PEOPLE
 ┌──────────────────────┐  BLE   ┌────────────────────────┐  HTTPS  ┌──────────────────────────────┐
 │ Sensor node          │ ─────▶ │ Android phone gateway  │ ──────▶ │ Ingestion API (FastAPI)      │
 │ ESP32 + ADXL345      │        │ • BLE receiver          │ batches │ • validate, dedupe, store    │
 │ 3.2 kHz, 10 s / min  │        │ • feature extraction    │         └──────────────┬───────────────┘
 └──────────────────────┘        │ • TFLite autoencoder    │                        ▼
                                 │ • Room DB (30 days)     │         ┌──────────────────────────────┐
                                 │ • sync queue            │         │ PostgreSQL (+ Timescale opt.)│
                                 │ • SMS fallback          │         └──────────────┬───────────────┘
                                 │ • owner UI + voice      │                        ▼
                                 └───────────▲─────────────┘         ┌──────────────────────────────┐
                                             │                       │ Analytics worker             │
                                             │                       │ • fault diagnosis (rules+clf)│
                                             │                       │ • RUL trend fit              │
                                             │                       └──────────────┬───────────────┘
                                             │                                      ▼ (anomaly event)
                                             │                       ┌──────────────────────────────┐
                                             │                       │ Coordinator agent (LLM)      │──▶ Dealers (sandbox)
                                             │                       │ tools: quotes, mechanics,    │──▶ Mechanics (sandbox)
                                             │                       │ slots, draft plan, TTS       │
                                             │                       └──────────────┬───────────────┘
                                             │                                      ▼
                                             │   voice note / push   ┌──────────────────────────────┐
                                             └────────────────────── │ Approval workflow (rules)    │◀── Owner voice/tap reply
                                                                     │ limits, states, audit log    │
                                                                     └──────────────┬───────────────┘
                                                                                    ▼
                                                                     Execute approved actions only
                                                                     (book mechanic, reserve part, schedule downtime)
                                                                                    ▼
                                                                     Repair feedback: job card + 24 h data → new baseline
```

## 2. Components and responsibilities

| # | Component | Runs on | Tech | Type |
|---|-----------|---------|------|------|
| C1 | Sensor node firmware | ESP32 | Arduino/ESP-IDF C++, NimBLE | HW |
| C2 | Phone gateway app | Android 9+ | Kotlin, Jetpack Compose, Room, WorkManager, TFLite, SmsManager | ML (on-device) |
| C3 | Ingestion API | Cloud VM / laptop for demo | Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, Alembic | Backend |
| C4 | Database | Same host | PostgreSQL 16 (TimescaleDB extension optional) | Storage |
| C5 | Analytics worker | Same host | Python, NumPy/SciPy, scikit-learn, joblib; triggered by event | ML |
| C6 | Coordinator agent | Same host | Python, Groq (`openai/gpt-oss-120b`) with Gemini fallback, own tool-use loop | LLM (only one) |
| C7 | Approval engine | Same host | Python rules module + state machine (`backend/app/approval/`), in-app background sweep for reminders/expiry | Rules |
| C8 | Voice service | Same host (no GPU) | **Gnani API** for STT + TTS (Kannada, Hindi) behind a provider-neutral adapter; ffmpeg for audio conversion; cached pre-generated phrases as fallback | Integration |
| C9 | Messaging adapter | Same host | Sandbox: in-app + simulated inbox; P1: Twilio/Meta WhatsApp sandbox | Integration |
| C10 | Judge dashboard (P1) | Browser | Streamlit or React + Recharts | UI |

## 3. Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Where does anomaly detection run? | On the phone (TFLite) | Works offline, cheap, privacy |
| What leaves the phone? | Feature rows + scores, not raw windows (raw only for opt-in debug recording during data collection) | Bandwidth and privacy |
| Diagnosis/RUL location | Cloud | Needs longer history + heavier models; easy to update |
| Voice provider | Gnani API (STT + TTS) behind a `VoiceProvider` interface | Team already has credits; Indian provider built for Indic, code-mixed, noisy speech; no GPU; swappable later |
| Agent loop | Our FastAPI backend drives the tool-use loop through a provider-neutral wrapper | The approval gate and spending limits must live in our code, not the model; providers can be swapped |
| LLM model | Groq `openai/gpt-oss-120b` first, Gemini `gemini-3.5-flash-lite` as automatic fallback (order configurable) | Free tiers; Groq wrote correct Kannada/Hindi script in live tests; fallback covers outages and bad output |
| Approvals | Deterministic rules, never the LLM | Safety and auditability |
| External parties | Simulated directory + sandbox messaging | No real money / people in prototype |
| Time series storage | Plain PostgreSQL table indexed on (machine_id, ts) | Enough for prototype volumes (1 row/min/machine) |

## 4. Data flow summary

| Step | From → To | Payload | Frequency |
|------|-----------|---------|-----------|
| 1 | Sensor → Phone | Raw window: 32,000 samples × 3 axes (int16) ≈ 192 KB, chunked BLE notifications | 1 per minute |
| 2 | Phone (local) | Feature vector (~40 floats) + anomaly score + health index | 1 per minute |
| 3 | Phone → API | Batch of feature rows with UUIDs | Every 15 min when online |
| 4 | API → Worker | `anomaly_event` when score > threshold for N windows | On event |
| 5 | Worker → Agent | Diagnosis (top-3 faults) + RUL range | On event |
| 6 | Agent → Approval engine | Plan JSON + voice script | On event |
| 7 | Approval engine → Owner | Voice note (Kn/Hi) + plan card | On plan |
| 8 | Owner → Approval engine | Voice reply / tap | On reply |
| 9 | Approval engine → Messaging | Booking confirmations (sandbox) | On approval |
| 10 | Mechanic → API | Job card | After repair |

> To cut BLE load, the firmware may send only the dominant radial axis at full rate and the other two at reduced rate. Decide after measuring BLE throughput in Phase 1 (see doc 03).

## 5. Repository layout (monorepo)

```
spandan/
├── firmware/                 # ESP32 PlatformIO project
├── android/                  # Kotlin app (Android Studio)
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── analytics/        # diagnosis + RUL
│   │   ├── agent/            # coordinator, tools, prompts
│   │   ├── approval/         # rules + state machine + audit
│   │   ├── voice/            # VoiceProvider interface + Gnani adapter + phrase cache
│   │   └── messaging/        # sandbox + WhatsApp adapters
│   ├── alembic/
│   ├── tests/
│   └── docker-compose.yml
├── ml/
│   ├── data/                 # (gitignored) MIMII, CWRU, IMS, bench recordings
│   ├── features/             # shared feature code (must match Kotlin implementation)
│   ├── notebooks/
│   ├── train_anomaly.py
│   ├── train_diagnosis.py
│   ├── fit_rul.py
│   └── export_tflite.py
├── dashboard/                # P1 judge dashboard
├── sim/                      # dealer/mechanic simulator + replay tool
└── docs/                     # this folder
```

## 6. Deployment for the demo

- **Backend:** `docker compose up` on a laptop or a small cloud VM (2 vCPU / 4 GB). Postgres + API + worker + scheduler.
- **Voice:** Gnani API (cloud) for TTS and STT, so no GPU is needed. Only the backend calls Gnani; the key never goes into the Android app. Pre-generate fixed phrases and a few demo voice notes and keep them in the repo as a fallback if the API or network fails.
- **Phone:** sideloaded APK; phone on a mount with charger beside the bench rig.
- **Network:** phone and laptop on the same hotspot; demo the offline path by toggling mobile data.
- **Secrets:** `GROQ_API_KEY`, `GEMINI_API_KEY`, `GNANI_API_KEY` (and any other Gnani credentials), Twilio keys in `.env` (never committed).

## 7. Feature parity rule (important)

Features are computed in Kotlin on the phone but models are trained in Python. **One feature spec, two implementations, one test:** `ml/features/` has a golden test file (input window → expected features) that both the Python and the Kotlin unit tests must pass to 1e-4 tolerance.
