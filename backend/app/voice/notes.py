"""The plan's voice note: the agent's voice_script spoken by TTS, stored once per distinct text.

Generated right after the agent's plan is accepted (so it is ready when the owner opens it) and
again on demand if that failed. On failure the owner still has the text and the tap buttons.
"""
import hashlib
import logging
import threading
import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.models import Plan
from app.voice.provider import VoiceError, VoiceProvider, default_provider

log = logging.getLogger(__name__)
# one TTS call per note: the pre-generation and the owner opening the plan can race
# (and Gnani allows one active request per account)
_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def voice_dir(*parts: str) -> Path:
    """Folder under VOICE_DIR (relative paths are relative to backend/, wherever the server starts)."""
    base = Path(get_settings().voice_dir)
    d = (base if base.is_absolute() else _BACKEND_DIR / base).joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _note_file(lang: str, text: str) -> Path:
    s = get_settings()
    voice = {"kn": s.gnani_voice_kn, "hi": s.gnani_voice_hi}.get(lang, s.gnani_voice_en)
    key = hashlib.sha256(f"{s.gnani_tts_model}|{voice}|{lang}|{text}".encode()).hexdigest()[:24]
    return voice_dir("notes") / f"{key}.ogg"


def ensure_note(db: Session, plan: Plan, provider: VoiceProvider | None = None) -> Path | None:
    """Path of the plan's note, generating it if needed. None when voice is off or TTS failed
    (audited). Commits only when it changed something."""
    script = plan.voice_script or {}
    text, lang = (script.get("text") or "").strip(), script.get("lang", "en")
    if not text:
        return None
    path = _note_file(lang, text)
    with _locks[path.name]:
        if not path.exists():
            provider = provider or default_provider()
            if provider is None:
                return None
            try:
                audio = provider.tts(text, lang)
            except VoiceError as e:
                log.warning("voice note for plan %s failed: %s", plan.id, e)
                audit(db, actor="system", action="voice_note_failed", entity="plan", entity_id=plan.id,
                      details={"error": str(e)[:300], "provider": provider.name})
                db.commit()
                return None
            tmp = path.with_suffix(".part")
            tmp.write_bytes(audio)
            tmp.replace(path)  # never serve a half-written file
    if plan.voice_audio_path != str(path):
        plan.voice_audio_path = str(path)
        audit(db, actor="system", action="voice_note_ready", entity="plan", entity_id=plan.id,
              details={"lang": lang, "bytes": path.stat().st_size})
        db.commit()
    return path


def prepare_note_in_background(plan_id: uuid.UUID) -> None:
    """Pre-generate the note right after planning (own DB session; never raises)."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            plan = db.get(Plan, plan_id)
            if plan is not None:
                ensure_note(db, plan)
        except Exception:
            log.exception("voice note crashed for plan %s", plan_id)
