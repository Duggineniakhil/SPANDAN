/**
 * Voice loop on the plan card (M1-24 / M1-25 in the phone app): play the plan's voice note, record the
 * owner's spoken reply, and play back what the system understood. Gnani runs on the server; the
 * browser only plays and records audio. Tap buttons stay available whenever voice fails.
 */
import { Loader2, Mic, Square, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type VoiceReply } from "../lib/api";

const MAX_SECONDS = 10; // a yes/no needs a few seconds; the server accepts up to 30

const HEARD: Record<VoiceReply["action"], string> = {
  approved: "Approved by voice",
  rejected: "Rejected by voice",
  replanning: "Asked for a change: the agent is making a new plan",
  reask: "Not clear: please say it again",
  use_buttons: "Still not clear: please use the buttons",
};

function pickMime(): string {
  for (const t of ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"]) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

export default function VoicePanel({ planId, phone, lang, onDone }: {
  planId: string; phone: string; lang: string; onDone: () => void;
}) {
  const [noteOk, setNoteOk] = useState(true);
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [left, setLeft] = useState(MAX_SECONDS);
  const [heard, setHeard] = useState<VoiceReply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);
  const canRecord = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && pickMime() !== "";

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
    rec.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  async function start() {
    setError(null);
    setHeard(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, noiseSuppression: true } });
    } catch {
      setError("Microphone not allowed. Use the buttons instead.");
      return;
    }
    const chunks: Blob[] = [];
    const r = new MediaRecorder(stream, { mimeType: pickMime() });
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      void send(new Blob(chunks, { type: r.mimeType }));
    };
    rec.current = r;
    r.start();
    setState("recording");
    setLeft(MAX_SECONDS);
    timer.current = window.setInterval(() => {
      setLeft((s) => {
        if (s <= 1) stop();
        return s - 1;
      });
    }, 1000);
  }

  function stop() {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    if (rec.current?.state === "recording") rec.current.stop();
  }

  async function send(audio: Blob) {
    setState("sending");
    try {
      const r = await api.voiceReply(planId, audio, phone);
      setHeard(r);
      if (r.say.audio_url) void new Audio(r.say.audio_url).play().catch(() => undefined);
      if (["approved", "rejected", "replanning"].includes(r.action)) onDone();
    } catch (e) {
      setError(`${(e as Error).message}`);
    } finally {
      setState("idle");
    }
  }

  return (
    <div className="voice-panel">
      {noteOk ? (
        <div className="voice-note">
          <Volume2 size={15} />
          <audio controls preload="none" src={api.voiceNoteUrl(planId)} onError={() => setNoteOk(false)} />
        </div>
      ) : (
        <p className="muted small">Voice note not available right now; the text above says the same.</p>
      )}
      {canRecord && (
        <button className={`btn btn-ghost mic ${state}`} disabled={state === "sending"}
          onClick={state === "recording" ? stop : start}>
          {state === "recording" ? <><Square size={14} /> Stop ({left}s)</>
            : state === "sending" ? <><Loader2 size={14} className="spin" /> Listening…</>
            : <><Mic size={15} /> Reply by voice</>}
        </button>
      )}
      {heard && (
        <div className={`heard ${heard.action}`}>
          <span className="mono dim">heard ({heard.intent_source})</span>
          <p lang={lang}>“{heard.transcript || "…"}”</p>
          <b>{HEARD[heard.action]}</b>
          {heard.question && <span className="muted small">Request: {heard.question}</span>}
          <span className="small" lang={heard.say.lang}>{heard.say.text}</span>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
