# 07 · API & Data Model

Base URL: `/api/v1`. JSON everywhere. Prototype auth: one static device token per phone (`Authorization: Bearer <device_token>`) and one admin token for the dashboard.

## 1. Endpoints

### Setup
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/owners` | Create owner (name, phone, language `kn`/`hi`, spending_limit_inr, idle_hours) |
| POST | `/machines` | Register machine (owner_id, name, type, motor_rpm, bearing_model, sensor_mac) |
| POST | `/machines/{id}/baseline/start` | Start baseline period |
| POST | `/machines/{id}/baseline/complete` | Mark baseline done; upload threshold + model version |

### Telemetry
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/telemetry/batch` | Upload feature rows (idempotent) |
| GET | `/machines/{id}/telemetry?from&to` | Time series for dashboard |
| GET | `/machines/{id}/health` | Latest health index, anomaly score, state |

`POST /telemetry/batch` request:
```json
{
  "device_id": "phone-01",
  "machine_id": "m-001",
  "rows": [
    {
      "row_id": "3f6c...uuid",
      "ts": "2026-12-10T09:31:00+05:30",
      "features": { "rms_x": 0.21, "rms_y": 0.18, "rms_z": 0.09, "kurtosis_y": 3.4,
                    "crest_y": 4.1, "peak_y": 0.86, "band_0_500": 0.12, "...": 0 },
      "anomaly_score": 0.73,
      "health_index": 41,
      "model_version": "ae-m001-v3",
      "rpm_estimate": 2880
    }
  ]
}
```
Response: `{"accepted": 58, "duplicates": 2, "rejected": []}`. Rows with an existing `row_id` are counted as duplicates (safe retry). A malformed batch → 422 and the phone retries later.

### Events, diagnosis, plans
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/events/anomaly` | Phone reports a confirmed anomaly → 201 new (diagnosed, auto-planned) or 200 existing open event. The server also opens one after 3 readings over the threshold |
| GET | `/events?machine_id=&open_only=` | Events for a machine |
| GET | `/events/{id}` | Event with its diagnosis and plans |
| POST | `/events/{id}/plan` | Run the coordinator agent now (synchronous) |
| POST | `/sim/reset` | Recreate sandbox dealers, parts, mechanics and calendars |
| GET | `/machines/{id}/diagnosis/latest` | Top-3 faults + RUL |
| GET | `/plans/{id}` | Plan detail |
| GET | `/owners/{id}/plans?state=pending` | Pending plans for app |
| POST | `/plans/{id}/decision` | `{ "decision": "approve" \| "reject", "channel": "tap" \| "voice", "audio_ref": "..." }` |
| POST | `/plans/{id}/voice-reply` | Multipart audio upload → Gnani STT → intent → decision |
| GET | `/plans/{id}/voice-note` | Gnani-generated TTS audio (ogg/mp3), or cached fallback |

### Feedback
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/jobs/{id}/job-card` | Mechanic: actual fault, parts replaced, notes, photo (optional) |
| POST | `/alerts/{id}/false-alarm` | Owner marks false alarm |

### Audit & admin
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/audit?machine_id&from&to` | Audit log |
| POST | `/sim/reset` | Reset sandbox dealers/mechanics (demo only) |

## 2. Database schema (PostgreSQL)

```sql
CREATE TABLE owners (
  id UUID PRIMARY KEY, name TEXT, phone TEXT, language TEXT CHECK (language IN ('kn','hi','en')),
  spending_limit_inr INT NOT NULL DEFAULT 2000,
  idle_windows JSONB,            -- e.g. [{"dow":6,"start":"09:00","end":"14:00"}]
  location GEOGRAPHY(POINT) NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE machines (
  id UUID PRIMARY KEY, owner_id UUID REFERENCES owners(id), name TEXT,
  machine_type TEXT,             -- 'flour_mill_motor', 'bench_rig'
  motor_rpm INT, bearing_model TEXT,   -- e.g. '6205-2RS'
  sensor_mac TEXT UNIQUE, state TEXT DEFAULT 'setup', -- setup|baseline|monitoring|alert|maintenance
  anomaly_threshold REAL, model_version TEXT, baseline_started_at TIMESTAMPTZ, baseline_done_at TIMESTAMPTZ
);

CREATE TABLE telemetry (
  row_id UUID PRIMARY KEY, machine_id UUID REFERENCES machines(id), ts TIMESTAMPTZ NOT NULL,
  features JSONB NOT NULL, anomaly_score REAL, health_index REAL, model_version TEXT,
  received_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON telemetry (machine_id, ts DESC);

CREATE TABLE anomaly_events (
  id UUID PRIMARY KEY, machine_id UUID REFERENCES machines(id), started_at TIMESTAMPTZ,
  peak_score REAL, status TEXT DEFAULT 'open',   -- open|diagnosed|planned|resolved|false_alarm
  source TEXT                                     -- phone|server
);

CREATE TABLE diagnoses (
  id UUID PRIMARY KEY, event_id UUID REFERENCES anomaly_events(id),
  faults JSONB,          -- [{"fault":"outer_race","confidence":0.71,"evidence":"BPFO peak 3.6x"}, ...]
  rul_days_low REAL NULL, rul_days_high REAL NULL, rul_status TEXT, -- ok|insufficient_data|low_confidence
  model_versions JSONB, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE dealers (id UUID PRIMARY KEY, name TEXT, phone TEXT, location GEOGRAPHY(POINT), sandbox BOOL DEFAULT true);
CREATE TABLE parts_catalog (id UUID PRIMARY KEY, dealer_id UUID REFERENCES dealers(id), part_code TEXT,
  description TEXT, price_inr INT, in_stock BOOL, lead_time_days INT);
CREATE TABLE mechanics (id UUID PRIMARY KEY, name TEXT, phone TEXT, skills TEXT[], rate_inr INT,
  location GEOGRAPHY(POINT), sandbox BOOL DEFAULT true);
CREATE TABLE mechanic_slots (id UUID PRIMARY KEY, mechanic_id UUID REFERENCES mechanics(id),
  start_at TIMESTAMPTZ, end_at TIMESTAMPTZ, status TEXT DEFAULT 'free'); -- free|held|booked

CREATE TABLE quotes (               -- dealer answers; the stored price is the source of truth
  id UUID PRIMARY KEY, event_id UUID REFERENCES anomaly_events(id), dealer_id UUID REFERENCES dealers(id),
  part_id UUID REFERENCES parts_catalog(id), part_code TEXT, qty INT, unit_price_inr INT NULL,
  lead_time_days INT NULL, status TEXT, dealer_reply TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
-- mechanic_slots also has held_for_event_id + held_until (slot held while a plan awaits approval)
-- dealers also has reply_style (how the sandbox dealer writes)

CREATE TABLE plans (
  id UUID PRIMARY KEY, event_id UUID REFERENCES anomaly_events(id), owner_id UUID REFERENCES owners(id),
  plan JSONB NOT NULL,     -- see doc 06 §4 for schema
  total_cost_inr INT, state TEXT DEFAULT 'pending',  -- draft|pending|approved|rejected|expired|executed|cancelled
  voice_script JSONB, voice_audio_path TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), expires_at TIMESTAMPTZ, decided_at TIMESTAMPTZ, decided_via TEXT
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY, plan_id UUID REFERENCES plans(id), mechanic_id UUID REFERENCES mechanics(id),
  slot_id UUID REFERENCES mechanic_slots(id), status TEXT DEFAULT 'scheduled', -- scheduled|done|no_show
  job_card JSONB NULL      -- {"actual_fault":"outer_race","parts":["6205-2RS"],"notes":"..."}
);

CREATE TABLE feedback_labels (
  id UUID PRIMARY KEY, machine_id UUID, event_id UUID NULL, label TEXT, -- fault name | false_alarm
  source TEXT, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_log (               -- append-only; no UPDATE/DELETE grants for the app user
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), actor TEXT,   -- system|agent|owner|mechanic|operator
  action TEXT, entity TEXT, entity_id UUID, details JSONB
);
```

## 3. Phone-side (Room) tables

| Table | Columns |
|-------|---------|
| `feature_rows` | row_id (PK), machine_id, ts, features_json, anomaly_score, health_index, model_version, synced (bool) |
| `alerts` | id, ts, type (anomaly / sensor_silent), score, sms_sent, acknowledged |
| `pending_plans` | plan_id, plan_json, voice_path, state |
| `config` | machine_id, threshold, baseline stats (mean/std per feature), model_version |

Retention job deletes `feature_rows` older than 30 days that are `synced = true`.
