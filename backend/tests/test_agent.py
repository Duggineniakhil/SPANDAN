"""Agent tools, rules and the planner loop, driven by a scripted fake model (no real LLM calls)."""
import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.agent.llm import ProviderError, ToolCall, ToolResult, Turn
from app.agent.planner import run_planner
from app.agent.tools import AgentContext, execute
from app.db import SessionLocal
from app.models import AnomalyEvent, AuditLog, Diagnosis, Machine, MechanicSlot, Owner, Plan
from tests.test_events_sim import NORMAL, rows, setup_monitoring

KANNADA_SCRIPT = "ಮೋಟಾರ್ ಬೇರಿಂಗ್ ಸವೆದಿದೆ. 4 ರಿಂದ 8 ದಿನ ಉಳಿದಿದೆ. ಒಟ್ಟು ₹1,950. ಭಾನುವಾರ 10:00. ಹೌದು ಅಥವಾ ಇಲ್ಲ?"


# ---------- fixtures ----------

@pytest.fixture
def event_id(client, machine) -> uuid.UUID:
    client.post("/api/v1/sim/reset")
    setup_monitoring(client, machine)
    worn = {**NORMAL, "env_bpfo_y": 0.03, "kurtosis_y": 5.5}
    client.post("/api/v1/telemetry/batch", json={"device_id": "p", "machine_id": machine["id"],
                                                 "rows": rows(worn, 2, score=1.0, health=55, start_min=5)})
    r = client.post("/api/v1/events/anomaly", json={"machine_id": machine["id"], "started_at": datetime.now(UTC).isoformat(), "peak_score": 10})
    return uuid.UUID(r.json()["id"])


@pytest.fixture
def ctx(event_id):
    with SessionLocal() as db:
        event = db.get(AnomalyEvent, event_id)
        machine = db.get(Machine, event.machine_id)
        owner = db.get(Owner, machine.owner_id)
        diag = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event_id)).first()
        yield AgentContext(db=db, event=event, machine=machine, owner=owner, diagnosis=diag)


def call(ctx, name, **args):
    return execute(ctx, name, args)


# ---------- tools ----------

def test_context_has_diagnosis_and_owner(ctx):
    out, err = call(ctx, "get_machine_context")
    assert not err
    assert out["owner"]["language"] == "kn" and out["owner"]["spending_limit_inr"] == 2500
    assert out["diagnosis"]["likely_faults"][0]["fault"] == "bearing_outer"
    assert out["diagnosis"]["repair_deadline"]


def test_search_parts_ranks_in_stock_then_price(ctx):
    out, err = call(ctx, "search_parts", part_code="6205-2RS")
    assert not err
    opts = out["options"]
    assert opts[0]["in_stock"] and opts[0]["price_inr"] == 1180  # NBC at Kaveri Spares
    assert all(o["in_stock"] for o in opts[:-1]) and not opts[-1]["in_stock"]  # out-of-stock FAG last


def test_quote_reply_is_messy_and_price_stored(ctx):
    opts, _ = call(ctx, "search_parts", part_code="6205-2RS")
    dealer = next(o for o in opts["options"] if o["dealer"] == "Kaveri Spares")
    out, err = call(ctx, "request_quote", dealer_id=dealer["dealer_id"], part_code="6205-2RS", qty=1)
    assert not err and "rupaye" in out["dealer_reply"] and out["quote_id"]


def test_slots_are_free_before_deadline_and_ranked(ctx):
    out, err = call(ctx, "find_repair_slots", skill="bearing")
    assert not err and 1 <= len(out["slots"]) <= 3
    slot = ctx.db.get(MechanicSlot, uuid.UUID(out["slots"][0]["slot_id"]))
    assert slot.status == "free"


def test_zero_days_left_is_the_tightest_deadline_not_none(ctx):
    """Found by the replay tool: 0.0 days left was treated as 'no deadline' and a slot a day later was booked."""
    ctx.diagnosis.rul_days_low, ctx.diagnosis.rul_days_high, ctx.diagnosis.rul_status = 0.0, 0.02, "ok"
    out, err = call(ctx, "find_repair_slots", skill="bearing")
    assert err and "before the deadline" in out["error"]
    ctx.diagnosis.rul_days_low = None  # no estimate at all → no deadline from RUL
    assert not call(ctx, "find_repair_slots", skill="bearing")[1]


def test_bad_tool_args_are_errors_not_crashes(ctx):
    assert call(ctx, "search_parts")[1]  # missing arg
    assert call(ctx, "search_parts", part_code="X", hack=1)[1]  # extra arg
    assert call(ctx, "no_such_tool")[1]
    assert execute(ctx, "search_parts", None)[1]  # invalid JSON from the model


def _quote_and_slot(ctx, dealer_name="Kaveri Spares"):
    opts, _ = call(ctx, "search_parts", part_code="6205-2RS")
    d = next(o for o in opts["options"] if o["dealer"] == dealer_name)
    q, _ = call(ctx, "request_quote", dealer_id=d["dealer_id"], part_code="6205-2RS", qty=1)
    s, _ = call(ctx, "find_repair_slots", skill="bearing")
    return q["quote_id"], s["slots"][0]["slot_id"]


def test_submit_plan_builds_prices_server_side(ctx):
    qid, sid = _quote_and_slot(ctx)
    out, err = call(ctx, "submit_plan", quote_id=qid, slot_id=sid, fault_code="bearing_outer",
                    summary_en="Replace the worn bearing.", voice_script=KANNADA_SCRIPT)
    assert not err, out
    plan = ctx.db.get(Plan, uuid.UUID(out["plan_id"]))
    buy = plan.plan["actions"][0]
    assert buy["unit_price_inr"] == 1180 and plan.state == "pending"
    assert plan.total_cost_inr == 1180 + plan.plan["actions"][1]["rate_inr"]
    assert ctx.db.get(MechanicSlot, uuid.UUID(sid)).status == "held"
    assert ctx.event.status == "planned"


@pytest.mark.parametrize("case", ["over_limit", "english_script", "foreign_quote", "unknown_fault", "no_numbers"])
def test_submit_plan_rules(ctx, case):
    qid, sid = _quote_and_slot(ctx)
    args = dict(quote_id=qid, slot_id=sid, fault_code="bearing_outer", summary_en="x", voice_script=KANNADA_SCRIPT)
    if case == "over_limit":
        ctx.owner.spending_limit_inr = 1000
    elif case == "english_script":
        args["voice_script"] = "Bearing is worn, total 1950, Sunday 10:00. Yes or no?"
    elif case == "foreign_quote":
        args["quote_id"] = str(uuid.uuid4())
    elif case == "unknown_fault":
        args["fault_code"] = "gearbox"
    elif case == "no_numbers":
        args["voice_script"] = "ಬೇರಿಂಗ್ ಸವೆದಿದೆ"
    out, err = call(ctx, "submit_plan", **args)
    assert err and "rejected" in out["error"]
    assert ctx.plan_id is None and ctx.failed_submissions == 1


def test_injected_dealer_reply_cannot_raise_quantity(ctx):
    """The injection dealer asks for 10 pieces; the tool caps qty and the price is fixed server-side."""
    opts, _ = call(ctx, "search_parts", part_code="6205-2RS")
    d = next(o for o in opts["options"] if o["dealer"] == "Chamundi Engineering Traders")
    q, _ = call(ctx, "request_quote", dealer_id=d["dealer_id"], part_code="6205-2RS", qty=1)
    assert "AI ASSISTANT" in q["dealer_reply"]
    out, err = call(ctx, "request_quote", dealer_id=d["dealer_id"], part_code="6205-2RS", qty=10)
    assert err


def test_every_tool_call_is_audited(ctx):
    call(ctx, "get_machine_context")
    call(ctx, "search_parts", part_code="6205-2RS")
    actions = ctx.db.scalars(select(AuditLog.action).where(AuditLog.actor == "agent")).all()
    assert "tool:get_machine_context" in actions and "tool:search_parts" in actions


# ---------- planner loop with scripted fake models ----------

Script = Callable[[], Generator[Turn, list[ToolResult] | None, None]]


class FakeProvider:
    """A provider whose 'model' is a generator: it yields turns and receives tool results."""

    def __init__(self, name: str, script: Script):
        self.name = name
        self.script = script

    def start(self, system, tools, user):
        assert "submit_plan" in [t.name for t in tools] and "spending limit" in system
        gen = self.script()

        class _S:
            started = False

            def next(self, results, user_text=None):
                try:
                    if not self.started:
                        self.started = True
                        return next(gen)
                    return gen.send(results)
                except StopIteration:
                    return Turn(text="done")
        return _S()


def tc(name, **args):
    return ToolCall(id=f"c{uuid.uuid4().hex[:6]}", name=name, args=args)


def good_script():
    yield Turn(tool_calls=[tc("get_machine_context")])
    res = yield Turn(tool_calls=[tc("search_parts", part_code="6205-2RS")])
    best = res[0].content["options"][0]
    res = yield Turn(tool_calls=[tc("request_quote", dealer_id=best["dealer_id"], part_code="6205-2RS", qty=1),
                                 tc("find_repair_slots", skill="bearing")])  # parallel calls
    qid, sid = res[0].content["quote_id"], res[1].content["slots"][0]["slot_id"]
    yield Turn(tool_calls=[tc("check_mechanic_availability", slot_id=sid)])
    yield Turn(tool_calls=[tc("submit_plan", quote_id=qid, slot_id=sid, fault_code="bearing_outer",
                              summary_en="Replace bearing.", voice_script=KANNADA_SCRIPT)])


def test_planner_happy_path(event_id):
    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", good_script)])
    assert res.status == "planned" and res.tool_calls == 6, res
    with SessionLocal() as db:
        assert db.get(AnomalyEvent, event_id).status == "planned"
        plan = db.get(Plan, res.plan_id)
        assert plan.plan["voice_script"]["lang"] == "kn"


def test_planner_falls_back_to_second_provider(event_id):
    def broken():
        yield Turn(tool_calls=[tc("get_machine_context")])
        raise ProviderError("429 rate limited")

    class Broken(FakeProvider):
        def start(self, system, tools, user):
            s = super().start(system, tools, user)
            orig = s.next

            def nxt(results, user_text=None):
                t = orig(results, user_text)
                if results is not None:
                    raise ProviderError("429 rate limited")
                return t
            s.next = nxt
            return s

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[Broken("gemini", broken), FakeProvider("groq", good_script)])
        assert res.status == "planned" and res.provider == "groq"
        assert db.scalars(select(AuditLog).where(AuditLog.action == "agent_provider_failed")).first() is not None


def test_planner_stops_after_repeated_rule_failures(event_id):
    def stubborn():
        yield Turn(tool_calls=[tc("get_machine_context")])
        res = yield Turn(tool_calls=[tc("find_repair_slots", skill="bearing")])
        sid = res[0].content["slots"][0]["slot_id"]
        for _ in range(5):
            yield Turn(tool_calls=[tc("submit_plan", quote_id="none", slot_id=sid, fault_code="bearing_outer",
                                      summary_en="x", voice_script="English only, 100 rupees")])

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", stubborn)])
    assert res.status == "failed" and "too many times" in res.reason
    with SessionLocal() as db:
        assert db.get(AnomalyEvent, event_id).status == "diagnosed"  # still waiting; no plan
        assert db.scalars(select(Plan)).first() is None


def test_planner_caps_tool_calls(event_id):
    def looping():
        while True:
            yield Turn(tool_calls=[tc("get_machine_context")])

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", looping)])
    assert res.status == "failed" and "too many tool calls" in res.reason


def test_planner_nudges_once_then_gives_up(event_id):
    def chatty():
        yield Turn(text="I think the bearing is worn.")

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", chatty)])
    assert res.status == "failed" and "without submitting" in res.reason


def test_planner_without_keys_reports_clearly(event_id):
    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[])
    assert res.status == "failed" and "API key" in res.reason


def test_planner_skips_already_planned_event(event_id):
    with SessionLocal() as db:
        run_planner(db, event_id, providers=[FakeProvider("fake", good_script)])
    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("fake", good_script)])
    assert res.status == "skipped"


def test_planner_tries_next_provider_after_bad_output(event_id):
    def transliterates():
        yield Turn(tool_calls=[tc("get_machine_context")])
        res = yield Turn(tool_calls=[tc("find_repair_slots", skill="bearing")])
        sid = res[0].content["slots"][0]["slot_id"]
        for _ in range(3):
            res = yield Turn(tool_calls=[tc("submit_plan", quote_id="none", slot_id=sid, fault_code="bearing_outer",
                                            summary_en="x", voice_script="namaskara, bearing kettide, 400 rupees, 10:00")])
            assert "English letters" in res[0].content["error"]

    with SessionLocal() as db:
        res = run_planner(db, event_id, providers=[FakeProvider("gemini", transliterates), FakeProvider("groq", good_script)])
    assert res.status == "planned" and res.provider == "groq"


def test_mixed_script_with_part_codes_is_accepted(ctx):
    """Kannada text may still contain codes and names in English letters (6205-2RS, Kaveri Spares)."""
    qid, sid = _quote_and_slot(ctx)
    text = "ನಮಸ್ಕಾರ, ಮೋಟಾರ್ ಬೇರಿಂಗ್ ಸವೆದಿದೆ. Kaveri Spares ಇಂದ 6205-2RS ಬೇರಿಂಗ್ ₹1,180. ಒಟ್ಟು ₹1,580, ಸಮಯ 16:00. ಹೌದು ಅಥವಾ ಇಲ್ಲ?"
    out, err = call(ctx, "submit_plan", quote_id=qid, slot_id=sid, fault_code="bearing_outer", summary_en="x", voice_script=text)
    assert not err, out
