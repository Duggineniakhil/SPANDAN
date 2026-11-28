/**
 * Landing page 3D parts: the pinned scroll story (motor wears → caught → planned → repaired) and
 * "inside the bearing". three.js itself is lazy-loaded, so this file is cheap for 2D devices.
 */
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { ArrowRight, ArrowUpRight, Check, Mic } from "lucide-react";
import { lazy, Suspense, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Reveal, RevealText, TypeCycle } from "../components/Motion";
import { BEARING_PARTS, type BearingPart } from "../three/parts";
import { healthAt } from "../three/story";

const HeroStory = lazy(() => import("../three/HeroStory"));
const BearingExplode = lazy(() => import("../three/BearingExplode"));

const CAPTIONS: { from: number; to: number; k: string; title: ReactNode; text: ReactNode; extra?: ReactNode; side?: "left" | "right" }[] = [
  { from: 0.13, to: 0.3, k: "01 · SENSE", title: <>A ₹1,000 sensor <span className="volt">clips on.</span></>,
    text: "It listens to the motor 3,200 times a second and learns this machine's normal in 30 readings." },
  { from: 0.3, to: 0.49, k: "02 · WEAR", side: "right", title: <>Inside, the bearing <span className="volt">starts to wear.</span></>,
    text: "A pit forms on the outer race. The motor still sounds the same. Its vibration doesn't." },
  { from: 0.49, to: 0.68, k: "03 · DETECT", title: <>The phone <span className="volt">hears it first.</span></>,
    text: "Impacts at 172 Hz, the outer race's own frequency. Health falls to 41 %. 4–8 days left." },
  { from: 0.68, to: 0.86, k: "04 · PLAN", side: "right", title: <>One agent <span className="volt">plans the repair.</span></>,
    text: "Cheapest bearing in stock, a mechanic in the owner's idle hours, inside the spending limit.",
    extra: (
      <div className="phone-card">
        <span className="mono dim">PLAN · WAITING FOR YOU</span>
        <ul>
          <li><span>Bearing 6205-2RS</span><b>₹1,450</b></li>
          <li><span>Mechanic Ravi · Sun 10:00</span><b>₹400</b></li>
        </ul>
        <div className="phone-voice"><Mic size={14} /> “ಹೌದು”</div>
        <div className="phone-ok"><Check size={14} /> Approved by voice · booked</div>
      </div>
    ) },
  { from: 0.86, to: 1, k: "05 · FIXED", title: <>Repaired on Sunday. <span className="volt">No lost grinding.</span></>,
    text: "The mechanic's job card tells SPANDAN what was really wrong, and it learns the new normal.",
    extra: (
      <div className="hero-cta left">
        <Link to="/setup" className="btn btn-volt">Start the demo <ArrowRight size={18} /></Link>
        <Link to="/monitor" className="btn btn-line">Live monitor <ArrowUpRight size={18} /></Link>
      </div>
    ) },
];

/** Piecewise-linear map as a plain function: framer runs these on the main thread, which keeps every
 * browser in step (its hardware-accelerated scroll path skipped some ranges). */
function ramp(input: number[], output: number[]) {
  return (v: number) => {
    if (v <= input[0]) return output[0];
    for (let i = 1; i < input.length; i++) {
      if (v <= input[i]) return output[i - 1] + ((output[i] - output[i - 1]) * (v - input[i - 1])) / (input[i] - input[i - 1]);
    }
    return output[output.length - 1];
  };
}

const STATUS = (p: number): string =>
  p < 0.3 ? "RUNNING NORMALLY" : p < 0.49 ? "LISTENING" : p < 0.68 ? "FAULT WARNING · BPFO 172 Hz"
    : p < 0.86 ? "PLAN WAITING FOR OWNER" : "REPAIRED · NEW BASELINE";
const TINT = (h: number) => (h >= 70 ? "#ccff00" : h >= 50 ? "#ffb020" : "#ff4d3d");

export function Story3D() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress: p } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const titleOpacity = useTransform(p, ramp([0, 0.08, 0.12], [1, 1, 0]));
  const titleY = useTransform(p, ramp([0, 0.12], [0, -80]));
  const hintOpacity = useTransform(p, ramp([0, 0.04], [1, 0]));
  const health = useTransform(p, (v) => `${healthAt(v)}%`);
  const tint = useTransform(p, (v) => TINT(healthAt(v)));
  const status = useTransform(p, STATUS);
  const rail = useTransform(p, (v) => `${Math.round(v * 1000) / 10}%`);

  return (
    <section className="story3d" ref={ref}>
      <div className="story-stick">
        <Suspense fallback={<div className="story-canvas" />}>
          <HeroStory progress={p} />
        </Suspense>
        <div className="story-shade" />
        <div className="grain" aria-hidden />
        <div className="hud" aria-hidden>
          <span className="hud-corner tl" /><span className="hud-corner tr" /><span className="hud-corner bl" /><span className="hud-corner br" />
          <span className="hud-label tl mono">REC ● SENSOR 01 · 3.2 kHz</span>
          <span className="hud-label tr mono">GRINDER MOTOR · 2,880 RPM</span>
        </div>

        <motion.div className="hero-content story-title" style={{ opacity: titleOpacity, y: titleY }}>
          <motion.span className="hero-tag mono" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}>
            [ PREDICTIVE MAINTENANCE FOR SMALL FLOUR MILLS ]
          </motion.span>
          <h1 className="hero-title">
            <RevealText text="Hear the breakdown" />
            <RevealText text="before it happens." delay={0.35} className="volt" />
          </h1>
          <motion.p className="hero-sub" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1 }}>
            A ₹1,000 clip-on sensor and a phone catch{" "}
            <TypeCycle phrases={["bearing wear", "imbalance", "loose mountings"]} className="type" />{" "}
            days early. An AI agent plans the repair. The owner says yes.
          </motion.p>
        </motion.div>
        <motion.div className="scroll-hint mono" style={{ opacity: hintOpacity }}>SCROLL TO SEE IT HAPPEN<i /></motion.div>

        {CAPTIONS.map((c) => <Caption key={c.k} p={p} {...c} />)}

        <div className="story-readout mono">
          <span>HEALTH <motion.b style={{ color: tint }}>{health}</motion.b></span>
          <motion.span style={{ color: tint }}>{status}</motion.span>
        </div>
        <div className="story-rail" aria-hidden><motion.i style={{ height: rail }} /></div>
      </div>
    </section>
  );
}

function Caption({ p, from, to, k, title, text, extra, side = "left" }: {
  p: MotionValue<number>; from: number; to: number; k: string; title: ReactNode; text: ReactNode; extra?: ReactNode; side?: "left" | "right";
}) {
  const fade = 0.035;
  const last = to >= 1; // the last caption stays; scroll ranges must stay inside 0–1
  const input = last ? [from, from + fade, 1] : [from, from + fade, to - fade, to];
  const opacity = useTransform(p, ramp(input, last ? [0, 1, 1] : [0, 1, 1, 0]));
  const y = useTransform(p, ramp(input, last ? [50, 0, 0] : [50, 0, 0, -50]));
  const rotateX = useTransform(p, ramp([from, from + fade], [-25, 0]));
  const pointerEvents = useTransform(opacity, (o) => (o > 0.5 ? "auto" : "none"));
  return (
    <motion.div className={`story-cap ${side}`} style={{ opacity, y, rotateX, pointerEvents, transformPerspective: 900 }}>
      <span className="mono volt">{k}</span>
      <h2>{title}</h2>
      <p>{text}</p>
      {extra}
    </motion.div>
  );
}

export function BearingSection({ use3D }: { use3D: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const explode = useTransform(scrollYProgress, ramp([0.3, 1], [0, 1]));
  const [hovered, setHovered] = useState<BearingPart | null>(null);
  return (
    <section className="section" ref={ref}>
      <div className="section-index mono"><span>03</span> INSIDE THE BEARING</div>
      <div className={use3D ? "split bearing-split" : ""}>
        <div>
          <Reveal><h2 className="h2">Each part fails at <span className="volt">its own frequency.</span></h2></Reveal>
          <p className="lead">
            The diagnosis is physics, not a black box. A pit on any part of a bearing makes impacts at a rate set by the
            bearing's geometry and the shaft speed. SPANDAN looks for exactly those, on a 6205 bearing at 2,880 rpm:
          </p>
          <ul className="part-list">
            {BEARING_PARTS.map((part) => (
              <li key={part.id} className={hovered === part.id ? "on" : ""}
                onMouseEnter={() => setHovered(part.id)} onMouseLeave={() => setHovered(null)}>
                <span className="part-name">{part.name}</span>
                <span className="mono volt">{part.freq}</span>
                <span className="part-note">{part.note}</span>
              </li>
            ))}
          </ul>
        </div>
        {use3D && (
          <Suspense fallback={<div className="bearing-canvas" />}>
            <BearingExplode explode={explode} hovered={hovered} onHover={setHovered} />
          </Suspense>
        )}
      </div>
    </section>
  );
}
