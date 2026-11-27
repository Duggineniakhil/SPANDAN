# 11 · Member 1 Sync Guide (state on 27 Nov 2026)

Member 2's side (cloud) is far ahead. This page tells Member 1 what is already live, what the phone app
must send and read to plug into it, and a sensible order to build in.

## 1. Where things stand

| Area | Status |
|------|--------|
| Backend API + DB (M2-01 – M2-05) | ✅ live: owners, machines, baseline, telemetry, health, audit |
| Anomaly events + server backup rule (M2-07) | ✅ |
| Sandbox dealers/mechanics + coordinator agent (M2-08 – M2-12) | ✅ Groq + Gemini fallback, writes the plan and the owner's message in Kannada/Hindi |
| Approval engine (M2-13 – M2-18) | ✅ owner approve/reject (only from the registered number), executor, 24 h reminder, 48 h expiry, owner messages |
| Diagnosis + RUL models (M2-19 – M2-25) | ✅ trained/evaluated (CWRU 87 % accuracy; IMS RUL); wiring into live events is next (M2-26) |
| Voice (Gnani), job card, false alarm (M2-27 – M2-33) | ⏳ not built yet |
| **Android app (all M1 tasks)** | ❌ **nothing in the repo yet** (no `android/` folder, no commits from Member 1) |

**The web app (`frontend/`) already does the phone's job in a browser**, so it is a working reference for
everything below:

| Web file | Matches M1 task | What to port |
|----------|-----------------|--------------|
| `src/lib/signal.ts` | M1-04 (input) | Simulated sensor; on Android this is the replay `WindowSource` |
| `src/lib/features.ts` | M1-07 / M1-08 | Feature names and maths (port to Kotlin) |
| `src/lib/detector.ts` | M1-15 – M1-17 | Baseline fit, score, threshold, health index, 3-in-a-row alert rule (works before the TFLite model exists) |
| `src/lib/gateway.ts` | M1-05, M1-06, M1-19, M1-20 | Offline queue, batch sync, alert → `POST /events/anomaly`, report again when back online |
| `src/components/RepairPanel.tsx` | M1-23 | Plan card: diagnosis, days left, part/mechanic/total, owner message, Approve/Reject, inbox |
| `src/pages/Setup.tsx` | M1-22 | Owner + machine registration, start baseline |

## 2. The contract the phone must follow

Interactive docs: run the backend and open `http://<laptop-ip>:8000/docs`. All calls: `Authorization: Bearer <API_TOKEN>`.
Put the token in `local.properties` → `BuildConfig`, never in git.

### Setup (M1-22)
1. `POST /api/v1/owners` `{name, phone, language: "kn"|"hi"|"en", spending_limit_inr, idle_windows: [{dow, start, end}]}`.
   **`phone` must be the owner's real SIM number**: approvals from any other number are refused (403).
2. `POST /api/v1/machines` `{owner_id, name, motor_rpm, bearing_model: "6205-2RS", sensor_id}`. The bearing model drives the fault frequencies.
3. `POST /api/v1/machines/{id}/baseline/start` → upload baseline readings → `POST …/baseline/complete` `{anomaly_threshold, model_version}`.

### Telemetry (M1-06)
`POST /api/v1/telemetry/batch` `{device_id, machine_id, rows: [...]}`, up to 1,000 rows, retries are safe (`row_id` UUID).
- `ts` **with timezone** (`2026-12-10T09:31:00+05:30`), no NaN/Infinity.
- **Baseline rows: no `anomaly_score`.** The server uses them as the machine's "normal" for diagnosis and RUL.
- **Monitoring rows: `anomaly_score` + `health_index` (0–100) + `model_version`.**
- Feature names the cloud reads now (keep these exact names): `rms_y` (RUL), `env_bpfo_y`, `kurtosis_y`, `amp_1x_y`,
  `amp_3x_y`, `band_0_25_y` (diagnosis). Send the full set from `features.ts`; extra features are kept.

### Alert (M1-20)
On the 3rd reading in a row over the threshold: `POST /api/v1/events/anomaly` `{machine_id, started_at, peak_score}`.
Sync the queued rows first. Offline: send the SMS (M1-19), keep the report, send it when the network is back.
201 = new event, 200 = already open (the server's backup rule may have opened it from uploaded rows; both are fine).

### Plan card + approval (M1-23)
- Poll `GET /api/v1/machines/{id}/health` → `open_event`, `pending_plan_id`.
- `GET /api/v1/events/{event_id}` → `diagnosis` (top faults with `evidence`, `rul_days_low/high`) and `plans`.
- Show the plan's `actions` (`buy_part`, `book_mechanic`), `total_cost_inr` and `voice_script.text` (owner's language).
- Approve/Reject: `POST /api/v1/plans/{id}/decision` `{decision: "approve"|"reject", channel: "tap", from_phone: <SIM number>}`.
  Handle **403** (wrong number), **409** (already decided or expired). The response says `executed` and, if the slot
  was lost, `replanning: true`.
- Inbox / notifications: `GET /api/v1/owners/{id}/messages` (plan, reminder, booking, expiry … already in the owner's language).

### Coming next from Member 2 (build the screens, wire when ready)
`GET /plans/{id}/voice-note`, `POST /plans/{id}/voice-reply` (M1-24, M1-25), `POST /jobs/{id}/job-card` (M1-27),
`POST /alerts/{id}/false-alarm` (M1-26).

## 3. Suggested order for Member 1
1. **M1-03** Android skeleton, then push it (`android/` folder, a branch + pull request is fine).
2. **M1-22** Setup screen → the three setup calls above.
3. **M1-04 + M1-08** replay input + Kotlin features (port `features.ts`), **M1-05/M1-06** Room + sync.
4. **M1-16/M1-17** baseline + score + alert rule using the simple detector from `detector.ts`. Swap in the TFLite autoencoder (M1-12 – M1-15) later.
5. **M1-20** alert report, **M1-23** plan card + approve/reject. At this point the full demo runs on the phone.
6. Then **M1-19** SMS, **M1-21** home screen polish, **M1-28** strings, then the anomaly model (M1-10 – M1-14), which can be trained on Kaggle like `ml/notebooks/`.

**Load balance:** doc 10 said to move RUL or the dashboard from M2 to M1. That is no longer needed: both are
done or nearly done on the M2 side. If Member 1 is short of time, Member 2 can instead take **M1-01/M1-02**
(dataset converters, replay sequences) or the **anomaly-model training** (M1-10 – M1-14) on Kaggle.
