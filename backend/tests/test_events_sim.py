import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.analytics.diagnosis_v0 import rank_faults
from app.db import engine
from app.models import AnomalyEvent, Mechanic, MechanicSlot

NORMAL = {"env_bpfo_y": 0.004, "kurtosis_y": 3.0, "amp_1x_y": 0.05, "amp_3x_y": 0.004, "band_0_25_y": 0.003, "rms_y": 0.06}


def rows(features: dict, n: int, score: float | None = None, health: float | None = None, start_min: int = 30):
    now = datetime.now(UTC)
    out = []
    for i in range(n):
        r = {"row_id": str(uuid.uuid4()), "ts": (now - timedelta(minutes=start_min - i)).isoformat(), "features": features}
        if score is not None:
            r["anomaly_score"] = score
            r["health_index"] = health
        out.append(r)
    return out


def setup_monitoring(client, machine, threshold=2.5):
    mid = machine["id"]
    client.post(f"/api/v1/machines/{mid}/baseline/start")
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(NORMAL, 10, start_min=40)})
    client.post(f"/api/v1/machines/{mid}/baseline/complete", json={"anomaly_threshold": threshold, "model_version": "t"})


# ---------- diagnosis v0 ----------

def test_rank_faults_picks_bearing():
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    faults = rank_faults([NORMAL] * 5, [worn] * 5)
    assert faults[0]["fault"] == "bearing_outer"
    assert "BPFO" in faults[0]["evidence"]


def test_rank_faults_picks_imbalance():
    faults = rank_faults([NORMAL] * 5, [{**NORMAL, "amp_1x_y": 0.3}] * 5)
    assert faults[0]["fault"] == "imbalance"


def test_rank_faults_unknown_when_nothing_changes():
    assert rank_faults([NORMAL] * 5, [NORMAL] * 5)[0]["fault"] == "unknown"


# ---------- events ----------

def test_phone_event_opens_once_and_is_diagnosed(client, machine):
    setup_monitoring(client, machine)
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": machine["id"],
                                                 "rows": rows(worn, 2, score=1.0, health=60, start_min=5)})
    body = {"machine_id": machine["id"], "started_at": datetime.now(UTC).isoformat(), "peak_score": 12.0}
    r1 = client.post("/api/v1/events/anomaly", json=body)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/v1/events/anomaly", json={**body, "peak_score": 30.0})
    assert r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]

    detail = client.get(f"/api/v1/events/{r1.json()['id']}").json()
    assert detail["status"] == "diagnosed"
    assert detail["peak_score"] == 30.0
    assert detail["diagnosis"]["faults"][0]["fault"] == "bearing_outer"
    assert detail["diagnosis"]["rul_status"] == "placeholder"
    assert client.get(f"/api/v1/machines/{machine['id']}").json()["state"] == "alert"


def test_server_rule_opens_event_after_three_high_scores(client, machine):
    setup_monitoring(client, machine, threshold=2.5)
    mid = machine["id"]
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(NORMAL, 2, score=3.0, health=40, start_min=6)})
    assert client.get("/api/v1/events", params={"machine_id": mid}).json() == []
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(NORMAL, 1, score=5.0, health=20, start_min=2)})
    events = client.get("/api/v1/events", params={"machine_id": mid}).json()
    assert len(events) == 1 and events[0]["source"] == "server"


def test_no_server_event_while_learning(client, machine):
    mid = machine["id"]
    client.post(f"/api/v1/machines/{mid}/baseline/start")
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(NORMAL, 3, score=9.0, health=0)})
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(AnomalyEvent)) == 0


def test_event_for_unknown_machine(client):
    r = client.post("/api/v1/events/anomaly", json={"machine_id": str(uuid.uuid4()), "started_at": datetime.now(UTC).isoformat()})
    assert r.status_code == 404


# ---------- sandbox ----------

def test_sim_reset_seeds_future_slots(client):
    counts = client.post("/api/v1/sim/reset").json()
    assert counts["dealers"] == 6 and counts["mechanics"] == 4 and counts["slots"] > 50
    again = client.post("/api/v1/sim/reset").json()
    assert again == counts  # idempotent: replaces, doesn't duplicate
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(Mechanic)) == 4
        assert c.scalar(select(func.min(MechanicSlot.start_at))) > datetime.now(UTC)
