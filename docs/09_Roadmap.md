# 09 · Prototype Roadmap

Assumes a team of 4 working part-time alongside college. Roles (one person can hold two):

| Role | Owns |
|------|------|
| **HW** — Hardware & firmware | Sensor node, bench rig, data collection sessions |
| **APP** — Android | Phone gateway, owner UI, offline/SMS, voice record/playback |
| **ML** — Models | Datasets, features, 3 models, TFLite export, REPORT.md |
| **BE** — Backend & agent | FastAPI, DB, rules engine, agent, voice service, simulator, dashboard |

Timeline: **8 weeks** (a compressed 4-week path is at the end). The folder doesn't state the prototype deadline, so map weeks to real dates once it's known.

---

## Phase 0 — Setup & procurement (Week 0, 3–4 days)

| Task | Owner | Output |
|------|-------|--------|
| Order ESP32, 2× ADXL345, magnets, motor, bearings, pillow blocks, safety gear | HW | Parts ordered (motor + bearings have the longest lead time — order day 1) |
| Create monorepo with folder layout (doc 02 §5), README, `.gitignore`, `.env.example` | BE | Repo on GitHub |
| Download MIMII, CWRU, NASA IMS; write `MANIFEST.csv` | ML | Data ready |
| Android project skeleton (Compose, Room, foreground service) | APP | Builds and runs |
| Get API keys: Anthropic, Bhashini (TTS/STT backup); test IndicConformer + Parler-TTS locally | BE | "Hello" voice in kn + hi |
| Book 3–5 mill owner interviews + 1 mill visit | All | Calendar |

**Exit:** parts arriving, repo exists, datasets on disk, voice models produce audio.

---

## Phase 1 — Thin end-to-end slice (Weeks 1–2)  ⭐ most important

Goal: one ugly but complete path through every box, using simple placeholders.

| Task | Owner | Placeholder allowed |
|------|-------|---------------------|
| Firmware: ADXL345 at 3,200 Hz, stream chunked windows over BLE; **measure throughput** | HW | — |
| Phone: receive windows, compute 5 features (RMS, peak, crest, kurtosis, 1×), show live value | APP | Few features |
| Phone: z-score threshold anomaly rule (no ML yet), local Room store, sync to API | APP | Rule instead of AE |
| API: `/telemetry/batch`, `/machines`, Postgres via docker compose, Alembic migrations | BE | — |
| Worker: fake diagnosis ("bearing_outer, 0.7, RUL 4–8 days") on anomaly event | BE | Hard-coded |
| Agent v0: Messages API tool loop with `get_machine_context`, `search_parts`, `find_repair_slots`, `submit_plan` on simulator data | BE | 3 dealers, 2 mechanics |
| Rules engine v0: spending limit + state machine + audit log | BE | — |
| Phone: plan card with Approve/Reject buttons → `/plans/{id}/decision` | APP | Tap only, no voice |
| Python feature module + golden file | ML | — |

**Exit demo (end of week 2):** shake/tap the sensor → phone alert → plan card appears → tap Approve → audit log shows booking in sandbox.

---

## Phase 2 — Bench rig & data collection (Weeks 2–4, overlaps)

| Task | Owner | Output |
|------|-------|--------|
| Build bench rig with guards (doc 03 §5) | HW | Running rig |
| Debug-mode raw window recording on phone/laptop | APP/HW | Raw `.npy` per window with session metadata |
| Record sessions: Normal ×6, IMB ×3, MIS ×3, LOOSE ×3, BRG-OR ×3 | HW | ~20 sessions, logged |
| Start progressive-wear runs (BRG-DEG), repeat across days | HW | Run-to-failure-ish data |
| Mill visit: record normal running, nameplate, owner interview | All | Real-world data + field notes |
| Owner/mechanic interviews | All | `field_notes.md` |

**Exit:** labelled bench dataset with session-level splits; at least one real-mill normal recording.

---

## Phase 3 — Real models (Weeks 3–5)

| Task | Owner | Output |
|------|-------|--------|
| Full feature set (~30) in Python; port to Kotlin; golden test passes in both | ML + APP | Parity ✅ |
| Anomaly: AE + Isolation Forest on MIMII (held-out IDs) → AUC | ML | Table |
| Anomaly: AE on bench normal → AUC per fault + false alarms/week | ML | Table |
| Export TFLite + scaler; integrate on phone; health index; per-machine threshold from baseline | ML + APP | On-device AE |
| Diagnosis: bearing frequency rules + HistGB classifier; CWRU (split by load) + bench | ML | Confusion matrices |
| RUL: exponential fit + bootstrap interval on IMS (leave-one-bearing-out) | ML | MAE + coverage |
| Wire real diagnosis + RUL into worker, replacing fakes | BE + ML | Real outputs in plans |
| `ml/REPORT.md` v1 | ML | Numbers for slide 9 |

**Exit:** induced bench fault → real AE alert on phone → real top-3 diagnosis with evidence string.

---

## Phase 4 — Agent, approvals, voice (Weeks 4–6)

| Task | Owner | Output |
|------|-------|--------|
| Full tool set incl. `request_quote`, `check_mechanic_availability`; simulator with messy multilingual replies + injection message | BE | `sim/` |
| Rules engine: all 5 checks, retries, expiry, 24 h reminder (APScheduler), executor for approved actions | BE | Safety tests pass |
| Voice out: LLM voice_script → TTS (kn/hi) → audio on plan; phone plays it | BE + APP | Voice note |
| Voice in: record → upload → IndicConformer → keyword intent → LLM fallback → decision | BE + APP | Voice approval |
| Offline SMS path + sensor-silent alert | APP | Works with data off |
| False-alarm button → threshold adjust; mechanic job card form → baseline reset | APP + BE | Feedback loop |
| Agent eval: 20 scripted incidents | BE | Pass rate |
| Voice eval: 40 yes/no clips from friends/family (kn + hi) | BE | Accuracy |

**Exit:** full demo script (doc 08 §3) works end to end on the bench, including voice approval.

---

## Phase 5 — Hardening, dashboard, demo polish (Weeks 6–7)

| Task | Owner | Output |
|------|-------|--------|
| Judge dashboard: live health chart, events, plan timeline, audit log | BE | Web page |
| 24 h soak test; fix crashes, reconnects, memory | APP + HW | Stable |
| Replay mode (recorded session → pipeline) as demo backup | BE + APP | Backup path |
| Enclosure + clean wiring for sensor node; label the rig | HW | Presentable hardware |
| Kannada/Hindi copy review by a native speaker | All | Correct language |
| Update deck: real metrics on slide 9, photos of rig + app, field-interview quotes | All | Deck v2 |

**Exit:** two clean rehearsals in a row with no manual fixes.

---

## Phase 6 — Final (Week 8)

| Task | Owner |
|------|-------|
| Record 3-min demo video (backup + submission) | All |
| Final README in repo: setup, run, architecture image, metrics, limitations | BE |
| Freeze code, tag `v1.0-prototype`, export APK | All |
| Rehearse Q&A: data leakage, why one LLM, safety, cost, scaling, business model | All |

---

## Milestone summary

| Week | Milestone | Proof |
|------|-----------|-------|
| 0 | Kick-off | Parts ordered, repo, datasets |
| 2 | **M1 Thin slice** | Tap sensor → plan → approve (tap) |
| 4 | **M2 Data** | Labelled bench sessions + mill recording |
| 5 | **M3 Real models** | On-device AE + real diagnosis/RUL + REPORT v1 |
| 6 | **M4 Full loop** | Voice approval, offline SMS, feedback loop |
| 7 | **M5 Demo-ready** | Dashboard, soak test, 2 clean rehearsals |
| 8 | **M6 Submitted** | Video, repo, APK, updated deck |

## Compressed 4-week path (if the deadline is close)

| Week | Do | Cut / simplify |
|------|----|----------------|
| 1 | Phase 0 + Phase 1 together; buy a ready-made small motor + pillow blocks | No enclosure |
| 2 | Bench sessions (Normal, IMB, BRG-OR only); AE + IF on bench + MIMII | Skip MIS/LOOSE; skip real-mill visit if impossible |
| 3 | Rules-based diagnosis + classifier on CWRU; RUL on IMS; agent + rules engine + Kannada voice out, tap-to-approve | Hindi voice optional; voice reply only keyword-based |
| 4 | Voice reply, SMS, dashboard-lite (Streamlit), rehearsals, video | Mechanic job card as a simple form |

Never cut: the approval/rules engine, the leakage-free evaluation, offline detection on the phone. Those are the core claims in the deck.

## Day-1 checklist
- [ ] Order hardware (motor, bearings, ESP32, ADXL345 ×2, magnets)
- [ ] Create GitHub repo + folder layout + `.env.example`
- [ ] Start MIMII / CWRU / IMS downloads
- [ ] Android skeleton builds
- [ ] `docker compose up` with Postgres + empty FastAPI
- [ ] Message 5 mill owners for interviews
