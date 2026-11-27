"""Provider-neutral speech interface (doc 06 §6). Switching speech provider = one new adapter file."""
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

# Our owner languages → BCP-47 codes the speech APIs use
LOCALES = {"kn": "kn-IN", "hi": "hi-IN", "en": "en-IN"}


class VoiceError(Exception):
    """Any speech-provider failure (network, timeout, quota, bad audio). Callers fall back to text."""


@dataclass
class Transcript:
    text: str
    language: str | None = None  # language the provider detected, if it says
    request_id: str | None = None


class VoiceProvider(Protocol):
    name: str

    def tts(self, text: str, lang: str) -> bytes:
        """Speak `text` (owner language kn/hi/en). Returns OGG/Opus audio."""
        ...

    def stt(self, audio: bytes, lang: str, filename: str = "reply.wav") -> Transcript:
        """Transcribe a short recording (≤ 30 s) in the owner's language."""
        ...


def default_provider() -> VoiceProvider | None:
    """The configured provider, or None when no key is set (voice off; text + tap buttons only)."""
    s = get_settings()
    if not s.gnani_api_key:
        return None
    from app.voice.gnani import GnaniVoice

    return GnaniVoice(s)
