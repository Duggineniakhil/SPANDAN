# SPANDAN backend

FastAPI + PostgreSQL. Covers tasks M2-01 – M2-03, M2-05, M2-07 – M2-12 from `docs/10_Task_Split_Two_Members.md`.

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
| POST | `/api/v1/telemetry/batch` | Idempotent by `row_id`; returns `{accepted, duplicates, rejected}` |
| POST | `/api/v1/events/anomaly` | Phone reports an anomaly → diagnosed → agent plans it in the background |
| GET | `/api/v1/events?machine_id=` / `/api/v1/events/{id}` | Events with diagnosis and plans |
| POST | `/api/v1/events/{id}/plan` | Run the agent now |
| POST | `/api/v1/sim/reset` | Recreate sandbox dealers, parts, mechanics, calendars |

## Coordinator agent

Set `GROQ_API_KEY` and/or `GEMINI_API_KEY` in `.env`. `AGENT_PROVIDERS=groq,gemini` sets the order; the next
provider takes over on any failure (API error, timeout, or plans the rules keep rejecting). Without keys,
events are still diagnosed but not planned. Run `POST /api/v1/sim/reset` once so there are dealers and mechanics.

Code: `app/agent/` (tools, provider wrapper, loop, prompt), `app/sim/` (sandbox), `app/events.py`,
`app/analytics/diagnosis_v0.py` (placeholder diagnosis; RUL is a labelled placeholder until M2-24).

## Notes
- 14 tables: the 13 from doc 07 plus `quotes` (migrations `0837ce1719ef`, `a6436a90e3ba`). Location is lat/lng floats, not PostGIS.
- `audit_log` is append-only: a database trigger blocks UPDATE and DELETE.
- Telemetry rows more than 10 min in the future or older than 60 days are rejected per row; a malformed batch (naive timestamps, NaN, health > 100, empty features) is rejected whole with 422.
- New migration after changing `app/models`: `.venv/Scripts/alembic revision --autogenerate -m "..."`.
