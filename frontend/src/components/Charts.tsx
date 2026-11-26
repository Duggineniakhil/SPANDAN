import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import type { Spectrum } from "../lib/features";

export function healthColor(h: number | null): string {
  if (h === null) return "#555555";
  return h >= 70 ? "#ccff00" : h >= 40 ? "#f2f2f2" : "#ff4d3d";
}

export function HealthRing({ health, size = 220, label }: { health: number | null; size?: number; label?: string }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const h = health ?? 0;
  const color = healthColor(health);
  return (
    <div className="health-ring" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" width={size} height={size}>
        <circle cx="50" cy="50" r={r} fill="none" stroke="#1a1a1a" strokeWidth="6" />
        <motion.circle
          cx="50" cy="50" r={r} fill="none" stroke={color} strokeLinecap="butt"
          strokeDasharray={c} transform="rotate(-90 50 50)" strokeWidth={6}
          animate={{ strokeDashoffset: c * (1 - h / 100), stroke: color }}
          transition={{ type: "spring", stiffness: 60, damping: 18 }}
          style={{ filter: `drop-shadow(0 0 8px ${color}55)` }}
        />
      </svg>
      <div className="health-ring-label">
        <motion.span key={health ?? "none"} initial={{ scale: 0.8, opacity: 0.4 }} animate={{ scale: 1, opacity: 1 }} className="health-value" style={{ color }}>
          {health === null ? "—" : `${h}%`}
        </motion.span>
        <span className="health-caption">{label ?? "machine health"}</span>
      </div>
    </div>
  );
}

function useCanvas(draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void, deps: unknown[]) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    draw(ctx, width, height);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

export function Waveform({ data, color = "#e8e8e8" }: { data: Float64Array | null; color?: string }) {
  const ref = useCanvas((ctx, w, h) => {
    ctx.strokeStyle = "#222";
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();
    if (!data) return;
    let max = 0.2;
    for (const v of data) max = Math.max(max, Math.abs(v));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = (i / (data.length - 1)) * w;
      const y = h / 2 - (data[i] / max) * (h / 2 - 6);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }, [data]);
  return <canvas ref={ref} className="chart-canvas" aria-label="Vibration waveform" />;
}

export interface Marker {
  f: number;
  label: string;
  color: string;
}

export function SpectrumChart({ spectrum, maxHz = 1600, markers = [], color = "#ccff00" }: { spectrum: Spectrum | null; maxHz?: number; markers?: Marker[]; color?: string }) {
  const ref = useCanvas((ctx, w, h) => {
    const pad = 16;
    ctx.fillStyle = "#666";
    ctx.font = "10px JetBrains Mono, monospace";
    for (let f = 0; f <= maxHz; f += maxHz <= 600 ? 100 : 400) {
      const x = (f / maxHz) * w;
      ctx.fillText(`${f}`, Math.min(x + 2, w - 26), h - 3);
    }
    if (!spectrum) return;
    const { freqs, amp } = spectrum;
    // Decibel scale (top 60 dB) so small peaks stay visible next to a large 1× peak.
    const RANGE_DB = 60;
    let peakDb = -200;
    for (let k = 1; k < freqs.length && freqs[k] <= maxHz; k++) peakDb = Math.max(peakDb, 20 * Math.log10(amp[k] + 1e-12));
    const level = (a: number) => Math.max(0, (20 * Math.log10(a + 1e-12) - (peakDb - RANGE_DB)) / RANGE_DB);
    const pts: [number, number][] = [];
    for (let k = 1; k < freqs.length && freqs[k] <= maxHz; k++) {
      pts.push([(freqs[k] / maxHz) * w, h - pad - level(amp[k]) * (h - pad - 14)]);
    }
    // faint fill under a crisp line
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, `${color}40`);
    grad.addColorStop(1, `${color}00`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, h - pad);
    for (const [x, y] of pts) ctx.lineTo(x, y);
    ctx.lineTo(w, h - pad);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();
    markers.forEach((m, i) => {
      if (m.f > maxHz) return;
      const x = (m.f / maxHz) * w;
      ctx.strokeStyle = m.color;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, 12);
      ctx.lineTo(x, h - pad);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = m.color;
      // stagger labels so close markers (e.g. 1× and 2×) don't overlap
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(m.label, Math.min(x + 3, w - 40), 10 + (i % 2) * 12);
    });
  }, [spectrum, maxHz, markers]);
  return <canvas ref={ref} className="chart-canvas" aria-label="Vibration spectrum" />;
}

/** Animated vibration lines, used behind the hero (and as the fallback if the video is missing). */
export function WaveBackground() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const resize = () => {
      canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1);
      canvas.height = canvas.clientHeight * (window.devicePixelRatio || 1);
    };
    resize();
    window.addEventListener("resize", resize);
    const lines = [
      { amp: 0.06, freq: 0.012, speed: 0.9, color: "rgba(245,158,11,0.55)", y: 0.62 },
      { amp: 0.04, freq: 0.02, speed: 1.4, color: "rgba(56,189,248,0.35)", y: 0.68 },
      { amp: 0.03, freq: 0.03, speed: 2.1, color: "rgba(16,185,129,0.3)", y: 0.74 },
    ];
    const draw = (t: number) => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      for (const l of lines) {
        ctx.strokeStyle = l.color;
        ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
        ctx.beginPath();
        for (let x = 0; x <= w; x += 4) {
          const spike = Math.exp(-(((x / w - ((t / 6000) % 1.2) + 0.1) * 14) ** 2)) * 0.12;
          const y = h * l.y + h * (l.amp + spike) * Math.sin(x * l.freq + (t / 1000) * l.speed) * Math.sin(x * 0.003 + t / 3000);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);
  return <canvas ref={ref} className="wave-bg" aria-hidden />;
}
