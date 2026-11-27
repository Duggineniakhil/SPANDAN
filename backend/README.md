# SPANDAN backend

FastAPI + PostgreSQL. Covers tasks M2-01 – M2-05, M2-07 – M2-18, M2-20, M2-21, M2-24, M2-26 – M2-34 from `docs/10_Task_Split_Two_Members.md`.

## Run (Windows, Git Bash or PowerShell)

```bash
cd backend
cp .env.example .env              # then set API_TOKEN
docker compose up -d              # Postgres 16 on localhost:5433 (+ spandan_test DB)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs. Every `/api/v1/*` call needs `Authorization: Bearer <API_TOKEN>`.

## Test

```bash
docker compose up -d
.venv/Scripts/python -m pytest -q
```

Tests use the `spandan_test` database and wipe it between tests.

## Endpoints so far

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | No token |
| POST | `/api/v1/owners` | 409 if phone already registered |
| GET | `/api/v1/owners/{id}` | |
| POST | `/api/v1/machines` | 404 unknown owner, 409 sensor already paired |
| GET | `/api/v1/machines?owner_id=` | |
| GET | `/api/v1/machines/{id}` | |
| POST | `/api/v1/machines/{id}/baseline/start` | from setup / monitoring / maintenance |
| POST | `/api/v1/machines/{id}/baseline/complete` | `{anomaly_threshold, model_version}` → monitoring |
| POST | `/api/v1/machines/{id}/windows` | Up to 3 raw windows (`baseline` or `alert`) for diagnosis |
| POST | `/api/v1/telemetry/batch` | Idempotent by `row_id`; returns `{accepted, duplicates, rejected}` |
| GET | `/api/v1/machines/{id}/telemetry?from&to&features&max_points` | Chart series; long ranges bucketed (max score, min health) |
| GET | `/api/v1/machines/{id}/health` | Latest reading, state, open event, pending plan |
| GET | `/api/v1/machines/{id}/diagnosis/latest` | Latest top faults + RUL |
| GET | `/api/v1/audit?machine_id&from&to&actor&limit` | Audit trail, newest first |
| POST | `/api/v1/events/anomaly` | Phone reports an anomaly → diagnosed → agent plans it in the background |
| GET | `/api/v1/events?machine_id=` / `/api/v1/events/{id}` | Events with diagnosis and plans |
| POST | `/api/v1/events/{id}/plan` | Run the agent now |
| GET | `/api/v1/plans/{id}` / `/api/v1/owners/{id}/plans?state=` | Plans |
| POST | `/api/v1/plans/{id}/decision` | Owner approve/reject; only from the owner's number (403), only while pending (409); approval runs the sandbox executor |
| GET | `/api/v1/owners/{id}/messages` | Owner inbox (kn/hi/en) |
| POST | `/api/v1/approval/sweep` | Reminders (24 h) and expiry (48 h) now; also runs every `APPROVAL_SWEEP_INTERVAL_S` |
| GET | `/api/v1/plans/{id}/voice-note` | The plan as an OGG/Opus voice note (Gnani TTS); 503 = no voice, show the text |
| POST | `/api/v1/plans/{id}/voice-reply` | Multipart `audio` + `from_phone` → STT → intent → approve / reject / re-plan / ask again |
| GET | `/api/v1/voice/phrases/{lang}/{name}` | Cached fixed phrases (`reask`, `use_buttons`, `approved`, `rejected`, `replanning`) |
| POST | `/api/v1/jobs/{id}/job-card` | Mechanic's job card: label, alert resolved, new baseline |
| POST | `/api/v1/alerts/{id}/false-alarm` | Owner: label, pending plan withdrawn, threshold +5 % (max +30 %) |
| POST | `/api/v1/sim/reset` | Recreate sandbox dealers, parts, mechanics, calendars |
| GET | `/api/v1/sim/messages?to_kind=` | What the sandbox dealers / mechanics were sent |

## Coordinator agent

Set `GROQ_API_KEY` and/or `GEMINI_API_KEY` in `.env`. `AGENT_PROVIDERS=groq,gemini` sets the order; the next
provider takes over on any failure (API error, timeout, or plans the rules keep rejecting). Without keys,
events are still diagnosed but not planned. Run `POST /api/v1/sim/reset` once so there are dealers and mechanics.

Code: `app/agent/` (tools, provider wrapper, loop, prompt), `app/sim/` (sandbox), `app/events.py`,
`app/analytics/worker.py` (diagnosis from raw windows: rules + the trained CWRU classifier; live RUL; falls back to `diagnosis_v0.py` feature ratios when no raw windows were sent). The model and RUL settings load from `../ml/results/` (`DIAGNOSIS_MODEL_PATH`, `RUL_CONFIG_PATH`); `DEFAULT_REPAIR_DAYS`, `READING_INTERVAL_MIN`.

Diagnosis building blocks (M2-20, M2-21): `app/analytics/bearings.py` + `bearings.csv` (fault frequencies from bearing
geometry), `signal.py` (Welch and envelope spectra), `rules.py` (physics rule scorer with evidence), and
`app/sim/vibration.py` (simulated raw windows for tests and replay). Not yet wired into the event flow: that
happens with the analytics worker (M2-26), which needs raw windows from the replay tool.

## Approval engine

`app/approval/`: state machine, owner decision, executor, reminder/expiry sweep and message templates
(doc 06 §5). The LLM never approves, books or pays. Silence never approves: plans expire after 48 h.
The Kannada/Hindi templates in `messages.py` still need a native speaker's check.

## Voice (Gnani)

Set `GNANI_API_KEY` (vachana.ai) in `.env`; without it there is no voice and the owner reads the text and taps.
ffmpeg must be on the PATH to accept browser/phone recordings (WebM, OGG, M4A...); only WAV works without it.

- `app/voice/provider.py`: `VoiceProvider` (`tts`, `stt`). `gnani.py`: the adapter (TTS `timbre-v3.0`, voices
  Shruthi (kn) / Shivani (hi); STT `prisma-v3.0`), retries the "one request at a time" 429.
- `notes.py`: the plan's voice note, generated right after planning and cached by text in `VOICE_DIR` (`var/voice/`, gitignored).
- `phrases.py` + `cache/`: fixed phrases in kn/hi/en, committed. Regenerate: `.venv/Scripts/python -m app.voice.phrases --force`.
- `intent.py`: keywords for short replies; one LLM call (Groq/Gemini) for longer or mixed ones; doubtful = `unclear`, never a guessed yes.
- `reply.py`: checks the number and the plan state **before** any audio leaves the server; stores the transcript and a
  reference to the recording in the audit log; `unclear` is asked again twice, then the owner is sent to the buttons;
  a request ("can the mechanic come tomorrow morning?") cancels the plan and the agent re-plans with those words.

Measured live (27 Nov 2026): a ~300-character Kannada script → 25–35 s note in about 5 s; STT about 1 s;
digits and ₹ amounts are read correctly, so scripts keep digits.

## Replay tool (M2-34)

Plays the phone against the running API from a recording: baseline → monitoring → alert (raw windows first) →
diagnosis → the agent's plan → approval (tap, or voice via Gnani) → job card with the true label → new baseline.

```bash
.venv/Scripts/python -m app.replay sim:bearing_outer --approve tap --job-card   # simulated run to failure
.venv/Scripts/python -m app.replay sim:imbalance --language hi --approve voice --job-card
.venv/Scripts/python -m app.replay ../ml/c4/cwru-bearing_outer-007-load1 --baseline 20   # a C4 session
.venv/Scripts/python -m app.replay sim:none --developing 0 --normal 500                  # false alerts?
```

`app/replay/phone.py` is the phone's feature set and z-score detector in Python (identical to `features.ts` /
`detector.ts` to 1e-12), `sources.py` the C4 window format and the simulated run to failure, `runner.py` the steps.
One window = one reading = `READING_INTERVAL_MIN` on a virtual clock ending now, so `--developing 60` fails in an
hour: days-left is then ~0 and the agent (correctly) can't book anything in time.

Measured on simulated runs: no false alert in 1,200 healthy readings (0.2 % of single readings cross the threshold;
the 3-in-a-row rule absorbs them). Alerts fire at ~3–12 % fault severity, before the fault has a clear signature, so
the cloud first says `unknown`; with fresh windows every 5 readings it names the fault from ~20 % severity.

## Repair feedback

`app/feedback.py`. A job card stores what was really wrong as a `feedback_labels` row (with `diagnosis_correct`),
resolves the alert and starts a new baseline: from then on diagnosis and RUL only use readings received since the
current baseline. A false alarm stores a label, withdraws a pending plan and raises the machine's threshold from
`threshold_base`. If the owner marks a false alarm while the agent is still planning, `submit_plan` re-reads the
event under a row lock and the planner stops (`agent_stopped`) instead of reopening it.

## Notes
- 16 tables: the 13 from doc 07 plus `quotes`, `messages` and `raw_windows`. Location is lat/lng floats, not PostGIS.
- `audit_log` is append-only: a database trigger blocks UPDATE and DELETE.
- Telemetry rows more than 10 min in the future or older than 60 days are rejected per row; a malformed batch (naive timestamps, NaN, health > 100, empty features) is rejected whole with 422.
- New migration after changing `app/models`: `.venv/Scripts/alembic revision --autogenerate -m "..."`.
