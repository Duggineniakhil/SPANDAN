/** Landing "inside the bearing": the 6205 bearing pulls apart as it scrolls into view; hover a part. */
import { Float } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import type { MotionValue } from "framer-motion";
import { useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import { BEARING_PARTS, Bearing, type BearingPart } from "./Bearing";
import { PinLayer, Stage, Studio, type Pin } from "./kit";

type Anchors = MutableRefObject<Partial<Record<BearingPart, THREE.Object3D | null>>>;
type Els = MutableRefObject<Record<string, HTMLElement | null>>;

function Scene({ explode, hovered, onHover, anchors, els }: {
  explode: MotionValue<number>; hovered: BearingPart | null; onHover: (p: BearingPart | null) => void; anchors: Anchors; els: Els;
}) {
  const e = useRef(0);
  const g = useRef<THREE.Group>(null!);
  const hl = useRef(hovered);
  hl.current = hovered;
  useFrame(({ pointer }, dt) => {
    e.current += (explode.get() - e.current) * Math.min(1, dt * 4);
    // three-quarter view, follows the mouse a little
    g.current.rotation.y += (-0.75 + pointer.x * 0.35 - g.current.rotation.y) * Math.min(1, dt * 3);
    g.current.rotation.x += (0.18 - pointer.y * 0.2 - g.current.rotation.x) * Math.min(1, dt * 3);
    // labels fade in once the parts are apart; the hovered one lights up
    const op = String(Math.min(1, Math.max(0, (e.current - 0.45) * 3)));
    for (const p of BEARING_PARTS) {
      const el = els.current[p.id];
      if (!el) continue;
      el.style.opacity = op;
      el.classList.toggle("on", hl.current === p.id);
    }
  });
  return (
    <>
      <Studio rim={0.9} />
      <Float speed={1.4} rotationIntensity={0.15} floatIntensity={0.4}>
        <group ref={g}>
          <Bearing explode={() => e.current} spin={0.9} damage={() => (hl.current === "outer" ? 1 : 0.35)}
            highlight={() => hl.current} onHover={onHover} anchors={anchors} />
        </group>
      </Float>
    </>
  );
}

export default function BearingExplode(props: { explode: MotionValue<number>; hovered: BearingPart | null; onHover: (p: BearingPart | null) => void }) {
  const anchors: Anchors = useRef({});
  const els: Els = useRef({});
  const pins = useRef<Pin[]>(BEARING_PARTS.map((p) => ({ key: p.id, obj: () => anchors.current[p.id] })));
  const overlay = BEARING_PARTS.map((p) => (
    <div key={p.id} className="b-label" ref={(el) => { els.current[p.id] = el; }}>
      <b>{p.name}</b>
      <span>{p.freq}</span>
    </div>
  ));
  return (
    <Stage className="bearing-canvas" camera={{ position: [0, 0.6, 5.6], fov: 36 }} overlay={overlay}>
      <PinLayer pins={pins} els={els} />
      <Scene {...props} anchors={anchors} els={els} />
    </Stage>
  );
}
