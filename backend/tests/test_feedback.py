"""Repair feedback: job card (M2-32) and false alarm (M2-33)."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AnomalyEvent, AuditLog, FeedbackLabel, Job, Machine, Mechanic, Plan
from tests.test_agent import event_id  # noqa: F401  (fixture)
from tests.test_approval import OWNER_PHONE, decide, plan_id, slot_of  # noqa: F401  (plan_id is a fixture)
from tests.test_events_sim import NORMAL, rows, setup_monitoring


@pytest.fixture
def job_id(client, plan_id) -> uuid.UUID:  # noqa: F811
    r = decide(client, plan_id)
    assert r.json()["executed"], r.text
    return uuid.UUID(r.json()["job_id"])


def mechanic_phone(job_id) -> str:
    with SessionLocal() as db:
        return db.get(Mechanic, db.get(Job, job_id).mechanic_id).phone


def card(client, job_id, phone, fault="bearing_outer", **extra):
    return client.post(f"/api/v1/jobs/{job_id}/job-card", json={
        "actual_fault": fault, "parts_replaced": ["6205-2RS"], "notes": "outer race pitted", "from_phone": phone, **extra})


def false_alarm(client, event_id, phone=OWNER_PHONE, note=""):  # noqa: F811
    return client.post(f"/api/v1/alerts/{event_id}/false-alarm", json={"from_phone": phone, "note": note})


def labels(machine_id=None):
    with SessionLocal() as db:
        return [(lb.label, lb.source) for lb in db.scalars(select(FeedbackLabel).order_by(FeedbackLabel.created_at))]


# ---------- job card ----------

def test_event_detail_lists_the_booked_job(client, event_id, job_id):  # noqa: F811
    jobs = client.get(f"/api/v1/events/{event_id}").json()["jobs"]
    assert [j["id"] for j in jobs] == [str(job_id)]
    assert jobs[0]["status"] == "scheduled" and jobs[0]["mechanic"] and jobs[0]["job_card"] is None


def test_job_card_resolves_labels_and_starts_new_baseline(client, owner, machine, event_id, job_id):  # noqa: F811
    r = card(client, job_id, mechanic_phone(job_id))
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["event_status"], b["machine_state"], b["diagnosis_correct"]) == ("resolved", "baseline", True)
    jc = b["job"]["job_card"]
    assert jc["submitted_by"] == "mechanic" and jc["predicted_fault"] == "bearing_outer"
    assert b["job"]["status"] == "done"
    assert labels() == [("bearing_outer", "job_card")]
    m = client.get(f"/api/v1/machines/{machine['id']}").json()
    assert m["state"] == "baseline" and m["baseline_done_at"] is None
    health = client.get(f"/api/v1/machines/{machine['id']}/health").json()
    assert health["open_event"] is None
    msgs = client.get(f"/api/v1/owners/{owner['id']}/messages").json()
    assert msgs[0]["kind"] == "job_done" and "ಬೇರಿಂಗ್" in msgs[0]["text"]
    # once only
    assert card(client, job_id, mechanic_phone(job_id)).status_code == 409


def test_owner_can_submit_and_a_wrong_diagnosis_is_recorded(client, job_id):
    b = card(client, job_id, "09876543210", fault="looseness").json()  # owner's number, local format
    assert b["job"]["job_card"]["submitted_by"] == "owner" and b["diagnosis_correct"] is False
    assert card(client, uuid.uuid4(), OWNER_PHONE).status_code == 404


def test_second_job_card_is_refused_and_adds_no_label(client, job_id):
    """Idempotency: a double submit (retry on a bad network) must not add a second training label."""
    phone = mechanic_phone(job_id)
    assert card(client, job_id, phone).status_code == 200
    n = len(labels())
    r = card(client, job_id, phone, fault="imbalance")
    assert r.status_code == 409 and len(labels()) == n


def test_job_card_from_another_number_is_refused(client, job_id):
    r = card(client, job_id, "+919000000001")
    assert r.status_code == 403
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "scheduled"
        refused = db.scalars(select(AuditLog).where(AuditLog.action == "job_card_refused")).one()
        assert refused.details["from_phone_last4"] == "0001"


@pytest.mark.parametrize("bad", [
    {"actual_fault": "gremlins"}, {"parts_replaced": ["x"] * 11}, {"notes": "n" * 1001}, {"extra": 1},
])
def test_job_card_validation(client, job_id, bad):
    assert card(client, job_id, OWNER_PHONE, **bad).status_code == 422


def test_after_repair_only_the_new_baseline_counts(client, machine, event_id, job_id):  # noqa: F811
    card(client, job_id, mechanic_phone(job_id))
    mid = machine["id"]
    # new baseline: much quieter readings than before the repair
    quiet = {**NORMAL, "rms_y": 0.03}
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(quiet, 10, start_min=20)})
    assert client.post(f"/api/v1/machines/{mid}/baseline/complete",
                       json={"anomaly_threshold": 2.0, "model_version": "t2"}).status_code == 200
    from app.analytics.diagnosis_v0 import feature_rows
    with SessionLocal() as db:
        base, recent = feature_rows(db, db.get(Machine, uuid.UUID(mid)))
    assert {r["rms_y"] for r in base} == {0.03}  # pre-repair baseline readings are not mixed in
    assert recent == []                          # nor the pre-repair alert readings


# ---------- false alarm ----------

def test_false_alarm_withdraws_plan_and_raises_threshold(client, owner, machine, event_id, plan_id):  # noqa: F811
    r = false_alarm(client, event_id, note="grain was wet, motor sounded fine")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["event"]["status"] == "false_alarm" and b["machine_state"] == "monitoring"
    assert b["cancelled_plan_id"] == str(plan_id)
    assert b["threshold_base"] == 2.5 and b["threshold_raise_pct"] == 5.0
    assert b["anomaly_threshold"] == pytest.approx(2.625)
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan.state == "cancelled" and slot_of(db, plan).status == "free"
    assert labels() == [("false_alarm", "owner")]
    msgs = client.get(f"/api/v1/owners/{owner['id']}/messages").json()
    assert msgs[0]["kind"] == "false_alarm"
    assert false_alarm(client, event_id).status_code == 409  # already closed


def test_threshold_raise_is_capped_at_30_percent(client, machine):
    mid = machine["id"]
    setup_monitoring(client, machine)  # threshold 2.5
    pcts = []
    for _ in range(8):
        ev = client.post("/api/v1/events/anomaly", json={"machine_id": mid, "started_at": datetime.now(UTC).isoformat(),
                                                         "peak_score": 9}).json()
        pcts.append(false_alarm(client, ev["id"]).json()["threshold_raise_pct"])
    assert pcts == [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 30.0, 30.0]
    assert client.get(f"/api/v1/machines/{mid}").json()["anomaly_threshold"] == pytest.approx(3.25)
    # a new baseline starts again from its own threshold
    client.post(f"/api/v1/machines/{mid}/baseline/start")
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": mid, "rows": rows(NORMAL, 5, start_min=10)})
    client.post(f"/api/v1/machines/{mid}/baseline/complete", json={"anomaly_threshold": 3.0, "model_version": "t2"})
    ev = client.post("/api/v1/events/anomaly", json={"machine_id": mid, "started_at": datetime.now(UTC).isoformat(),
                                                     "peak_score": 9}).json()
    b = false_alarm(client, ev["id"]).json()
    assert (b["threshold_raise_pct"], b["anomaly_threshold"]) == (5.0, pytest.approx(3.15))


def test_false_alarm_refusals(client, event_id, job_id):  # noqa: F811
    assert false_alarm(client, event_id, phone="+919000000001").status_code == 403
    r = false_alarm(client, event_id)  # a mechanic is already booked
    assert r.status_code == 409 and "job card" in r.json()["detail"]
    assert false_alarm(client, uuid.uuid4()).status_code == 404
    with SessionLocal() as db:
        assert db.get(AnomalyEvent, event_id).status == "planned"
        assert db.scalars(select(FeedbackLabel)).all() == []


def test_false_alarm_while_the_agent_is_planning_wins(client, event_id):  # noqa: F811
    """Found live: the owner tapped False alarm while the agent was still working, and the agent's plan
    then reopened the event. submit_plan now re-checks the event under a row lock."""
    from app.agent.planner import run_planner
    from tests.test_agent import FakeProvider, good_script

    def owner_cancels_midway():
        gen = good_script()
        results = None
        while True:
            turn = gen.send(results) if results is not None else next(gen)
            if any(c.name == "submit_plan" for c in turn.tool_calls):
                assert false_alarm(client, event_id).status_code == 200  # another request, its own transaction
            results = yield turn

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", owner_cancels_midway)])
    assert res.status == "skipped" and "false_alarm" in res.reason
    with SessionLocal() as db:
        assert db.get(AnomalyEvent, event_id).status == "false_alarm"
        assert db.scalars(select(Plan).where(Plan.event_id == event_id)).all() == []
        from app.models import MechanicSlot
        assert db.scalars(select(MechanicSlot).where(MechanicSlot.held_for_event_id == event_id)).all() == []
        assert db.scalars(select(AuditLog).where(AuditLog.action == "agent_stopped")).one()
