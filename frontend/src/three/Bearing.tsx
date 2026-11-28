/**
 * A 6205 deep-groove ball bearing built from code: outer race, inner race, 9 balls, cage. Axis = x.
 * `explode` pulls the parts apart along the axis; `damage` shows a spall on the outer race.
 * Fault frequencies at 2,880 rpm (48 Hz shaft), 6205 geometry (same ratios as the detector):
 * BPFO 3.585× = 172 Hz, BPFI 5.415× = 260 Hz, BSF 2.357× = 113 Hz (2×BSF 226 Hz), FTF 0.398× = 19 Hz.
 */
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import { RED, VOLT, read, ringGeometry, type Sig } from "./kit";

import { BEARING_PARTS, type BearingPart } from "./parts";

export { BEARING_PARTS, type BearingPart };

const N_BALLS = 9;
const PITCH_R = 0.69;

interface Props {
  explode?: Sig;
  spin?: Sig;        // shaft speed, rad/s
  damage?: Sig;      // 0..1 spall size on the outer race
  highlight?: Sig<BearingPart | null>;
  onHover?: (p: BearingPart | null) => void;
  /** filled with one invisible anchor per part, where its label should sit */
  anchors?: MutableRefObject<Partial<Record<BearingPart, THREE.Object3D | null>>>;
}

export function Bearing({ explode = 0, spin = 1.2, damage = 0, highlight = null, onHover, anchors }: Props) {
  const geo = useMemo(() => ({
    outer: ringGeometry(1, 0.82, 0.42),
    inner: ringGeometry(0.56, 0.38, 0.42),
    cage: ringGeometry(0.76, 0.62, 0.16),
    ball: new THREE.SphereGeometry(0.135, 32, 24),
  }), []);
  const mats = useMemo(() => ({
    outer: new THREE.MeshStandardMaterial({ color: "#c9ced6", metalness: 1, roughness: 0.22 }),
    inner: new THREE.MeshStandardMaterial({ color: "#d4d8de", metalness: 1, roughness: 0.18 }),
    balls: new THREE.MeshStandardMaterial({ color: "#e8ebef", metalness: 1, roughness: 0.08 }),
    cage: new THREE.MeshStandardMaterial({ color: "#b08d57", metalness: 0.8, roughness: 0.35 }),
  }), []);

  const outer = useRef<THREE.Group>(null!);
  const inner = useRef<THREE.Group>(null!);
  const cage = useRef<THREE.Group>(null!);
  const cageSpin = useRef<THREE.Mesh>(null!);
  const innerSpin = useRef<THREE.Mesh>(null!);
  const balls = useRef<THREE.Group>(null!);
  const ballMesh = useRef<(THREE.Mesh | null)[]>([]);
  const spall = useRef<THREE.Group>(null!);
  const crackFace = useRef<THREE.Group>(null!);
  const angle = useRef(0);

  useFrame((_, dt) => {
    const e = read(explode);
    const w = read(spin);
    angle.current += dt * w;
    outer.current.position.x = 1.25 * e;
    balls.current.position.x = 0.42 * e;
    cage.current.position.x = -0.42 * e;
    inner.current.position.x = -1.25 * e;
    innerSpin.current.rotation.x = angle.current;
    const cageAngle = angle.current * 0.398;
    cageSpin.current.rotation.x = cageAngle;
    const r = PITCH_R * (1 + 0.55 * e);
    ballMesh.current.forEach((m, i) => {
      if (!m) return;
      const a = cageAngle + (i / N_BALLS) * Math.PI * 2;
      m.position.set(0, Math.cos(a) * r, Math.sin(a) * r);
      m.rotation.x = -angle.current * 2.4;
    });
    const d = read(damage);
    spall.current.visible = d > 0.01;
    spall.current.scale.setScalar(0.3 + 0.7 * d);
    crackFace.current.visible = d > 0.01;
    crackFace.current.scale.setScalar(0.94 + 0.06 * d);
    ((crackFace.current.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial).opacity = Math.min(1, d * 1.4);

    const hl = read(highlight);
    (Object.keys(mats) as BearingPart[]).forEach((k) => {
      const m = mats[k];
      const target = hl === k ? 0.55 : 0;
      m.emissive.copy(VOLT);
      m.emissiveIntensity += (target - m.emissiveIntensity) * Math.min(1, dt * 10);
    });
  });

  const hover = (p: BearingPart | null) => (ev: { stopPropagation: () => void }) => {
    ev.stopPropagation();
    onHover?.(p);
  };
  const label = (id: BearingPart, pos: [number, number, number]) => anchors && (
    <group position={pos} ref={(o) => { anchors.current[id] = o; }} />
  );

  return (
    <group>
      <group ref={outer} onPointerOver={hover("outer")} onPointerOut={hover(null)}>
        <mesh geometry={geo.outer} material={mats.outer} />
        {/* spall: pits on the race's inner surface, top (load zone) */}
        <group ref={spall} position={[0, 0.83, 0]}>
          {[[-0.06, 0, 0.04], [0.05, 0, -0.03], [0, 0, 0.1], [0.02, 0, -0.11]].map((p, i) => (
            <mesh key={i} position={p as [number, number, number]}>
              <boxGeometry args={[0.07 + (i % 2) * 0.04, 0.025, 0.06]} />
              <meshStandardMaterial color={RED} emissive={RED} emissiveIntensity={2.2} toneMapped={false} />
            </mesh>
          ))}
        </group>
        {/* the same damage seen from outside: a glowing crack across the race's front face, at the top */}
        <group ref={crackFace} position={[0.215, 0, 0]} rotation-y={Math.PI / 2}>
          <mesh rotation-z={Math.PI / 2 - 0.32}>
            <torusGeometry args={[0.91, 0.022, 6, 24, 0.64]} />
            <meshBasicMaterial color={RED} toneMapped={false} transparent />
          </mesh>
        </group>
        {label("outer", [0, 1.35, 0])}
      </group>
      <group ref={balls} onPointerOver={hover("balls")} onPointerOut={hover(null)}>
        {Array.from({ length: N_BALLS }, (_, i) => (
          <mesh key={i} ref={(m) => { ballMesh.current[i] = m; }} geometry={geo.ball} material={mats.balls} />
        ))}
        {label("balls", [0, -1.4, 0.35])}
      </group>
      <group ref={cage} onPointerOver={hover("cage")} onPointerOut={hover(null)}>
        <mesh ref={cageSpin} geometry={geo.cage} material={mats.cage} />
        {label("cage", [0, 1.05, -0.4])}
      </group>
      <group ref={inner} onPointerOver={hover("inner")} onPointerOut={hover(null)}>
        <mesh ref={innerSpin} geometry={geo.inner} material={mats.inner} />
        {label("inner", [0, -0.85, 0])}
      </group>
    </group>
  );
}
