"""Dashboard read endpoints (M2-04): telemetry series, health, latest diagnosis, audit trail."""
import uuid
from datetime import UTC, datetime, timedelta

from tests.test_approval import plan_id  # noqa: F401  (fixture)
from tests.test_agent import event_id  # noqa: F401  (fixture)
from tests.test_events_sim import NORMAL, rows, setup_monitoring


def post_rows(client, machine, rs):
    r = client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": machine["id"], "rows": rs})
    assert r.status_code == 200, r.text


def spread(n: int, minutes_back: int, score=0.5, health=90.0):
    """n rows evenly spread over the last `minutes_back` minutes, scores rising."""
    now = datetime.now(UTC)
    step = minutes_back / n
    return [{"row_id": str(uuid.uuid4()), "ts": (now - timedelta(minutes=minutes_back - i * step)).isoformat(),
             "features": {**NORMAL, "rms_y": 0.06 + i * 0.001}, "anomaly_score": score + i * 0.01,
             "health_index": health - i * 0.1, "rpm_estimate": 2880} for i in range(n)]


# ---------- telemetry series ----------

def test_raw_series_with_selected_features(client, machine):
    post_rows(client, machine, spread(30, 120))
    r = client.get(f"/api/v1/machines/{machine['id']}/telemetry", params={"features": "rms_y,kurtosis_y,missing"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["downsampled"] is False and body["total_rows"] == 30 and len(body["points"]) == 30
    p0 = body["points"][0]
    assert p0["features"]["rms_y"] == 0.06 and p0["features"]["kurtosis_y"] == 3.0
    assert p0["features"]["missing"] is None
    ts = [p["ts"] for p in body["points"]]
    assert ts == sorted(ts)


def test_long_range_is_bucketed(client, machine):
    post_rows(client, machine, spread(300, 600))
    r = client.get(f"/api/v1/machines/{machine['id']}/telemetry", params={"max_points": 50, "features": "rms_y"})
    body = r.json()
    assert body["downsampled"] is True and body["total_rows"] == 300
    assert 1 <= len(body["points"]) <= 50
    # buckets keep the worst case: highest score, lowest health
    assert max(p["anomaly_score"] for p in body["points"]) == max(x["anomaly_score"] for x in spread(300, 600))
    assert min(p["health_index"] for p in body["points"]) == 90.0 - 299 * 0.1
    assert body["points"][0]["rpm_estimate"] == 2880


def test_series_range_and_validation(client, machine):
    post_rows(client, machine, spread(10, 60))
    mid = machine["id"]
    now = datetime.now(UTC)
    r = client.get(f"/api/v1/machines/{mid}/telemetry",
                   params={"from": (now - timedelta(minutes=30)).isoformat(), "to": now.isoformat()})
    assert 4 <= r.json()["total_rows"] <= 6
    bad = [
        {"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()},  # from after to
        {"from": (now - timedelta(days=61)).isoformat()},                        # too long
        {"from": "2026-11-01T00:00:00"},                                          # no timezone
        {"features": "rms_y;drop table"},
        {"features": ",".join(f"f{i}" for i in range(11))},
        {"max_points": 5},
    ]
    for params in bad:
        assert client.get(f"/api/v1/machines/{mid}/telemetry", params=params).status_code == 422, params
    assert client.get(f"/api/v1/machines/{uuid.uuid4()}/telemetry").status_code == 404


# ---------- health ----------

def test_health_before_any_data(client, machine):
    r = client.get(f"/api/v1/machines/{machine['id']}/health")
    body = r.json()
    assert r.status_code == 200 and body["state"] == "setup"
    assert body["last_reading"] is None and body["readings_24h"] == 0 and body["open_event"] is None


def test_health_shows_latest_reading_and_open_event(client, machine):
    setup_monitoring(client, machine)
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    post_rows(client, machine, rows(worn, 3, score=3.1, health=42, start_min=3))
    body = client.get(f"/api/v1/machines/{machine['id']}/health").json()
    assert body["last_reading"]["anomaly_score"] == 3.1 and body["last_reading"]["health_index"] == 42
    assert body["minutes_since_last_reading"] < 2
    assert body["readings_24h"] == 13
    assert body["state"] == "alert" and body["open_event"]["status"] == "diagnosed"  # server rule fired
    assert body["pending_plan_id"] is None


# ---------- diagnosis ----------

def test_latest_diagnosis(client, machine):
    mid = machine["id"]
    assert client.get(f"/api/v1/machines/{mid}/diagnosis/latest").status_code == 404
    setup_monitoring(client, machine)
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    post_rows(client, machine, rows(worn, 3, score=3.1, health=42, start_min=3))
    r = client.get(f"/api/v1/machines/{mid}/diagnosis/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["faults"][0]["fault"] == "bearing_outer" and body["event_id"]


# ---------- audit ----------

def test_audit_filtered_by_machine_and_actor(client, owner, machine):
    other = client.post("/api/v1/machines", json={"owner_id": owner["id"], "name": "Second", "motor_rpm": 1440,
                                                  "sensor_id": "other-1"}).json()
    setup_monitoring(client, machine)
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    post_rows(client, machine, rows(worn, 3, score=3.1, health=42, start_min=3))

    entries = client.get("/api/v1/audit", params={"machine_id": machine["id"]}).json()
    actions = {e["action"] for e in entries}
    assert {"machine_registered", "baseline_started", "anomaly_event_opened", "event_diagnosed"} <= actions
    assert all(e["entity_id"] != other["id"] for e in entries)
    ids = [e["id"] for e in entries]
    assert ids == sorted(ids, reverse=True)  # newest first

    device = client.get("/api/v1/audit", params={"machine_id": machine["id"], "actor": "device"}).json()
    assert device and all(e["actor"] == "device" for e in device)
    assert client.get("/api/v1/audit", params={"actor": "hacker"}).status_code == 422
    assert len(client.get("/api/v1/audit", params={"limit": 2}).json()) == 2


def test_audit_for_machine_covers_the_whole_repair(client, machine, plan_id):  # noqa: F811
    r = client.post(f"/api/v1/plans/{plan_id}/decision",
                    json={"decision": "approve", "channel": "tap", "from_phone": "+919876543210"})
    assert r.json()["executed"] is True
    actions = {e["action"] for e in client.get("/api/v1/audit", params={"machine_id": machine["id"]}).json()}
    assert {"tool:submit_plan", "plan_pending", "plan_approved", "mechanic_booked", "dealer_order_confirmed",
            "downtime_scheduled", "plan_executed"} <= actions
    health = client.get(f"/api/v1/machines/{machine['id']}/health").json()
    assert health["open_event"]["status"] == "planned" and health["pending_plan_id"] is None


# ---------- judge dashboard (M2-35) ----------

def test_fleet_shows_alert_fault_and_waiting_plan(client, owner, plan_id):  # noqa: F811
    from tests.test_approval import decide

    fleet = client.get("/api/v1/fleet").json()
    assert len(fleet) == 1
    m = fleet[0]
    assert m["owner_name"] == "Ramesh" and m["owner_language"] == "kn" and m["state"] == "alert"
    assert m["open_event_status"] == "planned" and m["top_fault"] == "bearing_outer"
    assert m["pending_plan_id"] == str(plan_id) and m["health_index"] is not None
    decide(client, plan_id)
    assert client.get("/api/v1/fleet").json()[0]["pending_plan_id"] is None
    assert client.get("/api/v1/fleet?limit=0").status_code == 422


def test_stats_count_the_whole_story(client, plan_id):  # noqa: F811
    from tests.test_approval import decide
    from tests.test_feedback import card, mechanic_phone

    s = client.get("/api/v1/stats").json()
    assert (s["machines"], s["open_alerts"], s["alerts_total"], s["plans_pending"]) == (1, 1, 1, 1)
    assert s["repairs_booked"] == 0 and s["diagnosis_checked"] == 0 and s["alert_to_plan_median_s"] >= 0
    job_id = decide(client, plan_id).json()["job_id"]
    card(client, job_id, mechanic_phone(uuid.UUID(job_id)))
    s = client.get("/api/v1/stats").json()
    assert (s["plans_pending"], s["repairs_booked"], s["repairs_done"]) == (0, 1, 1)
    assert (s["diagnosis_checked"], s["diagnosis_correct"], s["tap_decisions"]) == (1, 1, 1)
    assert s["open_alerts"] == 0 and s["monitoring"] == 0  # repaired machine is learning a new baseline


def test_stats_on_an_empty_system(client):
    s = client.get("/api/v1/stats").json()
    assert s["machines"] == 0 and s["alert_to_plan_median_s"] is None
    assert client.get("/api/v1/fleet").json() == []
