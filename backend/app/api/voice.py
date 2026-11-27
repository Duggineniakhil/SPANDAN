"""Voice note out and spoken reply in (M2-30). The phone never holds the Gnani key: it downloads
and uploads audio through these endpoints."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.approval.decision import DecisionError
from app.config import get_settings
from app.db import get_db
from app.events import plan_in_background
from app.models import Plan
from app.schemas import DecisionOut, PlanOut, SpokenOut, VoiceReplyOut
from app.voice.audio import AudioError
from app.voice.notes import ensure_note
from app.voice.phrases import PHRASES, phrase_audio, phrase_text
from app.voice.provider import VoiceError, VoiceProvider, default_provider
from app.voice.reply import handle_reply

router = APIRouter(tags=["voice"])
OGG = "audio/ogg"


def voice_provider() -> VoiceProvider | None:
    """Dependency, so tests can swap in a fake provider."""
    return default_provider()


def llm_providers() -> list | None:
    return None  # None = the configured LLMs (tests override)


@router.get("/plans/{plan_id}/voice-note", response_class=FileResponse,
            responses={200: {"content": {OGG: {}}}, 503: {"description": "No voice: show the text instead"}})
def voice_note(plan_id: uuid.UUID, db: Session = Depends(get_db),
               provider: VoiceProvider | None = Depends(voice_provider)) -> FileResponse:
    """The plan's voice script as an OGG/Opus voice note in the owner's language."""
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    path = ensure_note(db, plan, provider)
    if path is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voice note not available; show the text")
    return FileResponse(path, media_type=OGG, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/voice/phrases/{lang}/{name}", response_class=Response, responses={200: {"content": {OGG: {}}}})
def phrase(lang: str, name: str, provider: VoiceProvider | None = Depends(voice_provider)) -> Response:
    """Fixed phrases (ask again, approved, ...) from the cache."""
    if name not in PHRASES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown phrase")
    audio = phrase_audio(name, lang, provider)
    if audio is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Phrase audio not available")
    return Response(audio, media_type=OGG, headers={"Cache-Control": "public, max-age=86400"})


@router.post("/plans/{plan_id}/voice-reply", response_model=VoiceReplyOut)
async def voice_reply(plan_id: uuid.UUID, background: BackgroundTasks,
                      audio: UploadFile = File(description="The owner's recording, ≤ 30 s (WebM, OGG, M4A, MP3, WAV)"),
                      from_phone: str = Form(min_length=10, max_length=20),
                      db: Session = Depends(get_db),
                      provider: VoiceProvider | None = Depends(voice_provider),
                      llms: list | None = Depends(llm_providers)) -> VoiceReplyOut:
    """Owner's spoken yes/no. Approve/reject go through the same rules as a tap (registered number,
    pending, not expired); a request for a change re-plans; an unclear reply is asked again twice,
    then the owner is sent to the buttons."""
    settings = get_settings()
    data = await audio.read(settings.voice_max_reply_bytes + 1)
    if len(data) > settings.voice_max_reply_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Recording too large")
    try:
        # STT and the LLM are blocking network calls: keep them off the event loop
        r = await run_in_threadpool(handle_reply, db, plan_id, data, from_phone=from_phone,
                                    provider=provider, llm_providers=llms)
    except DecisionError as e:
        raise HTTPException(e.status, e.message)
    except AudioError as e:
        raise HTTPException(e.status, e.message)
    except VoiceError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Could not understand the recording right now; please tap Approve or Reject")
    if r.replan_event_id and settings.agent_auto_plan:
        background.add_task(plan_in_background, r.replan_event_id, r.question)
    decision = None
    if r.outcome:
        ex = r.outcome.execution
        decision = DecisionOut(plan=PlanOut.model_validate(r.outcome.plan), executed=ex.executed if ex else None,
                               reason=ex.reason if ex else None, job_id=ex.job_id if ex else None,
                               replanning=bool(ex and ex.replan))
    phrase_name = r.action  # each action has a cached phrase of the same name
    say = SpokenOut(lang=r.lang, text=phrase_text(phrase_name, r.lang),
                    audio_url=f"/api/v1/voice/phrases/{r.lang}/{phrase_name}")
    return VoiceReplyOut(transcript=r.transcript, intent=r.intent, intent_source=r.intent_source, action=r.action,
                         attempt=r.attempt, question=r.question, decision=decision, say=say)
