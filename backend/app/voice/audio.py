"""Turn whatever the phone or browser recorded (WebM/Opus, OGG, M4A, MP3, WAV...) into the 16 kHz
mono WAV that speech-to-text works best with, and refuse recordings that are too long."""
import shutil
import subprocess
import wave
from io import BytesIO

from app.config import get_settings


class AudioError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def wav_seconds(data: bytes) -> float:
    with wave.open(BytesIO(data)) as w:
        return w.getnframes() / float(w.getframerate())


def to_stt_wav(data: bytes) -> bytes:
    """Convert with ffmpeg. Raises AudioError(415) for unreadable audio, (413) when over the limit."""
    s = get_settings()
    if not data:
        raise AudioError(422, "Empty recording")
    exe = shutil.which(s.ffmpeg_path)
    if exe is None:
        # No ffmpeg: only a WAV can be passed on as it is (browsers record WebM, so install ffmpeg)
        try:
            secs = wav_seconds(data)
        except (wave.Error, EOFError) as e:
            raise AudioError(415, "Recording format needs ffmpeg on the server; send WAV") from e
        out = data
    else:
        try:
            p = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                                "-t", str(s.voice_max_reply_s + 1), "-ac", "1", "-ar", "16000",
                                "-sample_fmt", "s16", "-map_metadata", "-1", "-bitexact", "-f", "wav", "pipe:1"],
                               input=data, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as e:
            raise AudioError(415, "Could not convert the recording") from e
        if p.returncode != 0 or not p.stdout:
            raise AudioError(415, "Could not read the recording (unsupported or damaged audio)")
        out = _fix_wav_header(p.stdout)
        secs = wav_seconds(out)
    if secs > s.voice_max_reply_s:
        raise AudioError(413, f"Recording is longer than {s.voice_max_reply_s:.0f} s")
    if secs < 0.2:
        raise AudioError(422, "Recording is too short")
    return out


def _fix_wav_header(data: bytes) -> bytes:
    """ffmpeg writing WAV to a pipe can't seek back, so the size fields may be wrong: rewrite them."""
    i = data.find(b"data")
    if data[:4] != b"RIFF" or i < 0:
        return data
    pcm = data[i + 8:]
    return (data[:4] + (len(data) - 8).to_bytes(4, "little") + data[8:i + 4]
            + len(pcm).to_bytes(4, "little") + pcm)
