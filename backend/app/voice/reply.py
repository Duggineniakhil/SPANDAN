"""The owner's spoken reply to a plan (M2-30, M2-31):
recording → 16 kHz WAV → STT → intent → approve / reject / re-plan with their request / ask again.

Checked before any audio leaves the server: the plan is pending and the reply came from the owner's
registered number. Only the transcript and a reference to the recording go into the audit log.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm import Provider
from app.approval.decision import DecisionError, DecisionOutcome, check_decidable, decide
from app.approval.state import release_slot, reopen_event, transition
from app.audit import audit
from app.config import get_settings
from app.models import AuditLog
from app.voice.audio import to_stt_wav
from app.voice.intent import classify
from app.voice.notes import voice_dir
from app.voice.provider import VoiceError, VoiceProvider


@dataclass
class ReplyResult:
    transcript: str
    intent: str
    intent_source: str
    action: str                 # approved | rejected | replanning | reask | use_buttons
    lang: str
    attempt: int                # 1 = first reply to this plan
    question: str | None = None
    outcome: DecisionOutcome | None = None
    replan_event_id: uuid.UUID | None = None


def _previous_unclear(db: Session, plan_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.entity == "plan", AuditLog.entity_id == plan_id, AuditLog.action == "voice_reply",
        AuditLog.details["intent"].astext == "unclear")) or 0


def handle_reply(db: Session, plan_id: uuid.UUID, audio: bytes, *, from_phone: str,
                 provider: VoiceProvider | None, llm_providers: list[Provider] | None = None) -> ReplyResult:
    """Raises DecisionError (404/403/409), AudioError (413/415/422) or VoiceError (STT failed)."""
    settings = get_settings()
    plan, owner = check_decidable(db, plan_id, decision="voice", channel="voice", from_phone=from_phone)
    lang = (plan.voice_script or {}).get("lang") or owner.language
    db.commit()  # don't hold the plan's row lock during the STT call
    if provider is None:
        raise VoiceError("voice replies are off (no GNANI_API_KEY)")

    wav = to_stt_wav(audio)
    ref = voice_dir("replies") / f"{uuid.uuid4()}.wav"
    ref.write_bytes(wav)
    try:
        transcript = provider.stt(wav, lang, filename=ref.name)
    except VoiceError as e:
        audit(db, actor="system", action="voice_stt_failed", entity="plan", entity_id=plan_id,
              details={"error": str(e)[:300], "audio_ref": ref.name})
        db.commit()
        raise

    intent = classify(transcript.text, lang, llm_providers)
    attempt = _previous_unclear(db, plan_id) + 1
    audit(db, actor="owner", action="voice_reply", entity="plan", entity_id=plan_id,
          details={"transcript": transcript.text, "intent": intent.intent, "source": intent.source,
                   "question": intent.question, "audio_ref": ref.name, "attempt": attempt,
                   "detected_language": transcript.language})
    db.commit()
    result = ReplyResult(transcript.text, intent.intent, intent.source, "", lang, attempt, intent.question)

    if intent.intent in ("approve", "reject"):
        result.outcome = decide(db, plan_id, decision=intent.intent, channel="voice", from_phone=from_phone,
                                transcript=transcript.text)
        ex = result.outcome.execution
        if intent.intent == "reject":
            result.action = "rejected"
        elif ex and not ex.executed:  # approved, but the slot was lost: a new plan follows
            result.action = "replanning"
            result.replan_event_id = plan.event_id if ex.replan else None
        else:
            result.action = "approved"
        return result

    if intent.intent == "question":
        # The owner wants a change: this plan is withdrawn and the agent plans again with their words.
        plan, _ = check_decidable(db, plan_id, decision="question", channel="voice", from_phone=from_phone)
        transition(db, plan, "cancelled", actor="owner",
                   details={"channel": "voice", "reason": "owner asked for a change",
                            "request": intent.question, "transcript": transcript.text})
        release_slot(db, plan)
        reopen_event(db, plan)
        db.commit()
        result.action, result.replan_event_id = "replanning", plan.event_id
        return result

    result.action = "reask" if attempt <= settings.voice_reask_max else "use_buttons"
    return result


__all__ = ["DecisionError", "ReplyResult", "handle_reply"]
