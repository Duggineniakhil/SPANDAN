# SPANDAN backend

FastAPI + PostgreSQL. Covers tasks M2-01 – M2-05, M2-07 – M2-18, M2-20, M2-21, M2-24, M2-26 from `docs/10_Task_Split_Two_Members.md`.

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

## Notes
- 15 tables: the 13 from doc 07 plus `quotes` and `messages` (migrations `0837ce1719ef`, `a6436a90e3ba`, `de4177445205`). Location is lat/lng floats, not PostGIS.
- `audit_log` is append-only: a database trigger blocks UPDATE and DELETE.
- Telemetry rows more than 10 min in the future or older than 60 days are rejected per row; a malformed batch (naive timestamps, NaN, health > 100, empty features) is rejected whole with 422.
- New migration after changing `app/models`: `.venv/Scripts/alembic revision --autogenerate -m "..."`.
