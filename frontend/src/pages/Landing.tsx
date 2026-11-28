import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CloudArt, OwnerArt, PhoneArt, SensorArt } from "../art/Illustrations";
import { LiveSignal } from "../components/LiveSignal";
import { CountUp, Reveal, RevealText, ScrubText, TypeCycle } from "../components/Motion";
import { Tilt } from "../components/Tilt";
import { MEDIA } from "../media";
import { can3D } from "../three/support";
import { BearingSection, Story3D } from "./LandingStory";

const STEPS = [
  { n: "01", title: "Sense", text: "A clip-on vibration sensor on the motor streams readings to a phone in the mill.", Art: SensorArt, tag: "HARDWARE" },
  { n: "02", title: "Detect", text: "The phone learns this machine's normal and flags early signs of a fault. No internet needed.", Art: PhoneArt, tag: "ON-DEVICE ML" },
  { n: "03", title: "Plan", text: "Cloud models name the fault and days left. One AI agent gets quotes and a mechanic slot.", Art: CloudArt, tag: "ML + AGENT" },
  { n: "04", title: "Approve", text: "The owner hears the plan in Kannada or Hindi and says yes or no. Nothing moves without it.", Art: OwnerArt, tag: "HUMAN" },
];

const STORY = [
  { t: "T+0", title: "Vibration doubles", text: "A change on the grinder motor nobody can hear yet." },
  { t: "T+3 MIN", title: "Health 41%", text: "Phone raises the alert, offline." },
  { t: "T+5 MIN", title: "Outer-race wear", text: "4–8 days left before failure." },
  { t: "T+6 MIN", title: "Plan ready", text: "₹1,450 bearing · Mechanic Ravi · Sun 10:00" },
  { t: "T+1 HR", title: "“ಹೌದು”", text: "Owner approves by voice. Zero lost production." },
];

const MARQUEE = ["SENSE", "DETECT", "PLAN", "APPROVE", "ಕನ್ನಡ", "हिन्दी", "OFFLINE-FIRST", "OWNER IN CONTROL"];

export default function Landing() {
  const use3D = can3D();
  return (
    <div className="landing">
      {use3D ? <Story3D /> : <VideoHero />}

      {/* ================= MARQUEE ================= */}
      <div className="marquee" aria-hidden>
        <div className="marquee-track">
          {[...MARQUEE, ...MARQUEE, ...MARQUEE].map((w, i) => (
            <span key={i}>{w}<b>✦</b></span>
          ))}
        </div>
      </div>

      {/* ================= 01 PROBLEM ================= */}
      <section className="section">
        <div className="section-index mono"><span>01</span> THE PROBLEM</div>
        <ScrubText className="statement"
          text="Small mills run their machines until something breaks. Then the grinding stops for days while someone finds a mechanic and buys the part in town at emergency prices." />
        <div className="stats">
          <Tilt className="stat" max={7} glare={false}><span className="stat-num"><CountUp to={4} />–<CountUp to={8} /><small>days</small></span><span className="mono dim">WARNING BEFORE FAILURE</span></Tilt>
          <Tilt className="stat" max={7} glare={false}><span className="stat-num">₹<CountUp to={1450} /></span><span className="mono dim">PLANNED REPAIR, NOT EMERGENCY</span></Tilt>
          <Tilt className="stat" max={7} glare={false}><span className="stat-num"><CountUp to={0} /><small>actions</small></span><span className="mono dim">WITHOUT THE OWNER'S YES</span></Tilt>
        </div>
      </section>

      {/* ================= 02 HOW ================= */}
      <section className="section">
        <div className="section-index mono"><span>02</span> HOW IT WORKS</div>
        <Reveal><h2 className="h2">From vibration to an <span className="volt">approved repair.</span></h2></Reveal>
        <div className="steps">
          {STEPS.map(({ n, title, text, Art, tag }, i) => (
            <Tilt key={n} className="step">
              <Reveal delay={i * 0.1}>
                <div className="step-top mono"><span className="volt">{n}</span><span className="dim">{tag}</span></div>
                <Art className="step-art" />
                <h3>{title}</h3>
                <p>{text}</p>
              </Reveal>
            </Tilt>
          ))}
        </div>
      </section>

      {/* ================= 03 BEARING ================= */}
      <BearingSection use3D={use3D} />

      {/* ================= 04 LIVE ================= */}
      <section className="section">
        <div className="section-index mono"><span>04</span> LIVE SIGNAL</div>
        <div className="split">
          <Reveal>
            <h2 className="h2">Watch a bearing <span className="volt">wear out.</span></h2>
            <p className="lead">
              This is the real detection pipeline running in your browser. A simulated bearing starts healthy, then its
              outer race wears. Impacts appear at the bearing's fault frequency (BPFO), kurtosis climbs, and health falls.
            </p>
            <Link to="/setup" className="link-arrow">Run it on your own machine <ArrowRight size={16} /></Link>
          </Reveal>
          <Reveal delay={0.15}><LiveSignal /></Reveal>
        </div>
      </section>

      {/* ================= 05 STORY ================= */}
      <section className="section">
        <div className="section-index mono"><span>05</span> ONE BREAKDOWN, PREVENTED</div>
        <Reveal><h2 className="h2">A ₹1,450 bearing <span className="volt">saves a week.</span></h2></Reveal>
        <div className="story">
          <motion.div className="story-line" initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: 1.6, ease: "easeInOut" }} />
          {STORY.map((s, i) => (
            <Reveal key={i} delay={0.2 + i * 0.15} className="story-item">
              <span className="story-dot" />
              <span className="mono volt">{s.t}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </Reveal>
          ))}
        </div>
        <p className="mono dim note">ILLUSTRATIVE EXAMPLE FOR ONE FLOUR MILL</p>
      </section>

      {/* ================= 06 CONTROL ================= */}
      <section className="section">
        <div className="section-index mono"><span>06</span> THE OWNER STAYS IN CONTROL</div>
        <Reveal><h2 className="h2">One agent for judgement. <span className="dim-text">Rules for everything else.</span></h2></Reveal>
        <div className="rules">
          {[
            { k: "AUTOMATIC", items: ["Log readings", "Send alerts", "Ask dealers for quotes", "Check mechanic availability"] },
            { k: "OWNER APPROVES", items: ["Buy a part within the limit", "Confirm a mechanic", "Schedule downtime", "Share data"], hot: true },
            { k: "NEVER", items: ["Make payments", "Start or stop a machine"] },
          ].map((r, i) => (
            <Tilt key={r.k} className={`rule ${r.hot ? "hot" : ""}`} max={6}>
              <Reveal delay={i * 0.1}>
                <span className="mono">{r.k}</span>
                <ul>{r.items.map((it) => <li key={it}>{it}</li>)}</ul>
              </Reveal>
            </Tilt>
          ))}
        </div>
        <Reveal><p className="mono rule-foot"><span className="volt">■</span> NO REPLY = NO ACTION</p></Reveal>
      </section>

      {/* ================= CTA ================= */}
      <section className="cta">
        <Reveal>
          <h2 className="cta-title">See it catch<br /><span className="volt">a fault.</span></h2>
          <Link to="/setup" className="btn btn-volt big">Start the demo <ArrowRight size={20} /></Link>
        </Reveal>
      </section>

      <footer className="footer mono">
        <span>SPANDAN — TEAM CREED · AMRITA VISHWA VIDYAPEETHAM</span>
        <span>TECH4BHARAT 2026 · AGENTIC AI</span>
        {MEDIA.credits.length > 0 && <span className="dim">{MEDIA.credits.join(" · ").toUpperCase()}</span>}
      </footer>
    </div>
  );
}

/** 2D hero: the stock mill video (phones without 3D, reduced motion). */
function VideoHero() {
  const [videoOk, setVideoOk] = useState(true);
  const heroRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start start", "end start"] });
  const videoScale = useTransform(scrollYProgress, [0, 1], [1, 1.15]);
  const contentY = useTransform(scrollYProgress, [0, 1], [0, 140]);
  const contentOpacity = useTransform(scrollYProgress, [0, 0.7], [1, 0]);
  return (
    <>
      {/* ================= HERO ================= */}
      <section className="hero" ref={heroRef}>
        {videoOk && (
          <motion.video className="hero-video" style={{ scale: videoScale }} autoPlay muted loop playsInline
            poster={MEDIA.heroPoster} onError={() => setVideoOk(false)}>
            <source src={MEDIA.heroVideo} type="video/mp4" onError={() => setVideoOk(false)} />
          </motion.video>
        )}
        <div className="hero-shade" />
        <div className="grain" aria-hidden />
        <div className="hud" aria-hidden>
          <span className="hud-corner tl" /><span className="hud-corner tr" /><span className="hud-corner bl" /><span className="hud-corner br" />
          <span className="hud-label tl mono">REC ● SENSOR 01 · 3.2 kHz</span>
          <span className="hud-label tr mono">12.97° N · 77.59° E</span>
        </div>

        <motion.div className="hero-content" style={{ y: contentY, opacity: contentOpacity }}>
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
          <motion.div className="hero-cta" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1.2 }}>
            <Link to="/setup" className="btn btn-volt">Start the demo <ArrowRight size={18} /></Link>
            <Link to="/monitor" className="btn btn-line">Live monitor <ArrowUpRight size={18} /></Link>
          </motion.div>
        </motion.div>

        <div className="hero-ticker mono" aria-hidden>
          <span>RMS 0.21 g</span><span>KURTOSIS 3.04</span><span>1× 48.0 Hz</span><span>BPFO 172.1 Hz</span>
          <span className="volt">HEALTH 96%</span>
        </div>
      </section>

    </>
  );
}
