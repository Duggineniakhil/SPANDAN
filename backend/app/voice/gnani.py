"""Gnani (vachana.ai) adapter: REST TTS and STT.

Checked live on 27 Nov 2026: Kannada and Hindi both ways. A ~300-character plan script becomes a
~25 s OGG/Opus note in about 5 s; digits and ₹ amounts are read out correctly, so scripts keep
numbers as digits. STT returns in about 1 s. The API allows one active request per account (429),
so calls are retried with a short backoff.
"""
import time

import httpx

from app.config import Settings
from app.voice.provider import LOCALES, Transcript, VoiceError

RETRY_STATUS = {429, 502, 503, 504}


def _error_text(r: httpx.Response) -> str:
    """Gnani returns three error shapes: {message}, {detail: {...}} and {error: {type, message}}."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            return f"{body['error'].get('type')}: {body['error'].get('message')}"
        if isinstance(body.get("detail"), dict):
            d = body["detail"]
            return f"{d.get('error_code')}: {d.get('message') or d.get('detail')}"
        return str(body.get("message") or body.get("detail") or body)[:200]
    return str(body)[:200]


class GnaniVoice:
    name = "gnani"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, retries: int = 2):
        self.s = settings
        self.client = client or httpx.Client(timeout=settings.voice_timeout_s)
        self.retries = retries
        self.voices = {"kn": settings.gnani_voice_kn, "hi": settings.gnani_voice_hi, "en": settings.gnani_voice_en}

    def _post(self, url: str, **kwargs) -> httpx.Response:
        headers = {"X-API-Key-ID": self.s.gnani_api_key, **kwargs.pop("headers", {})}
        deadline = time.monotonic() + self.s.voice_timeout_s
        for attempt in range(self.retries + 1):
            try:
                r = self.client.post(url, headers=headers, **kwargs)
            except httpx.HTTPError as e:  # timeout, connection reset, DNS...
                raise VoiceError(f"gnani unreachable: {type(e).__name__}") from e
            if r.status_code == 200:
                return r
            wait = 1.5 * (attempt + 1)
            if r.status_code in RETRY_STATUS and attempt < self.retries and time.monotonic() + wait < deadline:
                time.sleep(wait)
                continue
            raise VoiceError(f"gnani {r.status_code}: {_error_text(r)}")
        raise VoiceError("gnani: retries used up")  # pragma: no cover

    def tts(self, text: str, lang: str) -> bytes:
        r = self._post(self.s.gnani_tts_url, json={
            "text": text,
            "model": self.s.gnani_tts_model,
            "voice": self.voices.get(lang, self.s.gnani_voice_en),
            "language": LOCALES.get(lang, "en-IN"),
            "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                             "encoding": "oggopus", "container": "ogg"},
        })
        if not r.content or "audio" not in r.headers.get("content-type", "audio"):
            raise VoiceError("gnani tts returned no audio")
        return r.content

    def stt(self, audio: bytes, lang: str, filename: str = "reply.wav") -> Transcript:
        r = self._post(self.s.gnani_stt_url,
                       files={"audio_file": (filename, audio, "audio/wav")},
                       data={"language_code": LOCALES.get(lang, "en-IN"), "model": self.s.gnani_stt_model,
                             "format": "transcribe"})
        try:
            body = r.json()
        except ValueError as e:
            raise VoiceError("gnani stt returned non-JSON") from e
        if not body.get("success", True):
            raise VoiceError(f"gnani stt failed: {_error_text(r)}")
        # an empty transcript (silence) is not an error: it becomes an "unclear" reply
        return Transcript(text=(body.get("transcript") or "").strip(),
                          language=body.get("detected_language_code"), request_id=body.get("request_id"))
