# 09 · Prototype Roadmap (Software First)

Two members, software only for now. Sensor input comes from **public datasets replayed through the pipeline** (MIMII, CWRU, NASA IMS). Hardware is added at the **Hardware Checkpoint** (week 6) once the software is nearly complete.

| Member | Area |
|--------|------|
| **M1 — Edge & Detection** | Replay input, features, anomaly model, Android app, offline/SMS, voice record/playback |
| **M2 — Cloud & Intelligence** | Backend, diagnosis, RUL, agent, approval engine, voice (STT/TTS), simulator, dashboard |

Task IDs refer to [doc 10](10_Task_Split_Two_Members.md). Timeline: **7 weeks of software + hardware track from week 6**. The prototype deadline isn't in the folder, so map weeks to real dates once it's known.

---

## Phase 0 — Foundations (first 2–3 days)

| Work | Owner |
|------|-------|
| Agree shared contracts C1–C4 (features, API JSON, plan schema, window file format) | M1 + M2 |
| Download MIMII, CWRU, NASA IMS | M1 (MIMII), M2 (CWRU, IMS) |
| Android skeleton (M1-03) | M1 |
| FastAPI + Postgres + migrations (M2-01) | M2 |
| Test Gnani API: Kannada + Hindi TTS and STT work, note audio formats, latency and limits | M2 |

**Exit:** contracts written, datasets on disk, both skeletons run.

---

## Phase 1 — Thin end-to-end slice (Weeks 1–2)  ⭐ most important

One rough but complete path through every box, using placeholders.

| Work | Owner | Placeholder allowed |
|------|-------|---------------------|
| Dataset → C4 converters + replay sequences (M1-01, M1-02) | M1 | — |
| Phone replay input, Room DB, sync worker (M1-04 – M1-06) | M1 | 5 simple features, z-score rule instead of ML |
| Telemetry API, audit log, fake-telemetry script, server anomaly rule (M2-02 – M2-07) | M2 | — |
| Simulator + agent v0 with core tools (M2-08, M2-10 – M2-12) | M2 | Hard-coded diagnosis "bearing_outer, 0.7, 4–8 days" |
| Rules engine v0: spending limit + states + audit (part of M2-13, M2-15) | M2 | — |
| Plan card with Approve/Reject (M1-23) | M1 | Tap only, no voice |

**Exit (end of week 2):** replay a fault sequence → phone alert → plan card → tap Approve → audit log shows sandbox booking.

---

## Phase 2 — Features & real models (Weeks 2–5)

| Work | Owner |
|------|-------|
| Full features in Python + Kotlin, golden test passes (M1-07 – M1-09) | M1 |
| Anomaly: IF baseline + autoencoder, leakage-free eval, TFLite export (M1-10 – M1-14) | M1 |
| On-device inference, baseline mode, health index, alerts, SMS (M1-15 – M1-20) | M1 |
| Diagnosis: bearing frequency rules + classifier + eval on CWRU (M2-19 – M2-23) | M2 |
| RUL: exponential fit + bootstrap, eval on IMS (M2-24, M2-25) | M2 (or M1 if M2 is behind) |
| Analytics worker wiring real diagnosis + RUL (M2-26) | M2 |

**Exit:** replayed fault → real autoencoder alert on phone → real top-3 diagnosis with evidence → RUL range in plan. Metrics written to `ml/REPORT.md`.

---

## Phase 3 — Agent, approvals, voice (Weeks 4–6)

| Work | Owner |
|------|-------|
| Messy multilingual dealer replies + injection test case (M2-09) | M2 |
| Full rules engine, retries, scheduler, executor, approval from registered number only (M2-13 – M2-18) | M2 |
| Gnani voice adapter (TTS + STT), phrase cache, intent detection, voice endpoints, re-plan on question (M2-27 – M2-31) | M2 |
| Home, setup, voice playback, voice reply, false alarm, job card, kn/hi/en strings (M1-21, M1-22, M1-24 – M1-28) | M1 |

**Exit:** full flow on replay: alert → diagnosis → plan → Kannada/Hindi voice note → voice approval → sandbox execution.

---

## 🔔 HARDWARE CHECKPOINT (start of week 6, when Phase 3 is nearly done)

> **Reminder:** when the end-to-end flow works on replayed data, start the hardware track. The software doesn't need to change; the sensor is just a new input source.

### Why build it (worth the effort)
- **The submission promises it.** `PS_Details.txt` and slides 3, 5, 7, 8 and 11 describe a clip-on ESP32 + accelerometer sensor; slide 9 promises "our own recordings" and "our bench rig". A software-only prototype leaves that promise open.
- **It's the most memorable part of the demo.** Judges remember a phone reacting live to a real vibrating machine far more than a chart from a dataset.
- **It proves the "low-cost" and "works offline on the phone" claims** instead of just stating them.
- **It makes the results more believable:** a few minutes of your own normal vs fault data checks the models outside the lab datasets.

### What to build (minimal, about ₹600–1,000, about 1–1.5 weeks)

| Step | Work | Reference |
|------|------|-----------|
| H1 | Buy ESP32 DevKit, ADXL345 module, neodymium magnet, USB adapter. **Order at the start of week 5** so parts arrive by week 6 | doc 03 §1 |
| H2 | Firmware: ADXL345 at 3,200 Hz over SPI, chunked BLE streaming, CONTROL/STATUS characteristics | doc 03 §2, §4 |
| H3 | Measure BLE throughput on your phone; decimate X/Z if needed | doc 03 §4 |
| H4 | Android: BLE `WindowSource` (scan, connect, reassemble, CRC, reconnect) — plugs into the existing pipeline | doc 04 §3 |
| H5 | Mount the sensor on any motor you have (table fan, water pump, mixer-grinder) | — |
| H6 | Record a few sessions: normal (re-mounted 3×), imbalance (coin/tape weight on blade), looseness (loosened mount) | doc 03 §5 |
| H7 | Run the anomaly model on these recordings; add the numbers to `ml/REPORT.md` | doc 05 |
| H8 | Watchdog + heartbeat; tidy box for the sensor | doc 03 §4 |

**Optional, only if time remains:** the full bench rig with a damaged bearing (doc 03 §5) for bearing-fault data.

**If the hardware isn't ready in time:** keep replay as the main path; nothing in the software depends on the sensor.

---

## Phase 4 — Integration & hardening (Weeks 6–7)

| Work | Owner |
|------|-------|
| Feedback endpoints, server-side replay tool, dashboard (M2-32 – M2-35) | M2 |
| Unit, safety, agent and voice tests (M2-36 – M2-39) | M2 |
| App tests + 24 h soak on replay (M1-29, M1-30) | M1 |
| Hardware track H1–H8 (alongside) | M1 (firmware + BLE), M2 helps with recordings |

**Exit:** two full runs in a row with no manual fixes, all safety tests at 0 unauthorised actions, and (if hardware is done) the same flow driven by the live sensor.

---

## Milestone summary

| Week | Milestone | Proof |
|------|-----------|-------|
| 0 | Foundations | Contracts, datasets, skeletons |
| 2 | **M1 Thin slice** | Replay fault → plan → tap approve |
| 5 | **M2 Real models** | On-device AE, real diagnosis + RUL, REPORT v1 |
| 6 | **M3 Full software loop** | Voice approval end to end on replay · 🔔 **start hardware** |
| 7 | **M4 Software complete** | Tests pass, soak done, dashboard |
| 7–8 | **M5 Hardware added** | Live sensor drives the same flow |

## Compressed 4-week path

| Week | Do | Cut / simplify |
|------|----|----------------|
| 1 | Phase 0 + Phase 1 | Fewer features |
| 2 | Anomaly AE + IF, on-device; rules-based diagnosis on CWRU | Skip classifier if short of time |
| 3 | RUL on IMS; full approval engine; Kannada voice out, tap approve | Hindi voice optional |
| 4 | Voice reply (keywords), SMS, Streamlit dashboard-lite, tests · 🔔 hardware only if week 3 finished on time | Hardware optional |

Never cut: the approval/rules engine, the leakage-free evaluation, offline detection on the phone.
