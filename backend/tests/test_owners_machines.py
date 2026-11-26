import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import engine
from app.main import app
from app.models import AuditLog


def test_health_needs_no_token():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_api_requires_token(headers):
    r = TestClient(app).get(f"/api/v1/owners/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 401


def test_create_and_get_owner(client, owner):
    r = client.get(f"/api/v1/owners/{owner['id']}")
    assert r.status_code == 200
    assert r.json()["language"] == "kn"
    assert r.json()["idle_windows"] == [{"dow": 6, "start": "09:00", "end": "14:00"}]


def test_duplicate_owner_phone_conflicts(client, owner):
    r = client.post("/api/v1/owners", json={"name": "Other", "phone": owner["phone"], "language": "hi"})
    assert r.status_code == 409


@pytest.mark.parametrize("patch", [
    {"language": "ta"},
    {"phone": "12345"},
    {"spending_limit_inr": -1},
    {"idle_windows": [{"dow": 7, "start": "09:00", "end": "10:00"}]},
    {"idle_windows": [{"dow": 1, "start": "14:00", "end": "09:00"}]},
    {"unexpected": "field"},
])
def test_owner_validation(client, patch):
    body = {"name": "X", "phone": "+919000000000", "language": "kn", **patch}
    assert client.post("/api/v1/owners", json=body).status_code == 422


def test_machine_needs_existing_owner(client):
    r = client.post("/api/v1/machines", json={"owner_id": str(uuid.uuid4()), "name": "M"})
    assert r.status_code == 404


def test_sensor_cannot_pair_twice(client, owner, machine):
    r = client.post("/api/v1/machines", json={"owner_id": owner["id"], "name": "M2",
                                              "sensor_id": machine["sensor_id"]})
    assert r.status_code == 409


def test_list_machines_for_owner(client, owner, machine):
    r = client.get("/api/v1/machines", params={"owner_id": owner["id"]})
    assert [m["id"] for m in r.json()] == [machine["id"]]


def test_baseline_flow(client, machine):
    mid = machine["id"]
    assert machine["state"] == "setup"

    # cannot complete before starting
    r = client.post(f"/api/v1/machines/{mid}/baseline/complete",
                    json={"anomaly_threshold": 0.8, "model_version": "ae-v1"})
    assert r.status_code == 409

    r = client.post(f"/api/v1/machines/{mid}/baseline/start")
    assert r.status_code == 200 and r.json()["state"] == "baseline"

    # cannot start twice
    assert client.post(f"/api/v1/machines/{mid}/baseline/start").status_code == 409

    r = client.post(f"/api/v1/machines/{mid}/baseline/complete",
                    json={"anomaly_threshold": 0.8, "model_version": "ae-v1"})
    body = r.json()
    assert r.status_code == 200
    assert body["state"] == "monitoring"
    assert body["anomaly_threshold"] == 0.8
    assert body["baseline_done_at"] is not None

    # re-baseline after repair is allowed from monitoring
    assert client.post(f"/api/v1/machines/{mid}/baseline/start").status_code == 200


def test_actions_are_audited(client, machine):
    client.post(f"/api/v1/machines/{machine['id']}/baseline/start")
    with engine.connect() as conn:
        actions = [a.action for a in conn.execute(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["owner_created", "machine_registered", "baseline_started"]


@pytest.mark.parametrize("sql", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"])
def test_audit_log_is_append_only(owner, sql):
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text(sql))
