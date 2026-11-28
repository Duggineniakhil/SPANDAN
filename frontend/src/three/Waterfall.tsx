/**
 * Monitor page: the vibration spectrum over time as a 3D surface ("waterfall"). Frequency runs left → right,
 * the newest reading is at the front and older ones slide back, height and colour are loudness (log scale).
 * A fault shows up as a ridge that grows along its frequency.
 */
import { OrbitControls } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { Spectrum } from "../lib/features";
import { PinLayer, Stage, type Pin } from "./kit";

const COLS = 128;
const ROWS = 48;
const WIDTH = 6;
const DEPTH = 4.2;
const HEIGHT = 1.6;

const C_LOW = new THREE.Color("#0c0f06");
const C_MID = new THREE.Color("#5c7a00");
const C_HIGH = new THREE.Color("#ccff00");
const C_PEAK = new THREE.Color("#ffffff");

function colorFor(v: number, out: THREE.Color) {
  if (v < 0.35) return out.copy(C_LOW).lerp(C_MID, v / 0.35);
  if (v < 0.75) return out.copy(C_MID).lerp(C_HIGH, (v - 0.35) / 0.4);
  return out.copy(C_HIGH).lerp(C_PEAK, (v - 0.75) / 0.25);
}

/** One spectrum → COLS values in 0..1: max in each band, in dB, showing the loudest RANGE_DB below a slow
 * running peak (so the noise floor stays flat and a growing fault stands up instead of being rescaled away). */
const RANGE_DB = 44;
const MIN_HZ = 20; // skip DC and the lowest bins, which dwarf everything else

function toRow(s: Spectrum, maxHz: number, ref: { level: number }): Float32Array {
  const amp = new Float32Array(COLS);
  const band = maxHz / COLS;
  for (let i = 0; i < s.freqs.length; i++) {
    const f = s.freqs[i];
    if (f < MIN_HZ) continue;
    if (f >= maxHz) break;
    const c = Math.floor(f / band);
    amp[c] = Math.max(amp[c], s.amp[i]);
  }
  const row = new Float32Array(COLS);
  let peak = -Infinity;
  for (let c = 0; c < COLS; c++) {
    row[c] = 20 * Math.log10(amp[c] + 1e-9);
    peak = Math.max(peak, row[c]);
  }
  ref.level = ref.level === 0 ? peak : Math.max(peak, ref.level - 0.05);
  for (let c = 0; c < COLS; c++) row[c] = Math.min(1, Math.max(0, (row[c] - (ref.level - RANGE_DB)) / RANGE_DB));
  return row;
}

function Surface({ spectrum, maxHz }: { spectrum: Spectrum | null; maxHz: number }) {
  const rows = useRef<Float32Array[]>([]);
  const ref = useRef({ level: 0 });
  const dirty = useRef(false);
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(WIDTH, DEPTH, COLS - 1, ROWS - 1);
    g.rotateX(-Math.PI / 2);
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(COLS * ROWS * 3), 3));
    return g;
  }, []);

  useEffect(() => {
    if (!spectrum) return;
    rows.current.unshift(toRow(spectrum, maxHz, ref.current));
    if (rows.current.length > ROWS) rows.current.length = ROWS;
    dirty.current = true;
  }, [spectrum, maxHz]);

  const tmp = useMemo(() => new THREE.Color(), []);
  useFrame(() => {
    if (!dirty.current) return;
    dirty.current = false;
    const pos = geo.attributes.position as THREE.BufferAttribute;
    const col = geo.attributes.color as THREE.BufferAttribute;
    // plane rows go back → front (row 0 = far edge); newest spectrum is the front edge
    for (let r = 0; r < ROWS; r++) {
      const data = rows.current[ROWS - 1 - r];
      for (let c = 0; c < COLS; c++) {
        const v = data ? data[c] : 0;
        const i = r * COLS + c;
        pos.setY(i, v * HEIGHT);
        colorFor(v, tmp);
        const fade = 0.35 + 0.65 * (r / (ROWS - 1)); // older rows dimmer
        col.setXYZ(i, tmp.r * fade, tmp.g * fade, tmp.b * fade);
      }
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
  });

  return (
    <group position={[0, Y0, 0]}>
      <mesh geometry={geo}>
        <meshBasicMaterial vertexColors side={THREE.DoubleSide} transparent opacity={0.92} />
      </mesh>
      <mesh geometry={geo} position-y={0.002}>
        <meshBasicMaterial color="#000" wireframe transparent opacity={0.3} />
      </mesh>
    </group>
  );
}

const Y0 = 0.05; // the surface group's height

export default function Waterfall({ spectrum, maxHz = 1600 }: { spectrum: Spectrum | null; maxHz?: number }) {
  const els = useRef<Record<string, HTMLElement | null>>({});
  const { pins, labels } = useMemo(() => {
    const step = maxHz <= 600 ? 100 : 400;
    const ticks = Array.from({ length: Math.floor(maxHz / step) + 1 }, (_, i) => i * step);
    const list: (Pin & { text: string; cls?: string })[] = ticks.map((f) => ({
      key: `f${f}`, text: `${f} Hz`, at: [-WIDTH / 2 + (f / maxHz) * WIDTH, Y0, DEPTH / 2 + 0.22],
    }));
    list.push({ key: "now", text: "now", cls: "volt", at: [WIDTH / 2 + 0.45, Y0, DEPTH / 2] });
    list.push({ key: "old", text: `${ROWS} readings ago`, at: [WIDTH / 2 + 0.75, Y0, -DEPTH / 2] });
    return { pins: { current: list as Pin[] }, labels: list };
  }, [maxHz]);
  const overlay = labels.map((l) => (
    <span key={l.key} ref={(el) => { els.current[l.key] = el; }} className={`wf-tick ${l.cls ?? ""}`}>{l.text}</span>
  ));
  return (
    <Stage className="waterfall-canvas" camera={{ position: [0, 3.0, 5.6], fov: 40 }} overlay={overlay}>
      <PinLayer pins={pins} els={els} />
      <Surface spectrum={spectrum} maxHz={maxHz} />
      <OrbitControls enableZoom={false} enablePan={false} minPolarAngle={0.5} maxPolarAngle={1.35}
        minAzimuthAngle={-0.9} maxAzimuthAngle={0.9} />
    </Stage>
  );
}
