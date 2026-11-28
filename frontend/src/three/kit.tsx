/** Shared 3D pieces: colours, value "signals", geometry helpers, lights and a canvas that sleeps off-screen. */
import { Canvas, useFrame, type CanvasProps } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import { useInView } from "framer-motion";
import { useMemo, useRef, type MutableRefObject, type ReactNode } from "react";
import * as THREE from "three";
import { clamp01 } from "./math";

export const VOLT = new THREE.Color("#ccff00");
export const AMBER = new THREE.Color("#ffb020");
export const RED = new THREE.Color("#ff4d3d");
export const WHITE = new THREE.Color("#f2f2f2");

export { clamp01, read, smooth, type Sig } from "./math";

/** Health 100 → 0 as volt → amber → red (smooth, for 3D glows). */
export function healthTint(h: number, out = new THREE.Color()): THREE.Color {
  if (h >= 70) return out.copy(VOLT);
  if (h >= 50) return out.copy(AMBER).lerp(VOLT, (h - 50) / 20);
  return out.copy(RED).lerp(AMBER, clamp01((h - 35) / 15));
}

/** A washer-shaped solid (ring with a hole) whose axis is x. */
export function ringGeometry(rOut: number, rIn: number, width: number, segments = 72): THREE.BufferGeometry {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, rOut, 0, Math.PI * 2, false);
  const hole = new THREE.Path();
  hole.absarc(0, 0, rIn, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  const bevel = Math.min(0.02, width * 0.08);
  const g = new THREE.ExtrudeGeometry(shape, {
    depth: width - 2 * bevel, bevelEnabled: true, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 2,
    curveSegments: segments,
  });
  g.translate(0, 0, -(width - 2 * bevel) / 2);
  g.rotateY(Math.PI / 2);
  return g;
}

/** Studio lighting built locally (no HDR download): a soft key, a cool fill and a volt rim. */
export function Studio({ rim = 0.6 }: { rim?: number }) {
  return (
    <>
      <ambientLight intensity={0.25} />
      <directionalLight position={[5, 6, 4]} intensity={1.5} />
      <directionalLight position={[-5, 2, -4]} intensity={rim} color="#ccff00" />
      <Environment resolution={128} frames={1}>
        <Lightformer form="rect" intensity={2.2} position={[0, 4, 3]} scale={[8, 2, 1]} />
        <Lightformer form="rect" intensity={0.8} position={[-5, 1, 0]} rotation-y={Math.PI / 2} scale={[6, 3, 1]} />
        <Lightformer form="rect" intensity={0.6} color="#ccff00" position={[5, 0, -2]} rotation-y={-Math.PI / 2} scale={[4, 1, 1]} />
        <Lightformer form="ring" intensity={1.2} position={[0, -3, 4]} scale={3} />
      </Environment>
    </>
  );
}

/** HTML labels pinned to 3D points: plain DOM in one overlay, moved every frame by projecting the point.
 * (Used instead of drei's <Html>, which makes one React root per label; under React 19 dev double-mounting
 * the first of a list could fail to mount.) */
export interface Pin { key: string; at?: [number, number, number]; obj?: () => THREE.Object3D | null | undefined }
export function PinLayer({ pins, els }: { pins: MutableRefObject<Pin[]>; els: MutableRefObject<Record<string, HTMLElement | null>> }) {
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, size }) => {
    for (const p of pins.current) {
      const el = els.current[p.key];
      if (!el) continue;
      const o = p.obj?.();
      if (o) o.getWorldPosition(v);
      else if (p.at) v.set(p.at[0], p.at[1], p.at[2]);
      else continue;
      v.project(camera);
      el.style.transform = `translate(-50%, -50%) translate3d(${((v.x + 1) / 2) * size.width}px, ${((1 - v.y) / 2) * size.height}px, 0)`;
      el.style.visibility = v.z > 1 ? "hidden" : "";
    }
  });
  return null;
}

/** A transparent canvas that only renders while it is on screen; `overlay` is HTML drawn on top of it. */
export function Stage({ children, className, camera, overlay, ...rest }: { children: ReactNode; className?: string; overlay?: ReactNode } & CanvasProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "120px" });
  return (
    <div ref={ref} className={`stage ${className ?? ""}`}>
      <Canvas
        frameloop={inView ? "always" : "never"}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={camera ?? { position: [4, 2, 5], fov: 35 }}
        {...rest}
      >
        {children}
      </Canvas>
      {overlay && <div className="pin-layer">{overlay}</div>}
    </div>
  );
}
