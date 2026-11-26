# SPANDAN backend

FastAPI + PostgreSQL. Covers tasks M2-01 – M2-03 and the audit log (M2-05) from `docs/10_Task_Split_Two_Members.md`.

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

## Notes
- All 13 tables from doc 07 exist (migration `0837ce1719ef`). Location is lat/lng floats, not PostGIS.
- `audit_log` is append-only: a database trigger blocks UPDATE and DELETE.
- Telemetry rows more than 10 min in the future or older than 60 days are rejected per row; a malformed batch (naive timestamps, NaN, health > 100, empty features) is rejected whole with 422.
- New migration after changing `app/models`: `.venv/Scripts/alembic revision --autogenerate -m "..."`.
