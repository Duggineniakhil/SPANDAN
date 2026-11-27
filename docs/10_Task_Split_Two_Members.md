# 10 · Development Task Split — Two Members (Software Only)

Only software engineering work is listed. **Hardware (sensor firmware, BLE sensor link, physical recordings) is left out for now.** Sensor input comes from **public datasets replayed through the pipeline** (MIMII, CWRU, NASA IMS), so the hardware can be plugged in later without changing anything downstream.

| Member | Area | Owns |
|--------|------|------|
| **Member 1 — Edge & Detection** | Everything on the phone | Data replay input, feature extraction, anomaly model (training → TFLite → on-device), offline storage/sync/SMS, owner app, voice record/playback |
| **Member 2 — Cloud & Intelligence** | Everything in the cloud | Backend API + DB, fault diagnosis, RUL, coordinator agent, rules/approval engine, voice (STT/TTS), simulator, server-side replay, dashboard |

---

## Shared contracts (agree in the first 2 days, then build independently)

| ID | Contract | Drafted by | Reviewed by | Reference |
|----|----------|-----------|-------------|-----------|
| C1 | Feature list + exact definitions + `features_golden.json` (input window → expected features) | M1 | M2 | doc 04 §4 |
| C2 | `POST /telemetry/batch`, `/events/anomaly`, `/plans/*`, `/jobs/*` request/response JSON | M2 | M1 | doc 07 §1 |
| C3 | Plan JSON schema (what the phone displays) | M2 | M1 | doc 06 §4 |
| C4 | Window file format for replay: `.npy` int16 [N×3] + `meta.json` (unit, session, label, fs, rpm). Later the hardware sensor will produce the same format | M1 | M2 | doc 03 §3 |

Until the other side is ready, each member mocks the other: M1 uses a mock server (static JSON), M2 uses a script that posts fake feature rows.

---

## Member 1 — Edge & Detection

### Week 1–2 · Data input + phone pipeline
- [ ] **M1-01** Dataset converters: MIMII, CWRU and NASA IMS → C4 window files (resample to 3.2 kHz, 10 s windows, unit/session/label metadata)
- [ ] **M1-02** Build replay sequences: normal → developing fault → failure, per unit, for testing and the end-to-end flow
- [ ] **M1-03** Android skeleton: Compose, foreground service, boot receiver, permissions flow
- [ ] **M1-04** Replay input on phone: load C4 files and feed windows on a timer (1 per minute, or faster in test mode) through a `WindowSource` interface (so a BLE sensor source can be added later)
- [ ] **M1-05** Room DB: `feature_rows`, `alerts`, `pending_plans`, `config`; 30-day retention job
- [ ] **M1-06** Sync worker (WorkManager): batches of 500 to `/telemetry/batch`, `row_id` idempotency, retry on failure

### Week 2–3 · Features
- [ ] **M1-07** Python feature module (`ml/features/`): all ~30 features (C1)
- [ ] **M1-08** Kotlin port of the same features (JTransforms FFT, Hilbert envelope)
- [ ] **M1-09** Golden test passing in both Python (pytest) and Kotlin (JUnit) within 1e-4

### Week 3–4 · Anomaly model
- [ ] **M1-10** Dataset loaders with unit/session IDs; `GroupKFold` splits (no leakage)
- [ ] **M1-11** Train Isolation Forest baseline
- [ ] **M1-12** Train dense autoencoder (30→16→8→16→30) on normal data only
- [ ] **M1-13** Evaluate: AUC / pAUC per machine ID on MIMII; AUC and false alarms per week on CWRU/IMS replay sequences; plots to `ml/results/`
- [ ] **M1-14** Export TFLite + scaler JSON; verify Python vs TFLite outputs match

### Week 4–5 · On-device detection
- [ ] **M1-15** TFLite inference on phone → anomaly score
- [ ] **M1-16** Baseline mode: fit per-machine scaler + threshold (99.5th percentile) on device
- [ ] **M1-17** Health index (0–100) + EMA smoothing; alert rule (3 consecutive windows over threshold, hysteresis)
- [ ] **M1-18** Input-silent alert (no window for 5 min)
- [ ] **M1-19** Offline SMS on alert (owner language), only when no network for > 2 min
- [ ] **M1-20** POST `/events/anomaly` on confirmed anomaly

### Week 5–6 · Owner app
- [ ] **M1-21** Home screen: health ring, colour bands, last reading, input status
- [ ] **M1-22** Setup screen: machine name, RPM, bearing model, start baseline
- [ ] **M1-23** Plan card from C3: fault, days left, part/price/dealer, mechanic/slot, total; Approve / Reject buttons
- [ ] **M1-24** Voice note download + playback (ExoPlayer)
- [ ] **M1-25** Voice reply: record (MediaRecorder, Opus) → upload to `/plans/{id}/voice-reply` → show result
- [ ] **M1-26** False-alarm button → API + local threshold bump (+5 %, max +30 %)
- [ ] **M1-27** Mechanic job-card form → `/jobs/{id}/job-card`; on new baseline, reset local scaler/threshold
- [ ] **M1-28** All strings in `kn`, `hi`, `en`

### Week 6–7 · Hardening
- [ ] **M1-29** Unit tests: replay input, score/threshold math; instrumented tests: Room DAO, sync with MockWebServer, SMS with fake SmsManager
- [ ] **M1-30** 24 h soak run on replay: fix crashes and leaks

---

## Member 2 — Cloud & Intelligence

### Week 1–2 · Backend foundation
- [x] **M2-01** FastAPI app + PostgreSQL (docker compose), SQLAlchemy models, Alembic migrations for all tables (doc 07 §2)
- [x] **M2-02** Endpoints: owners, machines, baseline start/complete
- [x] **M2-03** `/telemetry/batch` with validation, dedupe by `row_id`, `{accepted, duplicates, rejected}` response
- [ ] **M2-04** Telemetry/health read endpoints for dashboard
- [x] **M2-05** Append-only `audit_log` helper used by every write path
- [x] **M2-06** ~~Fake-telemetry script~~ replaced by the web app (simulated sensor + gateway) (posts feature rows, normal → anomalous) for testing without M1
- [x] **M2-07** Server-side anomaly rule as backup + `anomaly_events` creation

### Week 2–3 · Simulator + agent v0
- [x] **M2-08** Sandbox simulator: dealers + parts catalog + mechanics + weekly slot calendars; `/sim/reset`
- [x] **M2-09** Messy multilingual dealer replies (kn/hi/en mix) and one prompt-injection reply
- [x] **M2-10** Agent tools: `get_machine_context`, `search_parts` (rule-ranked), `request_quote`, `find_repair_slots` (rule-ranked: idle windows × free slots × RUL deadline), `check_mechanic_availability`, `submit_plan`, all with strict JSON schemas
- [x] **M2-11** Agent loop (Groq + Gemini fallback, provider-neutral wrapper, 12-call cap, 90 s timeout, fallback on any failure)
- [x] **M2-12** System prompt + voice-script instructions (doc 06 §7)

### Week 3–4 · Rules & approval engine
- [ ] **M2-13** Plan validation: spending limit, quote/slot IDs exist and are fresh, prices match DB, slot before RUL low bound and inside idle window, allowed action types only, voice-script language/length
- [ ] **M2-14** Reject-and-retry loop back to the agent (max 2), then "could not plan" message
- [ ] **M2-15** State machine: draft → pending → approved / rejected / expired → executed / cancelled
- [ ] **M2-16** Scheduler: 24 h reminder, 48 h expiry; never auto-approve
- [ ] **M2-17** Executor for approved plans (sandbox): book slot, confirm dealer order (no payment), schedule downtime, notify owner, each step audited
- [ ] **M2-18** Approval only accepted from the owner's registered device/number

### Week 3–5 · Diagnosis + RUL
- [ ] **M2-19** CWRU + NASA IMS loaders; resample CWRU to 3.2 kHz; split by load/recording (CWRU) and by bearing (IMS)
- [ ] **M2-20** Bearing geometry table + BPFO/BPFI/BSF/FTF calculator
- [ ] **M2-21** Rule scorer: envelope-spectrum peaks at fault frequencies ± 2 % + harmonics; 1×/2×/harmonics for imbalance/misalignment/looseness
- [ ] **M2-22** Classifier (HistGradientBoosting) on features + rule scores; calibrated top-3 + evidence string; `unknown` when confidence < 0.5
- [ ] **M2-23** Evaluate diagnosis: accuracy, macro-F1, confusion matrix (CWRU)
- [ ] **M2-24** RUL: exponential fit + bootstrap interval → `{low, high}` or `insufficient_data`
- [ ] **M2-25** Evaluate RUL on IMS leave-one-bearing-out: MAE at life checkpoints, interval coverage, width
- [ ] **M2-26** Analytics worker: on anomaly event → diagnosis + RUL → `diagnoses` row → trigger agent

### Week 4–5 · Voice
- [ ] **M2-27** `VoiceProvider` interface + Gnani adapter: TTS and STT for kn + hi, key from `.env`, timeout + error handling
- [ ] **M2-28** Audio conversion (ffmpeg) to/from Gnani formats; pre-generated phrase cache + demo voice notes; fallback to cache or text + tap on API failure
- [ ] **M2-29** Intent detection: keyword rules first, LLM structured-output fallback (`approve / reject / question / unclear`), re-ask up to 2 times
- [ ] **M2-30** `/plans/{id}/voice-note` and `/plans/{id}/voice-reply` endpoints
- [ ] **M2-31** "Question" intent → agent re-plans with the owner's constraint

### Week 5–6 · Feedback, replay, dashboard
- [ ] **M2-32** Job-card endpoint → `feedback_labels`, close event, trigger new baseline
- [ ] **M2-33** False-alarm endpoint → label + per-machine threshold update
- [ ] **M2-34** Server-side replay tool: stream C4 / CWRU / IMS run-to-failure sequences through the full pipeline without the phone
- [ ] **M2-35** Dashboard (Streamlit): live health chart, events, diagnosis + evidence, plan timeline, audit log

### Week 6–7 · Testing
- [ ] **M2-36** Unit tests: idempotency, every rule branch, every state transition
- [ ] **M2-37** Safety tests: over-limit plan, invented quote/price, missing approval, expired plan, injected dealer instruction, wrong-number approval → 0 actions executed
- [ ] **M2-38** Agent eval: 20 scripted incidents, automatic checks, pass rate
- [ ] **M2-39** Voice eval: 40 yes/no clips (kn + hi), intent accuracy

---

## Joint integration points

| When | Integration | M1 delivers | M2 delivers |
|------|-------------|-------------|-------------|
| End of week 2 | Telemetry path | Phone replaying data and syncing feature rows | `/telemetry/batch` live |
| End of week 3 | Anomaly → plan (tap) | `/events/anomaly` + plan card | Agent v0 + approval engine |
| End of week 5 | Real models | On-device AE alerts | Real diagnosis + RUL in plans |
| End of week 6 | Voice loop | Voice note play + reply upload | Gnani TTS/STT, intent |
| Week 7 | Full flow | Offline SMS, feedback forms | Executor, feedback, replay |

**Done when:** a replayed fault sequence goes through alert → diagnosis → plan → Kannada/Hindi voice note → voice approval → sandbox execution → job card → new baseline, and all safety tests show 0 unauthorised actions.

## Load balance
- M1: 30 tasks, mostly Android and the anomaly model.
- M2: 39 tasks, mostly backend, diagnosis/RUL and agent.
- M2 has more work, so move **M2-24/M2-25 (RUL)** or **M2-35 (dashboard)** to M1 once M1's anomaly model is done.

## Deferred (hardware, add later)
ESP32 firmware, BLE sensor link on the phone (a new `WindowSource`), and recordings from a real motor. Because the replay input already uses the C4 format and the `WindowSource` interface, none of the tasks above change when the hardware is added.
