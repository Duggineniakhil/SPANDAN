import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db import engine
from app.models import Telemetry

URL = "/api/v1/telemetry/batch"


def make_row(minutes_ago: float = 1, **overrides) -> dict:
    ts = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    row = {
        "row_id": str(uuid.uuid4()),
        "ts": ts.isoformat(),
        "features": {"rms_y": 0.21, "kurtosis_y": 3.4, "amp_1x_y": 0.05},
        "anomaly_score": 0.12,
        "health_index": 95.0,
        "model_version": "ae-v1",
    }
    row.update(overrides)
    return row


def batch(machine: dict, rows: list[dict]) -> dict:
    return {"device_id": "phone-01", "machine_id": machine["id"], "rows": rows}


def stored_count() -> int:
    with engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(Telemetry))


def test_accepts_rows(client, machine):
    rows = [make_row(minutes_ago=i) for i in range(5)]
    r = client.post(URL, json=batch(machine, rows))
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 5, "duplicates": 0, "rejected": []}
    assert stored_count() == 5


def test_resending_same_batch_is_safe(client, machine):
    payload = batch(machine, [make_row(minutes_ago=i) for i in range(3)])
    client.post(URL, json=payload)
    r = client.post(URL, json=payload)
    assert r.json() == {"accepted": 0, "duplicates": 3, "rejected": []}
    assert stored_count() == 3


def test_duplicate_within_one_batch(client, machine):
    row = make_row()
    r = client.post(URL, json=batch(machine, [row, row, make_row()]))
    assert r.json() == {"accepted": 2, "duplicates": 1, "rejected": []}


def test_rejects_out_of_range_timestamps(client, machine):
    future = make_row(minutes_ago=-60)
    old = make_row(minutes_ago=61 * 24 * 60)
    ok = make_row()
    r = client.post(URL, json=batch(machine, [future, old, ok]))
    body = r.json()
    assert body["accepted"] == 1
    assert {(x["row_id"], x["reason"]) for x in body["rejected"]} == {
        (future["row_id"], "timestamp_in_future"),
        (old["row_id"], "timestamp_too_old"),
    }


def test_unknown_machine(client, machine):
    payload = batch(machine, [make_row()])
    payload["machine_id"] = str(uuid.uuid4())
    assert client.post(URL, json=payload).status_code == 404


def test_malformed_batch_rejected_whole(client, machine):
    naive_ts = make_row(ts=datetime.now().isoformat())             # no timezone
    bad_health = make_row(health_index=150)
    no_features = make_row(features={})
    for bad in (naive_ts, bad_health, no_features):
        r = client.post(URL, json=batch(machine, [make_row(), bad]))
        assert r.status_code == 422, bad
    assert client.post(URL, json=batch(machine, [])).status_code == 422
    assert stored_count() == 0


def test_nan_feature_rejected(client, machine):
    raw = ('{"device_id":"p","machine_id":"%s","rows":[{"row_id":"%s","ts":"%s","features":{"rms_y":NaN}}]}'
           % (machine["id"], uuid.uuid4(), datetime.now(UTC).isoformat()))
    r = client.post(URL, content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422
