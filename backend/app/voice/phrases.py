"""Fixed spoken phrases (doc 06 §6 "cache + fallback"), pre-generated into app/voice/cache/ so they play
instantly and still work when Gnani is down.

Regenerate after changing the wording (needs GNANI_API_KEY):  python -m app.voice.phrases
Kannada and Hindi wording still needs a native speaker's check.
"""
import sys
from pathlib import Path

from app.voice.provider import VoiceError, VoiceProvider, default_provider

CACHE = Path(__file__).parent / "cache"

PHRASES: dict[str, dict[str, str]] = {
    # reply not understood: ask again
    "reask": {
        "kn": "ಕ್ಷಮಿಸಿ, ಸರಿಯಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಹೌದು ಅಥವಾ ಬೇಡ ಎಂದು ಹೇಳಿ.",
        "hi": "माफ़ कीजिए, ठीक से सुनाई नहीं दिया। कृपया हाँ या नहीं बोलिए।",
        "en": "Sorry, I did not catch that. Please say yes or no.",
    },
    # still unclear after the re-asks: tap instead
    "use_buttons": {
        "kn": "ಕ್ಷಮಿಸಿ, ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಪರದೆಯ ಮೇಲಿನ ಒಪ್ಪಿಗೆ ಅಥವಾ ಬೇಡ ಗುಂಡಿಯನ್ನು ಒತ್ತಿ.",
        "hi": "माफ़ कीजिए, समझ नहीं आया। कृपया स्क्रीन पर मंज़ूर या मना बटन दबाइए।",
        "en": "Sorry, I could not understand. Please tap Approve or Reject on the screen.",
    },
    "approved": {
        "kn": "ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಒಪ್ಪಿಗೆ ಸಿಕ್ಕಿದೆ. ಮೆಕ್ಯಾನಿಕ್ ಬುಕ್ ಆಗಿದೆ.",
        "hi": "धन्यवाद। आपकी मंज़ूरी मिल गई। मैकेनिक बुक हो गया है।",
        "en": "Thank you. Your approval is received and the mechanic is booked.",
    },
    "rejected": {
        "kn": "ಸರಿ, ಈ ಯೋಜನೆಯನ್ನು ರದ್ದು ಮಾಡಿದ್ದೇವೆ. ಏನನ್ನೂ ಖರೀದಿಸಿಲ್ಲ.",
        "hi": "ठीक है, यह योजना रद्द कर दी गई है। कुछ भी नहीं खरीदा गया।",
        "en": "Okay, this plan is cancelled. Nothing was bought.",
    },
    # owner asked for a change, or the slot was lost on approval
    "replanning": {
        "kn": "ಸರಿ, ಹೊಸ ಯೋಜನೆ ಮಾಡುತ್ತಿದ್ದೇವೆ. ಸ್ವಲ್ಪ ಹೊತ್ತಿನಲ್ಲಿ ಕಳುಹಿಸುತ್ತೇವೆ.",
        "hi": "ठीक है, हम नई योजना बना रहे हैं। थोड़ी देर में भेजेंगे।",
        "en": "Okay, we are making a new plan and will send it shortly.",
    },
}


def phrase_text(name: str, lang: str) -> str:
    texts = PHRASES[name]
    return texts.get(lang, texts["en"])


def phrase_path(name: str, lang: str) -> Path:
    lang = lang if lang in PHRASES[name] else "en"
    return CACHE / f"{name}_{lang}.ogg"


def phrase_audio(name: str, lang: str, provider: VoiceProvider | None = None) -> bytes | None:
    """Cached audio, generated (and cached) on first use if a provider is available. None = text only."""
    path = phrase_path(name, lang)
    if path.exists():
        return path.read_bytes()
    provider = provider or default_provider()
    if provider is None:
        return None
    try:
        audio = provider.tts(phrase_text(name, lang), lang)
    except VoiceError:
        return None
    CACHE.mkdir(exist_ok=True)
    path.write_bytes(audio)
    return audio


def generate_all(force: bool = False) -> None:
    provider = default_provider()
    if provider is None:
        sys.exit("GNANI_API_KEY is not set in backend/.env")
    for name, texts in PHRASES.items():
        for lang in texts:
            path = phrase_path(name, lang)
            if path.exists() and not force:
                continue
            CACHE.mkdir(exist_ok=True)
            path.write_bytes(provider.tts(texts[lang], lang))
            print("wrote", path.name, path.stat().st_size, "bytes")


if __name__ == "__main__":
    generate_all(force="--force" in sys.argv)
