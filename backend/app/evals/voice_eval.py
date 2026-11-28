"""Voice eval (M2-39): owners' spoken replies → Gnani STT → intent, scored against the true answer.

Clips are named `<lang>_<label>_<speaker>[_anything].<ext>`: lang kn | hi | en; label yes | no | question |
unclear. Any common format (WhatsApp .ogg/.opus, .m4a, .mp3, .wav). They go through exactly what a real
reply does: ffmpeg → 16 kHz WAV → Gnani STT → keyword rules / LLM → intent.

    # real recordings (keep them out of git: ml/data/ is ignored)
    cd backend && .venv/Scripts/python -m app.evals.voice_eval ../ml/data/voice
    # synthetic first check: Gnani TTS voices speak the replies, plus copies with mill-like noise
    cd backend && .venv/Scripts/python -m app.evals.voice_eval ../ml/data/voice_synth --synth

Target (doc 01): ≥ 95 % on yes/no. The number that matters most is reported on its own: replies that were
not a plain "yes" but were taken as approval (false approvals).
"""
import argparse
import json
import re
import sys
import time
import wave
from collections import Counter, defaultdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import numpy as np

from app.voice.audio import AudioError, to_stt_wav
from app.voice.intent import classify
from app.voice.provider import VoiceError, default_provider

EXPECTED = {"yes": "approve", "no": "reject", "question": "question", "unclear": "unclear"}
NAME = re.compile(r"^(?P<lang>kn|hi|en)_(?P<label>yes|no|question|unclear)_(?P<speaker>[A-Za-z0-9-]+)", re.I)
AUDIO = {".ogg", ".opus", ".oga", ".m4a", ".mp3", ".wav", ".webm", ".aac", ".flac", ".amr", ".3gp"}

# ---------- synthetic clips ----------

VOICES = {"kn": ["Shruthi", "Sneha", "Prakash", "Shubham", "Sunaina"], "hi": ["Shivani", "Lakshmi", "Avinash", "Kalpana"]}
PHRASES = {
    "kn": {"yes": ["ಹೌದು", "ಹೌದು, ಮಾಡಿ", "ಸರಿ", "ಆಗಲಿ", "ಓಕೆ, ಮಾಡಿ"],
           "no": ["ಬೇಡ", "ಇಲ್ಲ, ಬೇಡ", "ಬೇಡ ಬಿಡಿ", "ಈಗ ಬೇಡ", "ಇಲ್ಲ"],
           "question": ["ಹೌದು, ಆದರೆ ಸೋಮವಾರ ಬನ್ನಿ", "ಮೆಕ್ಯಾನಿಕ್ ಮಧ್ಯಾಹ್ನ ಬರಲಿ"]},
    "hi": {"yes": ["हाँ", "हाँ जी, कर दो", "ठीक है", "हाँ, ठीक है", "हाँ जी"],
           "no": ["नहीं", "नहीं, मत करो", "रहने दो", "अभी नहीं", "नहीं जी"],
           "question": ["हाँ, पर सोमवार को भेजो", "मैकेनिक दोपहर में आए"]},
}


def mill_noise(n: int, rate: int, rng: np.random.Generator) -> np.ndarray:
    """Motor hum (50 Hz mains + harmonics, 48 Hz shaft) and broadband grinding noise."""
    t = np.arange(n) / rate
    hum = sum(a * np.sin(2 * np.pi * f * t + rng.random() * 6.3) for f, a in ((50, 1), (100, .6), (150, .3), (48, .5)))
    return hum + 1.5 * rng.standard_normal(n)


def add_noise(wav_bytes: bytes, snr_db: float, seed: int) -> bytes:
    with wave.open(BytesIO(wav_bytes)) as w:
        rate, x = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    noise = mill_noise(len(x), rate, np.random.default_rng(seed))
    p_sig = np.mean(x[np.abs(x) > 0.05 * np.max(np.abs(x))] ** 2) if np.any(x) else 1.0  # speech power
    noise *= np.sqrt(p_sig / (np.mean(noise ** 2) * 10 ** (snr_db / 10)))
    y = np.clip(x + noise, -32768, 32767).astype("<i2")
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(y.tobytes())
    return buf.getvalue()


def synthesize(folder: Path, *, snr_db: float = 10, log=print) -> int:
    """40 yes/no clips (20 per language, rotating voices and phrases), 4 'yes, but…' requests, and a noisy
    copy of every yes/no clip. Needs GNANI_API_KEY."""
    from app.config import get_settings
    from app.voice.gnani import GnaniVoice

    folder.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    made = 0
    for lang, voices in VOICES.items():
        jobs = [(label, i) for label in ("yes", "no") for i in range(10)] + [("question", i) for i in range(2)]
        for label, i in jobs:
            voice = voices[i % len(voices)]
            phrase = PHRASES[lang][label][i % len(PHRASES[lang][label])]
            base = folder / f"{lang}_{label}_{voice.lower()}{i:02d}"
            if base.with_suffix(".wav").exists():
                continue
            tts = GnaniVoice(s.model_copy(update={f"gnani_voice_{lang}": voice}))
            try:
                ogg = tts.tts(phrase, lang)
            except VoiceError as e:
                log(f"  skip {voice} «{phrase}»: {e}")
                continue
            wav = to_stt_wav(ogg)
            base.with_suffix(".wav").write_bytes(wav)
            (folder / f"{base.name}.txt").write_text(phrase, encoding="utf-8")
            if label in ("yes", "no"):
                (folder / f"{base.name}_noisy.wav").write_bytes(add_noise(wav, snr_db, seed=made))
            made += 1
            log(f"  {base.name}: «{phrase}» ({voice})")
    return made


# ---------- evaluation ----------

def clips(folder: Path) -> list[tuple[Path, str, str, str]]:
    out = []
    for p in sorted(folder.iterdir()):
        m = NAME.match(p.stem)
        if p.suffix.lower() in AUDIO and m:
            out.append((p, m["lang"].lower(), m["label"].lower(), m["speaker"]))
    return out


def evaluate(folder: Path, *, llm_providers=None, provider=None, log=print) -> dict:
    provider = provider or default_provider()
    if provider is None:
        raise SystemExit("GNANI_API_KEY is not set in backend/.env")
    rows = []
    for path, lang, label, speaker in clips(folder):
        t = time.monotonic()
        row = {"file": path.name, "lang": lang, "label": label, "speaker": speaker,
               "noisy": "noisy" in path.stem, "expected": EXPECTED[label]}
        try:
            wav = to_stt_wav(path.read_bytes())
            try:
                text = provider.stt(wav, lang, filename=path.name).text
            except VoiceError as e:  # a network blip is not a wrong answer: one retry, then it counts
                if "unreachable" not in str(e):
                    raise
                time.sleep(3)
                text = provider.stt(wav, lang, filename=path.name).text
            intent = classify(text, lang, llm_providers)
            row.update(transcript=text, intent=intent.intent, source=intent.source)
        except (AudioError, VoiceError) as e:
            row.update(transcript=None, intent="error", source=str(e)[:120])
        row["correct"] = row["intent"] == row["expected"]
        row["seconds"] = round(time.monotonic() - t, 2)
        rows.append(row)
        log(f"{'ok ' if row['correct'] else 'BAD'} {path.name}: «{row.get('transcript')}» → {row['intent']}"
            f" ({row.get('source')}), expected {row['expected']}")
    return report(rows)


def _acc(rows: list[dict]) -> dict:
    return {"n": len(rows), "correct": sum(r["correct"] for r in rows),
            "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3) if rows else None}


def report(rows: list[dict]) -> dict:
    yn = [r for r in rows if r["label"] in ("yes", "no")]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in yn:
        groups[f"{r['lang']}"].append(r)
        groups[f"{r['label']}"].append(r)
        groups["noisy" if r["noisy"] else "clean"].append(r)
    false_approvals = [r["file"] for r in rows if r["intent"] == "approve" and r["expected"] != "approve"]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "yes_no": _acc(yn),
        "target": 0.95,
        "false_approvals": false_approvals,
        "by_group": {k: _acc(v) for k, v in sorted(groups.items())},
        "requests": _acc([r for r in rows if r["label"] == "question"]),
        "unclear_clips": _acc([r for r in rows if r["label"] == "unclear"]),
        "confusion": {f"{e}->{i}": n for (e, i), n in sorted(Counter((r["expected"], r["intent"]) for r in rows).items())},
        "intent_source": dict(Counter(r.get("source") for r in rows if r["intent"] != "error")),
        "median_seconds": float(np.median([r["seconds"] for r in rows])) if rows else None,
        "clips": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--synth", action="store_true", help="generate the synthetic set into the folder first")
    ap.add_argument("--out", default="../ml/results")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if a.synth:
        print("generating clips with Gnani TTS…", flush=True)
        synthesize(folder, log=lambda s: print(s, flush=True))
    if not folder.is_dir() or not clips(folder):
        print(f"no clips named like kn_yes_s01.ogg in {folder}", file=sys.stderr)
        return 2
    rep = evaluate(folder, log=lambda s: print(s, flush=True))
    rep["set"] = "synthetic (Gnani TTS voices)" if a.synth or "synth" in folder.name else "recorded"
    name = "voice_eval_synth_report.json" if rep["set"].startswith("synthetic") else "voice_eval_report.json"
    out = Path(a.out) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    yn = rep["yes_no"]
    print(f"\nyes/no: {yn['correct']}/{yn['n']} = {yn['accuracy']:.1%} (target 95 %) · "
          f"false approvals: {len(rep['false_approvals'])} · requests {rep['requests']['correct']}/{rep['requests']['n']}"
          f" → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
