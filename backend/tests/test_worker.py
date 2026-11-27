"""Analytics worker (M2-26): raw windows → rules + trained classifier → diagnosis; live RUL from telemetry."""
import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.analytics import artifacts
from app.db import SessionLocal
from app.models import AuditLog, RawWindow
from app.sim.vibration import generate_window
from tests.test_events_sim import NORMAL, setup_monitoring


def win(fault: str, severity: float = 0.6, seed: int = 0) -> list[float]:
    return generate_window(fault, severity, rpm=2880, seconds=2, seed=seed).y.round(5).tolist()


def upload(client, machine, kind, windows, **extra):
    return client.post(f"/api/v1/machines/{machine['id']}/windows", json={
        "kind": kind, "ts": datetime.now(UTC).isoformat(), "fs": 3200, "rpm": 2880, "windows": windows, **extra})


def report(client, machine) -> dict:
    r = client.post("/api/v1/events/anomaly", json={"machine_id": machine["id"],
                                                    "started_at": datetime.now(UTC).isoformat(), "peak_score": 9})
    assert r.status_code in (200, 201), r.text
    return client.get(f"/api/v1/events/{r.json()['id']}").json()


# ---------- raw window upload ----------

def test_window_upload_validates_and_keeps_only_recent(client, machine):
    assert upload(client, machine, "alert", [win("none")]).status_code == 201
    bad = [
        {"windows": [[0.0] * 100]},                    # too short
        {"windows": [[20.0] * 2048]},                  # beyond ±16 g
        {"windows": [win("none")] * 4},                # more than 3
        {"kind": "debug", "windows": [win("none")]},
        {"ts": "2026-11-27T10:00:00", "windows": [win("none")]},  # no timezone
    ]
    for b in bad:
        body = {"kind": "alert", "ts": datetime.now(UTC).isoformat(), "fs": 3200, "windows": [], **b}
        assert client.post(f"/api/v1/machines/{machine['id']}/windows", json=body).status_code == 422, b
    nan = '{"kind":"alert","ts":"2026-11-27T10:00:00+05:30","fs":3200,"windows":[[NaN' + ",0.0" * 1100 + "]]}"
    assert client.post(f"/api/v1/machines/{machine['id']}/windows", content=nan,
                       headers={"Content-Type": "application/json"}).status_code == 422
    for i in range(5):
        upload(client, machine, "alert", [win("none", seed=i)] * 3)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RawWindow)) == 12  # raw_windows_keep
    assert client.post(f"/api/v1/machines/{uuid.uuid4()}/windows",
                       json={"kind": "alert", "ts": datetime.now(UTC).isoformat(), "fs": 3200,
                             "windows": [win("none")]}).status_code == 404


# ---------- diagnosis from raw windows ----------

@pytest.mark.parametrize("fault", ["bearing_outer", "bearing_inner", "imbalance", "looseness"])
def test_alert_windows_drive_the_diagnosis(client, machine, fault):
    setup_monitoring(client, machine)
    upload(client, machine, "baseline", [win("none", seed=s) for s in (1, 2, 3)])
    upload(client, machine, "alert", [win(fault, seed=s) for s in (4, 5, 6)])
    d = report(client, machine)["diagnosis"]
    assert d["faults"][0]["fault"] == fault, d["faults"]
    assert d["faults"][0]["confidence"] >= 0.5
    assert d["model_versions"]["windows"] == "3"
    if fault.startswith("bearing_"):
        assert ("BPFO" if fault == "bearing_outer" else "BPFI") in d["faults"][0]["evidence"]


def test_trained_classifier_is_used_when_present(client, machine):
    if artifacts.diagnosis_model() is None:
        pytest.skip("trained model not in ml/results")
    setup_monitoring(client, machine)
    upload(client, machine, "alert", [win("bearing_outer", seed=s) for s in (1, 2)])
    d = report(client, machine)["diagnosis"]
    assert "diagnosis-hgb-v1" in d["model_versions"]["diagnosis"]


def test_no_known_pattern_gives_unknown(client, machine):
    setup_monitoring(client, machine)
    upload(client, machine, "alert", [win("none", seed=s) for s in (7, 8, 9)])
    d = report(client, machine)["diagnosis"]
    assert d["faults"][0]["fault"] == "unknown" and "closest" in d["faults"][0]["evidence"]
    assert d["rul_status"] == "insufficient_data" and d["rul_days_low"] is None


def test_stale_windows_are_ignored(client, machine):
    setup_monitoring(client, machine)
    upload(client, machine, "alert", [win("bearing_outer")])
    with SessionLocal() as db:
        for w in db.scalars(select(RawWindow)):
            w.created_at = datetime.now(UTC) - timedelta(hours=3)
        db.commit()
    d = report(client, machine)["diagnosis"]
    assert d["model_versions"]["windows"] == "0"  # fell back to the feature-ratio rules


def test_rules_alone_when_model_missing(client, machine, monkeypatch):
    monkeypatch.setattr(artifacts, "diagnosis_model", lambda: None)
    import app.analytics.worker as worker
    monkeypatch.setattr(worker, "diagnosis_model", lambda: None)
    setup_monitoring(client, machine)
    upload(client, machine, "alert", [win("bearing_outer", seed=3)])
    d = report(client, machine)["diagnosis"]
    assert d["faults"][0]["fault"] == "bearing_outer" and d["model_versions"]["diagnosis"] == "rules-v1"


# ---------- live RUL ----------

def _rows(n: int, start_min: int, rms, score=1.0):
    now = datetime.now(UTC)
    return [{"row_id": str(uuid.uuid4()), "ts": (now - timedelta(minutes=start_min - i)).isoformat(),
             "features": {**NORMAL, "rms_y": rms(i)}, "anomaly_score": score, "health_index": 70.0}
            for i in range(n)]


def test_rul_follows_the_wear_trend(client, machine):
    setup_monitoring(client, machine)  # baseline rms_y = 0.06
    growth = 0.04  # per reading after onset at reading 20
    rms = lambda i: 0.06 * (1.0 if i < 20 else math.exp(growth * (i - 20)))  # noqa: E731
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": machine["id"],
                                                 "rows": _rows(40, 200, rms)})
    upload(client, machine, "alert", [win("bearing_outer", seed=s) for s in (1, 2)])
    d = report(client, machine)["diagnosis"]
    assert d["faults"][0]["fault"] == "bearing_outer"
    first = (d["rul_status"], d["rul_days_low"])

    # more readings arrive while the alert is open → days-left is recomputed
    more = _rows(40, 160, lambda i: rms(i + 40))
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": machine["id"], "rows": more})
    ev = client.get(f"/api/v1/machines/{machine['id']}/health").json()["open_event"]
    d2 = client.get(f"/api/v1/events/{ev['id']}").json()["diagnosis"]
    assert d2["rul_status"] == "ok", d2
    assert 0 <= d2["rul_days_low"] <= d2["rul_days_high"] < 1.0  # minutes-to-hours scale for this test data
    assert (d2["rul_status"], d2["rul_days_low"]) != first
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "rul_updated")) >= 1


def test_agent_gets_a_deadline_even_without_a_trend(client, machine):
    setup_monitoring(client, machine)
    upload(client, machine, "alert", [win("bearing_outer")])
    d = report(client, machine)["diagnosis"]
    assert d["rul_status"] == "default_window" and d["rul_days_low"] == 3.0
