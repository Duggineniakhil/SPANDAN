/**
 * Dashboard: every machine as a small motor on its own plinth, laid out like a mill floor.
 * The glow ring is the machine's health colour; an open alert pulses red with a warning beacon;
 * a plan waiting for the owner shows a volt tag. Click a machine to select it; the camera glides over.
 */
import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { FleetMachine } from "../lib/api";
import { PinLayer, RED, Stage, Studio, VOLT, healthTint, type Pin } from "./kit";

const GAP = 2.6;

function layout(n: number): [number, number][] {
  const cols = Math.max(1, Math.ceil(Math.sqrt(n * 1.6)));
  const rows = Math.ceil(n / cols);
  return Array.from({ length: n }, (_, i) => {
    const c = i % cols;
    const r = Math.floor(i / cols);
    return [(c - (cols - 1) / 2) * GAP, (r - (rows - 1) / 2) * GAP];
  });
}

function machineView(m: FleetMachine) {
  const alert = !!m.open_event_id && m.open_event_status !== "planned";
  const health = m.health_index ?? (m.state === "baseline" || m.state === "setup" ? null : 96);
  return { alert, health, running: m.state === "monitoring" };
}

function MiniMotor({ m, pos, selected, onSelect, onHover }: {
  m: FleetMachine; pos: [number, number]; selected: boolean; onSelect: () => void; onHover: (on: boolean) => void;
}) {
  const group = useRef<THREE.Group>(null!);
  const ring = useRef<THREE.MeshBasicMaterial>(null!);
  const beacon = useRef<THREE.Mesh>(null!);
  const pulley = useRef<THREE.Mesh>(null!);
  const led = useRef<THREE.MeshStandardMaterial>(null!);
  const tint = useMemo(() => new THREE.Color(), []);
  const hover = useRef(false);
  const { alert, health, running } = machineView(m);

  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime;
    if (health === null) tint.set("#555555");
    else healthTint(health, tint);
    if (alert) tint.lerp(RED, 0.5 + 0.5 * Math.sin(t * 5));
    ring.current.color.copy(tint);
    ring.current.opacity = alert ? 0.6 + 0.4 * Math.sin(t * 5) : 0.85;
    const lift = (selected ? 0.35 : 0) + (hover.current ? 0.15 : 0);
    group.current.position.y += (lift - group.current.position.y) * Math.min(1, dt * 8);
    if (running) pulley.current.rotation.x += dt * 4;
    if (beacon.current) {
      beacon.current.visible = alert;
      beacon.current.position.y = 1.55 + Math.sin(t * 3) * 0.08;
      beacon.current.rotation.y += dt * 2;
    }
    group.current.position.x = alert && running ? (Math.random() - 0.5) * 0.03 : 0;
    led.current.emissive.copy(tint);
  });

  return (
    <group position={[pos[0], 0, pos[1]]}>
      {/* plinth + glow ring */}
      <RoundedBox args={[2.1, 0.16, 2.1]} radius={0.05} position={[0, -0.08, 0]}
        onClick={(e) => { e.stopPropagation(); onSelect(); }}
        onPointerOver={(e) => { e.stopPropagation(); hover.current = true; onHover(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { hover.current = false; onHover(false); document.body.style.cursor = ""; }}>
        <meshStandardMaterial color={selected ? "#1a1f0a" : "#111"} metalness={0.4} roughness={0.6} />
      </RoundedBox>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0.005, 0]}>
        <ringGeometry args={[0.92, 1.0, 64]} />
        <meshBasicMaterial ref={ring} transparent toneMapped={false} />
      </mesh>
      {selected && (
        <mesh rotation-x={-Math.PI / 2} position={[0, 0.006, 0]}>
          <ringGeometry args={[1.04, 1.07, 64]} />
          <meshBasicMaterial color={VOLT} toneMapped={false} />
        </mesh>
      )}
      {/* the motor */}
      <group ref={group} position-x={0}
        onClick={(e) => { e.stopPropagation(); onSelect(); }}
        onPointerOver={(e) => { e.stopPropagation(); hover.current = true; onHover(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { hover.current = false; onHover(false); document.body.style.cursor = ""; }}>
        <group position={[0, 0.48, 0]} scale={0.42}>
          <mesh rotation-z={Math.PI / 2}>
            <cylinderGeometry args={[0.9, 0.9, 2.2, 32]} />
            <meshStandardMaterial color="#2b2f34" metalness={0.75} roughness={0.38} />
          </mesh>
          {Array.from({ length: 12 }, (_, i) => {
            const a = (i / 12) * Math.PI * 2;
            return (
              <mesh key={i} position={[0, Math.cos(a) * 0.95, Math.sin(a) * 0.95]} rotation-x={-a}>
                <boxGeometry args={[2.0, 0.12, 0.04]} />
                <meshStandardMaterial color="#2b2f34" metalness={0.75} roughness={0.38} />
              </mesh>
            );
          })}
          <mesh position={[-1.35, 0, 0]} rotation-z={Math.PI / 2}>
            <cylinderGeometry args={[0.85, 0.9, 0.5, 32]} />
            <meshStandardMaterial color="#16181b" metalness={0.6} roughness={0.5} />
          </mesh>
          <mesh ref={pulley} position={[1.55, 0, 0]} rotation-z={Math.PI / 2}>
            <cylinderGeometry args={[0.42, 0.42, 0.3, 24]} />
            <meshStandardMaterial color="#5d636b" metalness={0.9} roughness={0.3} />
          </mesh>
          <mesh position={[0, -1.0, 0]}>
            <boxGeometry args={[2.3, 0.14, 1.4]} />
            <meshStandardMaterial color="#16181b" />
          </mesh>
          <mesh position={[0.8, 1.0, 0]}>
            <boxGeometry args={[0.36, 0.16, 0.26]} />
            <meshStandardMaterial ref={led} color="#0b0b0b" emissiveIntensity={0.6} toneMapped={false} />
          </mesh>
        </group>
        <mesh ref={beacon} position={[0, 1.55, 0]} visible={false}>
          <octahedronGeometry args={[0.16, 0]} />
          <meshBasicMaterial color={RED} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

/** Frames the whole floor and leans toward the selected machine. */
function CameraGlide({ target, span }: { target: [number, number] | null; span: number }) {
  const look = useRef(new THREE.Vector3());
  useFrame(({ camera, size }, dt) => {
    const [tx, tz] = target ?? [0, 0];
    const narrow = size.width / size.height < 2.2 ? 1.25 : 1;
    const x = tx * 0.35;
    const z = tz * 0.35;
    const h = (2.6 + span * 0.36) * narrow;
    const d = (3.4 + span * 0.42) * narrow;
    const k = Math.min(1, dt * 2.2);
    camera.position.x += (x - camera.position.x) * k;
    camera.position.y += (h - camera.position.y) * k;
    camera.position.z += (z + d - camera.position.z) * k;
    look.current.x += (x - look.current.x) * k;
    look.current.z += (z - look.current.z) * k;
    camera.lookAt(look.current);
  });
  return null;
}

export default function FleetFloor({ fleet, selected, onSelect }: { fleet: FleetMachine[]; selected: string | null; onSelect: (id: string) => void }) {
  const pos = useMemo(() => layout(fleet.length), [fleet.length]);
  const span = useMemo(() => Math.max(GAP, ...pos.map(([x, z]) => Math.max(Math.abs(x), Math.abs(z)) * 2 + GAP)), [pos]);
  const idx = fleet.findIndex((m) => m.machine_id === selected);
  const [hovered, setHovered] = useState<string | null>(null);
  const els = useRef<Record<string, HTMLElement | null>>({});
  const pins = useRef<Pin[]>([]);
  pins.current = fleet.map((m, i) => ({ key: m.machine_id, at: [pos[i][0], -0.05, pos[i][1] + 1.22] }));
  const overlay = fleet.map((m) => {
    const v = machineView(m);
    const show = m.machine_id === selected || m.machine_id === hovered;
    return (
      <div key={m.machine_id} ref={(el) => { els.current[m.machine_id] = el; }}
        className={`floor-label ${show ? "show" : ""} ${m.machine_id === selected ? "on" : ""} ${v.alert ? "alert" : ""}`}>
        <b>{m.name}</b>
        <span>
          {v.health === null ? m.state : `${Math.round(v.health)}%`}
          {v.alert ? " · ALERT" : m.pending_plan_id ? " · PLAN WAITING" : ""}
        </span>
      </div>
    );
  });
  return (
    <Stage className="floor-canvas" camera={{ position: [0, 4.6, 6.2], fov: 42 }} overlay={overlay}>
      <PinLayer pins={pins} els={els} />
      <Studio rim={0.5} />
      <CameraGlide target={idx >= 0 ? pos[idx] : null} span={span} />
      <gridHelper args={[60, 60, "#1c1c1c", "#101010"]} position={[0, -0.17, 0]} />
      {fleet.map((m, i) => (
        <MiniMotor key={m.machine_id} m={m} pos={pos[i]} selected={m.machine_id === selected} onSelect={() => onSelect(m.machine_id)}
          onHover={(on) => setHovered((h) => (on ? m.machine_id : h === m.machine_id ? null : h))} />
      ))}
    </Stage>
  );
}
