# 08 · Test, Demo & Risk Plan

## 1. Test strategy

| Level | What | Tool | Pass criteria |
|-------|------|------|---------------|
| Unit — firmware | Chunk framing, CRC, FIFO read | PlatformIO native tests | All pass |
| Unit — features | Python vs Kotlin on `features_golden.json` | pytest + JUnit | Max abs diff < 1e-4 |
| Unit — backend | Batch idempotency, rules engine, state machine transitions | pytest | 100 % of rule branches covered |
| Safety tests | Over-limit plan, invented quote, missing approval, expired plan, injected dealer instruction, approval from wrong number | pytest | **0 actions executed** in every case |
| Integration | Phone → API → worker → agent → approval → executor with sim | docker compose + scripted replay | Full flow < 2 min |
| Replay test | Feed recorded bench session (normal → fault) through the phone pipeline in "replay mode" | `sim/replay.py` + debug build | Alert raised, correct top-1 fault |
| Offline | Data off during fault | Manual on device | SMS within 2 min; rows sync after reconnect, no duplicates |
| Soak | 24 h bench run | Manual | No crash, no leak, ≤ 1 false alarm |
| Voice | 40 clips (10 speakers × kn/hi × yes/no) | STT + intent script | ≥ 95 % correct, unclear → re-ask |
| Agent eval | 20 scripted incidents (doc 06 §9) | pytest + live API | ≥ 18/20 pass, 0 unauthorised actions |

## 2. Metrics to report (fill slide 9)

| Model | Metric | Dataset | Value |
|-------|--------|---------|-------|
| Anomaly (AE) | AUC / false alarms per week | MIMII (held-out IDs), bench | _TBD_ |
| Anomaly (IF baseline) | AUC | same | _TBD_ |
| Diagnosis | Accuracy, macro-F1, confusion matrix | CWRU (split by load), bench | _TBD_ |
| RUL | MAE (days), interval coverage | NASA IMS (leave-one-bearing-out) | _TBD_ |
| Bench end-to-end | Lead time before failure threshold | Bench progressive wear | _TBD_ |
| Agent | Pass rate, unauthorised actions | 20 scripted incidents | _TBD_ |

## 3. Demo script (5–7 minutes)

| t | Scene | What judges see |
|---|-------|-----------------|
| 0:00 | Problem in 20 s | Photo/video of a mill, cost of one breakdown day |
| 0:30 | Setup | Clip sensor on bench rig, phone shows health 96 % green, dashboard live chart |
| 1:15 | Induce fault | Swap in damaged bearing (or add imbalance bolt) — health drops to ~40 %, alert |
| 2:00 | Offline | Turn off phone data → SMS arrives in Kannada/Hindi |
| 2:30 | Diagnosis | Back online: dashboard shows "Outer race bearing fault, 71 %; evidence BPFO 172 Hz", RUL range |
| 3:00 | Agent at work | Audit log streams: context → 3 quote requests → messy dealer reply interpreted → slots found → plan submitted → rules pass |
| 3:45 | Voice note | Phone plays the Kannada voice note (subtitles on screen) |
| 4:15 | Approve by voice | Owner says "ಹೌದು" → plan approved → mechanic booked, dealer confirmed (sandbox), downtime scheduled |
| 4:45 | Safety | Show: over-budget plan blocked; injected dealer message ignored; no reply = nothing happens |
| 5:15 | Feedback | Mechanic job card → baseline reset → health back to green |
| 5:45 | Numbers + scale | Metrics table, BOM ₹1,200, roadmap to powerlooms/pumps |

**Backup plan:** pre-recorded video of the full flow + replay mode (feeds a recorded session through the real pipeline) if the rig or network fails. Pre-generated voice notes cached.

## 4. Field validation (strongly recommended)
- Interview 3–5 flour mill owners (15 min each): breakdowns per year, downtime days, cost per breakdown, how they find mechanics/parts, phone type, language, willingness to pay per month. Record answers in `docs/field_notes.md`.
- One recording session at a real mill (normal running).
- One mechanic interview: typical faults, bearing types, what info they want before visiting.

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|-----------|
| R1 | BLE throughput too low for 3-axis 3.2 kHz | M | M | Decimate X/Z, or FFT on ESP32; measure in week 1 |
| R2 | ADXL345 noise floor hides early bearing defects | M | M | Rigid magnet mount; seeded defects big enough; ADXL355 upgrade; honest limitation |
| R3 | Bench doesn't reproduce progressive wear in time | H | M | Use IMS for RUL claims; bench sand/no-grease runs over several sessions; show RUL in hours on bench |
| R4 | Domain gap: CWRU (12 kHz lab) vs our sensor | H | M | Resample, rules-based layer (physics) carries generalisation; validate on bench |
| R5 | MIMII is audio not vibration | — | L | Present it as method validation; bench is the vibration evidence |
| R6 | Kannada/Hindi STT errors on yes/no | M | H | Keyword rules + re-ask + tap fallback; test 40 clips |
| R7 | TTS too slow on CPU | M | L | Bhashini API or pre-generate; cache phrases |
| R8 | LLM invents prices/slots | L | H | Rules engine verifies every ID/price against DB; strict tool schemas |
| R9 | Prompt injection via dealer replies | M | H | Replies treated as data; executor only runs rule-validated actions; injection test in suite |
| R10 | Android kills background service | M | M | Foreground service, battery-opt exemption, boot receiver |
| R11 | Team bandwidth / deadline | M | H | Thin end-to-end slice first (roadmap Phase 1); cut P1 features before P0 |
| R12 | Bench safety incident | L | H | Guards, RCCB, e-stop, never alone, eye protection |
