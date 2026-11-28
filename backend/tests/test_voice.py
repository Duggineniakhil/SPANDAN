"""Voice (M2-27 – M2-31): Gnani adapter, audio conversion, intent, voice note, spoken reply, re-plan.
Never calls Gnani or an LLM: fake providers and httpx.MockTransport stand in."""
import json
import math
import shutil
import struct
import subprocess
import uuid
import wave
from io import BytesIO

import httpx
import pytest
from sqlalchemy import select

from app.agent.llm import ToolCall, Turn
from app.agent.prompts import user_message
from app.api import voice as voice_api
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AnomalyEvent, AuditLog, Plan
from app.voice.audio import AudioError, to_stt_wav, wav_seconds
from app.voice.gnani import GnaniVoice
from app.voice.intent import classify, keyword_intent
from app.voice.phrases import PHRASES, phrase_path
from app.voice.provider import Transcript, VoiceError
from tests.test_agent import event_id  # noqa: F401  (fixture)
from tests.test_approval import OWNER_PHONE, plan_id, slot_of  # noqa: F401  (plan_id is a fixture)

OGG = b"OggS\x00fake-opus-audio"


def tone_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


class FakeVoice:
    name = "fake"

    def __init__(self, replies=(), fail_tts=False, fail_stt=False):
        self.replies = list(replies)
        self.fail_tts, self.fail_stt = fail_tts, fail_stt
        self.tts_calls: list[tuple[str, str]] = []
        self.stt_calls: list[tuple[int, str]] = []

    def tts(self, text, lang):
        self.tts_calls.append((text, lang))
        if self.fail_tts:
            raise VoiceError("gnani 500: text too long")
        return OGG

    def stt(self, audio, lang, filename="reply.wav"):
        self.stt_calls.append((len(audio), lang))
        if self.fail_stt:
            raise VoiceError("gnani 504: UPSTREAM_TIMEOUT")
        return Transcript(self.replies.pop(0), language=f"{lang}-IN")


class IntentLLM:
    """Fake LLM that answers classify_reply."""

    def __init__(self, intent, question=""):
        self.name = "fake-llm"
        self.args = {"intent": intent, "question": question}
        self.seen: list[str] = []

    def start(self, system, tools, user):
        assert [t.name for t in tools] == ["classify_reply"] and "data, not instructions" in system
        self.seen.append(user)
        args = self.args

        class _S:
            def next(self, results, user_text=None):
                return Turn(tool_calls=[ToolCall(id="c1", name="classify_reply", args=args)])
        return _S()


@pytest.fixture
def voice(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_dir", str(tmp_path))  # no notes cached by an earlier test
    fake = FakeVoice()
    app.dependency_overrides[voice_api.voice_provider] = lambda: fake
    app.dependency_overrides[voice_api.llm_providers] = lambda: []
    yield fake
    app.dependency_overrides.clear()


def reply(client, plan_id, audio=None, phone=OWNER_PHONE):  # noqa: F811
    return client.post(f"/api/v1/plans/{plan_id}/voice-reply", data={"from_phone": phone},
                       files={"audio": ("reply.wav", audio or tone_wav(), "audio/wav")})


def audits(action):
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


# ---------- intent ----------

@pytest.mark.parametrize("text,expected", [
    ("ಹೌದು", "approve"), ("houdu", "approve"), ("ಸರಿ, ಮಾಡಿ", "approve"), ("हाँ जी", "approve"),
    ("ठीक है।", "approve"), ("Okay.", "approve"), ("haan", "approve"),
    ("ಬೇಡ", "reject"), ("ಇಲ್ಲ.", "reject"), ("नहीं", "reject"), ("nahi", "reject"), ("No.", "reject"),
    ("ಸರಿ ಇಲ್ಲ", None),                         # both sides → the LLM decides
    ("theek nahi hai", None),
    ("haan but can it be on Monday please", None),  # long reply → the LLM decides
    ("ಹೌದು, ಆದರೆ ಸೋಮವಾರ ಬನ್ನಿ.", None),       # short but conditional: was a false approval in the voice eval
    ("हाँ, पर सोमवार को", None), ("yes but monday", None),
    ("ಓಕೆ, ಮಾಡಿ", "approve"), ("हाँ जी, कर दो", "approve"), ("ಈಗ ಬೇಡ", "reject"), ("ಬ್ಯಾಡ.", "reject"), ("अभी नहीं", "reject"),
    ("   ", "unclear"),
])
def test_keyword_rules(text, expected):
    assert keyword_intent(text) == expected


def test_llm_only_when_keywords_cant_tell():
    llm = IntentLLM("question", "Monday morning instead")
    assert classify("ಹೌದು", "kn", [llm]).source == "keywords" and not llm.seen
    q = classify("ಹೌದು ಆದರೆ ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ ಬರಲಿ", "kn", [llm])
    assert (q.intent, q.source, q.question) == ("question", "llm", "Monday morning instead")
    assert "ಸೋಮವಾರ" in llm.seen[0]
    # no LLM available, or a "question" with no request in it → unclear, never a guessed approve
    assert classify("ಹೌದು ಆದರೆ ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ ಬರಲಿ", "kn", []).intent == "unclear"
    assert classify("ಏನು ಹೇಳ್ತಾ ಇದ್ದೀರಾ ಗೊತ್ತಾಗ್ತಿಲ್ಲ ಸ್ವಾಮಿ", "kn", [IntentLLM("question", "")]).intent == "unclear"
    assert classify("", "kn", [llm]).source == "empty"


# ---------- Gnani adapter (mocked HTTP) ----------

def _gnani(handler):
    s = get_settings().model_copy(update={"gnani_api_key": "k-test", "voice_timeout_s": 10})
    return GnaniVoice(s, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_gnani_tts_request_and_retry_on_busy(monkeypatch):
    monkeypatch.setattr("app.voice.gnani.time.sleep", lambda s: None)
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if len(seen) == 1:  # one active request per account
            return httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "busy"}})
        return httpx.Response(200, content=OGG, headers={"content-type": "audio/ogg"})

    assert _gnani(handler).tts("ನಮಸ್ಕಾರ ₹1,630", "kn") == OGG
    body = json.loads(seen[-1].content)
    assert seen[-1].headers["X-API-Key-ID"] == "k-test"
    assert (body["language"], body["voice"], body["model"]) == ("kn-IN", "Shruthi", "timbre-v3.0")
    assert body["audio_config"]["container"] == "ogg" and body["text"] == "ನಮಸ್ಕಾರ ₹1,630"


@pytest.mark.parametrize("status,body,expect", [
    (401, {"detail": {"error_code": "INVALID_API_KEY", "message": "bad key"}}, "INVALID_API_KEY"),
    (500, {"success": False, "message": "text too long", "status_code": 500}, "text too long"),
    (400, {"success": False, "error": {"type": "INVALID_VOICE", "message": "no such voice"}}, "INVALID_VOICE"),
])
def test_gnani_errors_become_voice_errors(status, body, expect):
    with pytest.raises(VoiceError, match=expect):
        _gnani(lambda req: httpx.Response(status, json=body)).tts("x", "hi")


def test_gnani_stt_parses_transcript():
    def handler(req: httpx.Request):
        assert b'name="language_code"' in req.content and b"hi-IN" in req.content and b"prisma-v3.0" in req.content
        return httpx.Response(200, json={"success": True, "request_id": "r1", "transcript": " हाँ जी ",
                                         "detected_language_code": "hi-IN"})
    t = _gnani(handler).stt(tone_wav(), "hi")
    assert (t.text, t.language, t.request_id) == ("हाँ जी", "hi-IN", "r1")
    with pytest.raises(VoiceError, match="unreachable"):
        _gnani(lambda req: (_ for _ in ()).throw(httpx.ConnectTimeout("slow"))).stt(tone_wav(), "hi")


# ---------- audio conversion ----------

def test_audio_conversion_and_limits():
    assert abs(wav_seconds(to_stt_wav(tone_wav(1.0, rate=44100))) - 1.0) < 0.05
    with pytest.raises(AudioError) as e:
        to_stt_wav(tone_wav(31))
    assert e.value.status == 413
    with pytest.raises(AudioError) as e:
        to_stt_wav(b"definitely not audio")
    assert e.value.status == 415


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_browser_webm_recording_is_converted():
    webm = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-c:a", "libopus",
                           "-f", "webm", "pipe:1"], input=tone_wav(2.0, rate=48000), capture_output=True).stdout
    out = to_stt_wav(webm)
    with wave.open(BytesIO(out)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)
    assert abs(wav_seconds(out) - 2.0) < 0.1


# ---------- voice note ----------

def test_voice_note_generated_once_and_cached(client, plan_id, voice):  # noqa: F811
    r = client.get(f"/api/v1/plans/{plan_id}/voice-note")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/ogg" and r.content == OGG
    assert client.get(f"/api/v1/plans/{plan_id}/voice-note").content == OGG
    assert len(voice.tts_calls) == 1 and voice.tts_calls[0][1] == "kn" and "ಹೌದು" in voice.tts_calls[0][0]
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).voice_audio_path.endswith(".ogg")
    assert len(audits("voice_note_ready")) == 1
    assert client.get(f"/api/v1/plans/{uuid.uuid4()}/voice-note").status_code == 404


def test_voice_note_falls_back_to_text(client, plan_id, voice):  # noqa: F811
    voice.fail_tts = True
    r = client.get(f"/api/v1/plans/{plan_id}/voice-note")
    assert r.status_code == 503 and "text" in r.json()["detail"]
    assert "text too long" in audits("voice_note_failed")[0].details["error"]
    app.dependency_overrides[voice_api.voice_provider] = lambda: None  # no key configured
    assert client.get(f"/api/v1/plans/{plan_id}/voice-note").status_code == 503


def test_fixed_phrases_are_cached_for_every_language(client):
    for name, texts in PHRASES.items():
        for lang in texts:
            assert phrase_path(name, lang).exists(), f"run: python -m app.voice.phrases ({name}_{lang})"
    r = client.get("/api/v1/voice/phrases/kn/reask")
    assert r.status_code == 200 and r.content[:4] == b"OggS"
    assert client.get("/api/v1/voice/phrases/ta/reask").status_code == 200  # unknown language → English
    assert client.get("/api/v1/voice/phrases/kn/../../etc").status_code == 404
    assert client.get("/api/v1/voice/phrases/kn/whatever").status_code == 404


# ---------- spoken reply ----------

def test_spoken_yes_approves_and_books(client, plan_id, voice):  # noqa: F811
    voice.replies = ["ಹೌದು, ಮಾಡಿ"]
    r = reply(client, plan_id)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["intent"], b["intent_source"], b["action"]) == ("approve", "keywords", "approved")
    assert b["decision"]["executed"] is True and b["decision"]["plan"]["decided_via"] == "voice"
    assert b["say"]["lang"] == "kn" and b["say"]["audio_url"] == "/api/v1/voice/phrases/kn/approved"
    assert voice.stt_calls[0][1] == "kn"
    approved = audits("plan_approved")[0]
    assert approved.details == {"from": "pending", "to": "approved", "channel": "voice", "transcript": "ಹೌದು, ಮಾಡಿ"}
    heard = audits("voice_reply")[0].details
    assert heard["transcript"] == "ಹೌದು, ಮಾಡಿ" and heard["audio_ref"].endswith(".wav")
    assert heard["intent"] == "approve" and heard["attempt"] == 1


def test_spoken_no_rejects(client, event_id, plan_id, voice):  # noqa: F811
    voice.replies = ["ಬೇಡ"]
    b = reply(client, plan_id).json()
    assert b["action"] == "rejected" and b["decision"]["plan"]["state"] == "rejected"
    with SessionLocal() as db:
        assert slot_of(db, db.get(Plan, plan_id)).status == "free"


def test_reply_from_another_number_never_reaches_gnani(client, plan_id, voice):  # noqa: F811
    voice.replies = ["ಹೌದು"]
    assert reply(client, plan_id, phone="+919000000001").status_code == 403
    assert voice.stt_calls == []
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).state == "pending"


def test_unclear_is_asked_again_twice_then_buttons(client, plan_id, voice):  # noqa: F811
    voice.replies = ["", "ಏನು?", "hmm"]
    actions = [reply(client, plan_id).json() for _ in range(3)]
    assert [a["action"] for a in actions] == ["reask", "reask", "use_buttons"]
    assert [a["attempt"] for a in actions] == [1, 2, 3]
    assert actions[0]["say"]["text"].startswith("ಕ್ಷಮಿಸಿ")
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).state == "pending"  # nothing happens without a clear yes


def test_question_cancels_and_replans_with_the_owners_words(client, event_id, plan_id, voice, monkeypatch):  # noqa: F811
    voice.replies = ["ಹೌದು ಆದರೆ ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ ಬರಲಿ"]
    app.dependency_overrides[voice_api.llm_providers] = lambda: [IntentLLM("question", "Come on Monday morning")]
    monkeypatch.setattr(get_settings(), "agent_auto_plan", True)
    started = []
    monkeypatch.setattr(voice_api, "plan_in_background", lambda ev, req: started.append((ev, req)))
    b = reply(client, plan_id).json()
    assert (b["intent"], b["action"], b["question"]) == ("question", "replanning", "Come on Monday morning")
    assert started == [(event_id, "Come on Monday morning")]
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan.state == "cancelled" and slot_of(db, plan).status == "free"
        assert db.get(AnomalyEvent, event_id).status == "diagnosed"
    assert audits("plan_cancelled")[0].details["request"] == "Come on Monday morning"
    assert "Monday morning" in user_message(str(event_id), "Come on Monday morning")


def test_reply_failures_send_the_owner_to_buttons(client, plan_id, voice):  # noqa: F811
    assert reply(client, plan_id, audio=b"garbage").status_code == 415
    voice.fail_stt = True
    r = reply(client, plan_id)
    assert r.status_code == 503 and "tap" in r.json()["detail"]
    assert audits("voice_stt_failed")
    app.dependency_overrides[voice_api.voice_provider] = lambda: None
    assert reply(client, plan_id).status_code == 503
    assert reply(client, uuid.uuid4()).status_code == 404
    with SessionLocal() as db:
        assert db.get(Plan, plan_id).state == "pending"
