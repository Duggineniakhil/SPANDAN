/** A card that leans toward the mouse in 3D, with a moving glare. Touch screens and reduced motion: flat. */
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { type CSSProperties, type ReactNode, useRef } from "react";

const SPRING = { stiffness: 220, damping: 22, mass: 0.6 };

export function Tilt({ children, className = "", max = 9, glare = true, lift = 18, style }: {
  children: ReactNode; className?: string; max?: number; glare?: boolean; lift?: number; style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const hover = useMotionValue(0);
  const rx = useSpring(useTransform(py, [0, 1], [max, -max]), SPRING);
  const ry = useSpring(useTransform(px, [0, 1], [-max, max]), SPRING);
  const z = useSpring(useTransform(hover, [0, 1], [0, lift]), SPRING);
  const gx = useTransform(px, (v) => `${v * 100}%`);
  const gy = useTransform(py, (v) => `${v * 100}%`);
  const glareBg = useMotionTemplate`radial-gradient(circle at ${gx} ${gy}, rgba(255,255,255,0.16), rgba(255,255,255,0) 55%)`;
  const glareOpacity = useSpring(hover, SPRING);

  if (reduce) return <div className={className} style={style}>{children}</div>;

  const move = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    const r = ref.current!.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width);
    py.set((e.clientY - r.top) / r.height);
    hover.set(1);
  };
  const leave = () => {
    px.set(0.5);
    py.set(0.5);
    hover.set(0);
  };

  return (
    <motion.div ref={ref} className={`tilt ${className}`} onPointerMove={move} onPointerLeave={leave}
      style={{ ...style, rotateX: rx, rotateY: ry, z, transformPerspective: 900 }}>
      {children}
      {glare && <motion.span className="tilt-glare" aria-hidden style={{ background: glareBg, opacity: glareOpacity }} />}
    </motion.div>
  );
}
