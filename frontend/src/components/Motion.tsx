import { animate, motion, useInView, useMotionValue, useScroll, useTransform, type MotionValue } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode } from "react";

/** Words slide up one after another. */
export function RevealText({ text, className = "", delay = 0 }: { text: string; className?: string; delay?: number }) {
  const words = text.split(" ");
  return (
    <span className={className} aria-label={text}>
      {words.map((w, i) => (
        <span key={i} className="reveal-word" aria-hidden>
          <motion.span
            initial={{ y: "110%", opacity: 0 }}
            animate={{ y: "0%", opacity: 1 }}
            transition={{ delay: delay + i * 0.08, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            style={{ display: "inline-block" }}
          >
            {w}&nbsp;
          </motion.span>
        </span>
      ))}
    </span>
  );
}

/** Types each phrase, holds it, deletes it, moves to the next. */
export function TypeCycle({ phrases, className = "" }: { phrases: string[]; className?: string }) {
  const [i, setI] = useState(0);
  const [shown, setShown] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const full = phrases[i % phrases.length];
    let t: ReturnType<typeof setTimeout>;
    if (!deleting && shown === full) t = setTimeout(() => setDeleting(true), 1600);
    else if (deleting && shown === "") {
      setDeleting(false);
      setI((v) => v + 1);
    } else {
      t = setTimeout(
        () => setShown(deleting ? full.slice(0, shown.length - 1) : full.slice(0, shown.length + 1)),
        deleting ? 35 : 70,
      );
    }
    return () => clearTimeout(t);
  }, [shown, deleting, i, phrases]);

  return (
    <span className={className}>
      {shown}
      <span className="caret" aria-hidden>|</span>
    </span>
  );
}

/** Words light up one by one as the paragraph scrolls through the viewport. */
export function ScrubText({ text, className = "" }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.45"] });
  const words = text.split(" ");
  return (
    <p ref={ref} className={className} aria-label={text}>
      {words.map((w, i) => (
        <ScrubWord key={i} word={w} progress={scrollYProgress} range={[i / words.length, (i + 1) / words.length]} />
      ))}
    </p>
  );
}

function ScrubWord({ word, progress, range }: { word: string; progress: MotionValue<number>; range: [number, number] }) {
  const opacity = useTransform(progress, range, [0.18, 1]);
  return <motion.span style={{ opacity }} aria-hidden>{word} </motion.span>;
}

/** Fades and lifts its children when scrolled into view. */
export function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.7, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

/** Counts up to `to` when it becomes visible. */
export function CountUp({ to, prefix = "", suffix = "", duration = 1.6 }: { to: number; prefix?: string; suffix?: string; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const value = useMotionValue(0);
  const text = useTransform(value, (v) => `${prefix}${Math.round(v).toLocaleString("en-IN")}${suffix}`);
  useEffect(() => {
    if (inView) {
      const c = animate(value, to, { duration, ease: "easeOut" });
      return () => c.stop();
    }
  }, [inView, to, duration, value]);
  return <motion.span ref={ref}>{text}</motion.span>;
}
