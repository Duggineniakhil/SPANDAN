"""Coordinator agent loop (doc 06 §7). The LLM proposes; fixed rules and the owner dispose."""
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import Provider, ProviderError, ToolDef, ToolResult, default_providers
from app.agent.prompts import SYSTEM_PROMPT, user_message
from app.agent.tools import TOOLS, AgentContext, execute
from app.approval.messages import notify_owner, send
from app.audit import audit
from app.config import get_settings
from app.models import AnomalyEvent, Diagnosis, Machine, Owner, Plan

log = logging.getLogger(__name__)
MAX_FAILED_SUBMISSIONS = 3
TOOL_DEFS = [ToolDef(t.name, t.description, t.schema) for t in TOOLS]


@dataclass
class PlannerResult:
    status: str  # planned | failed | skipped
    plan_id: uuid.UUID | None = None
    provider: str | None = None
    reason: str | None = None
    tool_calls: int = 0


class _Stop(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _run_once(ctx: AgentContext, provider: Provider, max_calls: int, deadline: float,
              owner_request: str | None = None) -> int:
    """One attempt with one provider. Returns the number of tool calls; raises _Stop or ProviderError."""
    session = provider.start(SYSTEM_PROMPT, TOOL_DEFS, user_message(str(ctx.event.id), owner_request))
    results: list[ToolResult] | None = None
    calls = 0
    nudged = False
    while True:
        if time.monotonic() > deadline:
            raise _Stop("timed out")
        turn = session.next(results)
        if turn.refused:
            raise _Stop(f"model declined: {turn.text}")
        if not turn.tool_calls:
            if ctx.plan_id:
                return calls
            if nudged:
                raise _Stop("model stopped without submitting a plan")
            # one reminder, then give up
            nudged = True
            results = None
            turn = session.next(None, user_text="You have not submitted a plan yet. Use the tools and finish with submit_plan.")
            if turn.refused:
                raise _Stop(f"model declined: {turn.text}")
            if not turn.tool_calls:
                raise _Stop("model stopped without submitting a plan")
        results = []
        for call in turn.tool_calls:
            calls += 1
            if calls > max_calls:
                raise _Stop(f"too many tool calls (limit {max_calls})")
            content, is_error = execute(ctx, call.name, call.args)
            results.append(ToolResult(call, content, is_error))
            if ctx.failed_submissions >= MAX_FAILED_SUBMISSIONS:
                raise _Stop("plan rejected by the rules too many times")
        if ctx.plan_id:  # plan accepted by the rules; no need for another model turn
            return calls


def run_planner(db: Session, event_id: uuid.UUID, providers: list[Provider] | None = None,
                owner_request: str | None = None) -> PlannerResult:
    settings = get_settings()
    event = db.get(AnomalyEvent, event_id)
    if event is None:
        return PlannerResult("failed", reason="event not found")
    if event.status != "diagnosed":
        return PlannerResult("skipped", reason=f"event is '{event.status}', not waiting for a plan")
    machine = db.get(Machine, event.machine_id)
    owner = db.get(Owner, machine.owner_id)
    diagnosis = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event.id).order_by(Diagnosis.created_at.desc())).first()
    if diagnosis is None or not diagnosis.faults or diagnosis.faults[0]["fault"] == "unknown":
        audit(db, actor="system", action="agent_skipped", entity="anomaly_event", entity_id=event.id,
              details={"reason": "no clear diagnosis; owner should get the machine inspected"})
        notify_owner(db, owner, "inspection", event_id=event.id, once=True, machine=machine.name)
        db.commit()
        return PlannerResult("skipped", reason="no clear diagnosis; recommend an inspection")

    providers = default_providers() if providers is None else providers
    if not providers:
        audit(db, actor="system", action="agent_unavailable", entity="anomaly_event", entity_id=event.id,
              details={"reason": "no LLM API key configured"})
        notify_owner(db, owner, "could_not_plan", event_id=event.id, once=True, machine=machine.name)
        db.commit()
        return PlannerResult("failed", reason="no LLM API key configured (GEMINI_API_KEY / GROQ_API_KEY)")

    deadline = time.monotonic() + settings.agent_timeout_s
    total_calls = 0
    last_reason = "no provider succeeded"
    for provider in providers:
        ctx = AgentContext(db=db, event=event, machine=machine, owner=owner, diagnosis=diagnosis)
        audit(db, actor="agent", action="agent_started", entity="anomaly_event", entity_id=event.id,
              details={"provider": provider.name, **({"owner_request": owner_request} if owner_request else {})})
        try:
            calls = _run_once(ctx, provider, settings.agent_max_tool_calls, deadline, owner_request)
            total_calls += calls
            audit(db, actor="agent", action="plan_submitted", entity="plan", entity_id=ctx.plan_id,
                  details={"provider": provider.name, "tool_calls": calls})
            # the plan goes to the owner as the agent's own explanation (in their language)
            script = ctx.db.get(Plan, ctx.plan_id).voice_script
            send(db, to_kind="owner", to_id=owner.id, kind="plan_ready", lang=script["lang"], text=script["text"],
                 plan_id=ctx.plan_id, event_id=event.id)
            db.commit()
            return PlannerResult("planned", plan_id=ctx.plan_id, provider=provider.name, tool_calls=total_calls)
        except ProviderError as e:
            # Keep quotes and audit entries; try the next provider from scratch.
            last_reason = str(e)
            log.warning("provider %s failed: %s", provider.name, e)
            audit(db, actor="system", action="agent_provider_failed", entity="anomaly_event", entity_id=event.id,
                  details={"provider": provider.name, "error": last_reason[:500]})
            db.commit()
        except _Stop as stop:
            # The model did not produce an acceptable plan (bad output, too many calls, gave up):
            # also a reason to try the next provider, while time remains.
            last_reason = f"{provider.name}: {stop.reason}"
            audit(db, actor="system", action="agent_provider_failed", entity="anomaly_event", entity_id=event.id,
                  details={"provider": provider.name, "reason": stop.reason})
            db.commit()
            if stop.reason == "timed out":
                break

    audit(db, actor="system", action="agent_failed", entity="anomaly_event", entity_id=event.id,
          details={"reason": last_reason[:500]})
    notify_owner(db, owner, "could_not_plan", event_id=event.id, once=True, machine=machine.name)
    db.commit()
    return PlannerResult("failed", reason=last_reason)
