"""Approval engine: state machine, owner decision, executor, reminders/expiry, owner messages."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.agent.planner import run_planner
from app.approval.state import TransitionError, transition
from app.approval.sweep import sweep
from app.db import SessionLocal
from app.models import AnomalyEvent, AuditLog, Diagnosis, Job, MechanicSlot, Message, Plan
from tests.test_agent import FakeProvider, event_id, good_script  # noqa: F401  (event_id is a fixture)

OWNER_PHONE = "+919876543210"  # from conftest's owner fixture


@pytest.fixture
def plan_id(event_id) -> uuid.UUID:  # noqa: F811
    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", good_script)])
    assert res.status == "planned", res
    return res.plan_id


def decide(client, plan_id, decision="approve", phone=OWNER_PHONE, channel="tap"):
    return client.post(f"/api/v1/plans/{plan_id}/decision",
                       json={"decision": decision, "channel": channel, "from_phone": phone})


def slot_of(db, plan: Plan) -> MechanicSlot:
    sid = next(a["slot_id"] for a in plan.plan["actions"] if a["type"] == "book_mechanic")
    return db.get(MechanicSlot, uuid.UUID(sid))


def owner_messages(client, owner) -> list[dict]:
    r = client.get(f"/api/v1/owners/{owner['id']}/messages")
    assert r.status_code == 200
    return r.json()


def count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ---------- plan creation ----------

def test_new_plan_goes_draft_to_pending_and_owner_gets_script(client, owner, plan_id):
    with SessionLocal() as db:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "plan_pending")).one()
        assert entry.details["from"] == "draft" and entry.entity_id == plan_id
    msgs = owner_messages(client, owner)
    assert [m["kind"] for m in msgs] == ["plan_ready"]
    assert msgs[0]["lang"] == "kn" and "ಹೌದು" in msgs[0]["text"]
    r = client.get(f"/api/v1/owners/{owner['id']}/plans", params={"state": "pending"})
    assert [p["id"] for p in r.json()] == [str(plan_id)]
    assert client.get(f"/api/v1/owners/{owner['id']}/plans", params={"state": "bogus"}).status_code == 422


# ---------- approve → execute ----------

def test_approval_executes_every_action_in_sandbox(client, owner, plan_id):
    r = decide(client, plan_id, phone="09876543210")  # same number, local format
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True and body["plan"]["state"] == "executed" and body["job_id"]
    assert body["plan"]["decided_via"] == "tap"
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        slot = slot_of(db, plan)
        assert slot.status == "booked"
        job = db.get(Job, uuid.UUID(body["job_id"]))
        assert job.status == "scheduled" and job.slot_id == slot.id
        actions = db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
        steps = ["plan_approved", "mechanic_booked", "dealer_order_confirmed", "downtime_scheduled", "plan_executed"]
        assert [a for a in actions if a in steps] == steps
    kinds = {m["kind"]: m for m in owner_messages(client, owner)}
    confirmed = kinds["booking_confirmed"]
    assert confirmed["lang"] == "kn" and str(body["plan"]["total_cost_inr"]) in confirmed["text"]
    assert "ಪಾವತಿಸಿ" in confirmed["text"]  # pay at pickup; the system never pays
    dealer = client.get("/api/v1/sim/messages", params={"to_kind": "dealer"}).json()
    mech = client.get("/api/v1/sim/messages", params={"to_kind": "mechanic"}).json()
    assert len(dealer) == 1 and "pays ₹1180 at pickup" in dealer[0]["text"]
    assert len(mech) == 1 and mech[0]["kind"] == "booking"


def test_cannot_decide_twice(client, plan_id):
    assert decide(client, plan_id).status_code == 200
    r = decide(client, plan_id, decision="reject")
    assert r.status_code == 409 and "executed" in r.json()["detail"]


# ---------- M2-18: only the owner's number ----------

def test_wrong_number_is_refused_and_nothing_happens(client, owner, plan_id):
    r = decide(client, plan_id, phone="+919000000001")
    assert r.status_code == 403
    assert "9876543210" not in r.text  # registered number is never echoed
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan.state == "pending" and slot_of(db, plan).status == "held"
        assert count(db, Job) == 0
        refused = db.scalars(select(AuditLog).where(AuditLog.action == "decision_refused")).one()
        assert refused.details["from_phone_last4"] == "0001"


@pytest.mark.parametrize("phone", ["", "12345", "+91 98765 4321x"])
def test_malformed_numbers_never_match(client, plan_id, phone):
    r = decide(client, plan_id, phone=phone)
    assert r.status_code in (403, 422)
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).state == "pending"


# ---------- reject ----------

def test_reject_frees_slot_and_reopens_event(client, owner, event_id, plan_id):  # noqa: F811
    r = decide(client, plan_id, decision="reject", channel="voice")
    assert r.status_code == 200 and r.json()["plan"]["state"] == "rejected" and r.json()["executed"] is None
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        slot = slot_of(db, plan)
        assert slot.status == "free" and slot.held_for_event_id is None
        assert db.get(AnomalyEvent, event_id).status == "diagnosed"
        assert count(db, Job) == 0
    assert owner_messages(client, owner)[0]["kind"] == "rejected"


# ---------- executor: slot lost ----------

def test_lost_slot_cancels_and_asks_for_replan(client, owner, event_id, plan_id):  # noqa: F811
    with SessionLocal() as db:
        slot = slot_of(db, db.get(Plan, plan_id))
        slot.status, slot.held_for_event_id = "booked", None  # someone else took it
        db.commit()
    r = decide(client, plan_id)
    body = r.json()
    assert r.status_code == 200 and body["executed"] is False and body["replanning"] is True
    assert body["plan"]["state"] == "cancelled"
    with SessionLocal() as db:
        assert db.get(AnomalyEvent, event_id).status == "diagnosed"
        assert count(db, Job) == 0
        assert slot_of(db, db.get(Plan, plan_id)).status == "booked"  # the other booking is untouched
    assert owner_messages(client, owner)[0]["kind"] == "slot_lost"
    assert client.get("/api/v1/sim/messages", params={"to_kind": "dealer"}).json() == []


# ---------- M2-16: reminder, expiry, never auto-approve ----------

def test_reminder_once_then_expiry_never_approves(client, owner, event_id, plan_id):  # noqa: F811
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        created, expires = plan.created_at, plan.expires_at
        assert expires - created >= timedelta(hours=47)
        assert sweep(db, now=created + timedelta(hours=1)).reminded == 0
        assert sweep(db, now=created + timedelta(hours=25)).reminded == 1
        assert sweep(db, now=created + timedelta(hours=30)).reminded == 0  # only once
        r = sweep(db, now=expires + timedelta(minutes=1))
        assert r.expired == 1
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan.state == "expired" and plan.reminded_at is not None
        assert slot_of(db, plan).status == "free"
        assert db.get(AnomalyEvent, event_id).status == "diagnosed"
        assert count(db, Job) == 0
        assert count(db, AuditLog, AuditLog.action == "plan_approved") == 0
    kinds = [m["kind"] for m in owner_messages(client, owner)]
    assert kinds == ["expired", "reminder", "plan_ready"]
    reminder = owner_messages(client, owner)[1]
    assert "ಹೌದು" in reminder["text"] and str(plan.total_cost_inr) in reminder["text"]


def test_decision_after_expiry_is_refused(client, plan_id):
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        plan.expires_at = plan.created_at - timedelta(seconds=1)  # expired, sweep hasn't run yet
        db.commit()
    r = decide(client, plan_id)
    assert r.status_code == 409 and "expired" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).state == "expired"
        assert count(db, Job) == 0


def test_sweep_endpoint(client, plan_id):
    r = client.post("/api/v1/approval/sweep")
    assert r.status_code == 200 and r.json() == {"reminded": 0, "expired": 0}


# ---------- state machine ----------

@pytest.mark.parametrize("frm,to,ok", [
    ("draft", "pending", True), ("draft", "approved", False), ("pending", "executed", False),
    ("pending", "approved", True), ("approved", "executed", True), ("approved", "pending", False),
    ("rejected", "approved", False), ("expired", "approved", False), ("executed", "cancelled", False),
])
def test_transitions(plan_id, frm, to, ok):
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        plan.state = frm
        if ok:
            transition(db, plan, to, actor="system")
            assert plan.state == to
        else:
            with pytest.raises(TransitionError):
                transition(db, plan, to, actor="system")
        db.rollback()


# ---------- planner messages (M2-14) ----------

def test_could_not_plan_message_sent_once(client, owner, event_id):  # noqa: F811
    with SessionLocal() as db:
        assert run_planner(db, event_id, providers=[]).status == "failed"
        assert run_planner(db, event_id, providers=[]).status == "failed"
    msgs = owner_messages(client, owner)
    assert [m["kind"] for m in msgs] == ["could_not_plan"] and msgs[0]["lang"] == "kn"


def test_unclear_diagnosis_sends_inspection_message(client, owner, event_id):  # noqa: F811
    with SessionLocal() as db:
        diag = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event_id)).one()
        diag.faults = [{"fault": "unknown", "confidence": 0.3, "evidence": "no clear pattern"}]
        db.commit()
        assert run_planner(db, event_id, providers=[FakeProvider("fake", good_script)]).status == "skipped"
        assert count(db, Message, Message.kind == "inspection") == 1
    assert "ಪರಿಶೀಲಿಸಿ" in owner_messages(client, owner)[0]["text"]
