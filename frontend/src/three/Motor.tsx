/**
 * A flour-mill induction motor with the SPANDAN sensor clipped on, built from simple shapes.
 * Shaft axis = x, drive end (pulley, the watched bearing, the sensor) at +x.
 *
 *  health   0–100: colour of the glow, LED and vibration rings
 *  xray     0–1:   casing fades to a wireframe and shows the drive-end bearing inside
 *  crack    0–1:   spall on the bearing's outer race
 *  shake    metres-ish amplitude; `mode` picks how it shakes (imbalance wobbles at 1×, looseness rattles,
 *           bearing wear buzzes)
 *  rings    0–1:   vibration ripples spreading from the sensor
 */
import { Billboard, RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { Bearing } from "./Bearing";
import { VOLT, healthTint, read, type Sig } from "./kit";

export type ShakeMode = "none" | "imbalance" | "looseness" | "bearing_outer";

export interface MotorProps {
  health?: Sig;
  xray?: Sig;
  crack?: Sig;
  shake?: Sig;
  mode?: Sig<ShakeMode>;
  spin?: Sig;
  rings?: Sig;
}

const BEARING_X = 0.95;
const SENSOR: [number, number, number] = [0.86, 0.99, 0];
const FINS = 22;

export function Motor({ health = 96, xray = 0, crack = 0, shake = 0, mode = "none", spin = 1.6, rings = 0 }: MotorProps) {
  const body = useRef<THREE.Group>(null!);
  const shaft = useRef<THREE.Group>(null!);
  const scan = useRef<THREE.Mesh>(null!);
  const glow = useRef<THREE.PointLight>(null!);
  const led = useRef<THREE.MeshStandardMaterial>(null!);
  const wire = useRef<THREE.MeshBasicMaterial>(null!);
  const ringRefs = useRef<(THREE.Mesh | null)[]>([]);
  const tint = useMemo(() => new THREE.Color(), []);

  const shell = useMemo(() => new THREE.MeshStandardMaterial({
    color: "#2b2f34", metalness: 0.75, roughness: 0.38, transparent: true,
  }), []);
  const dark = useMemo(() => new THREE.MeshStandardMaterial({ color: "#16181b", metalness: 0.6, roughness: 0.5, transparent: true }), []);
  const steel = useMemo(() => new THREE.MeshStandardMaterial({ color: "#9aa1a9", metalness: 1, roughness: 0.25 }), []);
  const ringGeo = useMemo(() => new THREE.RingGeometry(0.96, 1, 64), []);

  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime;
    const x = read(xray);
    const h = read(health);
    healthTint(h, tint);

    // casing → x-ray
    const op = 1 - 0.88 * Math.min(1, x / 0.97);
    shell.opacity = dark.opacity = op;
    shell.depthWrite = dark.depthWrite = op > 0.95;
    wire.current.opacity = 0.32 * x;
    wire.current.color.copy(tint);
    scan.current.visible = x > 0.02 && x < 0.97;
    scan.current.position.x = -1.1 + 2.2 * x;
    (scan.current.material as THREE.MeshBasicMaterial).opacity = Math.sin(Math.PI * x) * 0.9;

    // glow on the bearing, LED on the sensor
    glow.current.color.copy(tint);
    glow.current.intensity = 0.4 + 5 * x;
    led.current.emissive.copy(tint);
    led.current.emissiveIntensity = 1.5 + Math.sin(t * (h < 50 ? 9 : 3)) * 1.2;

    // shaft
    shaft.current.rotation.x += dt * read(spin);

    // shake, by fault type
    const a = read(shake);
    const m = read(mode);
    const b = body.current;
    if (m === "imbalance") {
      const w = t * Math.PI * 2 * 2.4;
      b.position.set(0, Math.sin(w) * a, Math.cos(w) * a);
      b.rotation.set(0, 0, 0);
    } else if (m === "looseness") {
      const kick = Math.sin(t * 11) > 0.6 ? 1 : 0;
      b.position.set(0, kick * a * 1.4, 0);
      b.rotation.set(0, 0, kick * a * 0.8 * (Math.random() - 0.3));
    } else {
      b.position.set((Math.random() - 0.5) * a * 0.5, (Math.random() - 0.5) * a, (Math.random() - 0.5) * a * 0.5);
      b.rotation.set(0, 0, 0);
    }

    // ripples from the sensor
    const r = read(rings);
    ringRefs.current.forEach((mesh, i) => {
      if (!mesh) return;
      const ph = (t * (0.5 + 0.6 * r) + i / 3) % 1;
      mesh.scale.setScalar(0.15 + ph * (1.2 + 1.6 * r));
      const mat = mesh.material as THREE.MeshBasicMaterial;
      mat.opacity = r * (1 - ph) * 0.85;
      mat.color.copy(tint);
      mesh.visible = r > 0.01;
    });
  });

  return (
    <group>
      <group ref={body}>
        {/* frame with cooling fins */}
        <mesh rotation-z={Math.PI / 2} material={shell}>
          <cylinderGeometry args={[0.9, 0.9, 2.2, 56]} />
        </mesh>
        {Array.from({ length: FINS }, (_, i) => {
          const a = (i / FINS) * Math.PI * 2;
          return (
            <mesh key={i} position={[0, Math.cos(a) * 0.95, Math.sin(a) * 0.95]} rotation-x={-a} material={shell}>
              <boxGeometry args={[2.05, 0.13, 0.035]} />
            </mesh>
          );
        })}
        {/* x-ray wireframe + scan ring */}
        <mesh rotation-z={Math.PI / 2}>
          <cylinderGeometry args={[0.97, 0.97, 2.3, 20, 6, true]} />
          <meshBasicMaterial ref={wire} wireframe transparent opacity={0} color={VOLT} depthWrite={false} />
        </mesh>
        <mesh ref={scan} rotation-y={Math.PI / 2}>
          <torusGeometry args={[1.0, 0.012, 8, 96]} />
          <meshBasicMaterial color={VOLT} transparent toneMapped={false} />
        </mesh>
        {/* end shields */}
        <mesh position={[1.12, 0, 0]} rotation-z={Math.PI / 2} material={dark}>
          <cylinderGeometry args={[0.94, 0.94, 0.14, 56]} />
        </mesh>
        <mesh position={[1.22, 0, 0]} rotation-z={Math.PI / 2} material={dark}>
          <cylinderGeometry args={[0.36, 0.5, 0.12, 40]} />
        </mesh>
        <mesh position={[-1.12, 0, 0]} rotation-z={Math.PI / 2} material={dark}>
          <cylinderGeometry args={[0.94, 0.94, 0.14, 56]} />
        </mesh>
        {/* fan cowl with grille */}
        <mesh position={[-1.46, 0, 0]} rotation-z={Math.PI / 2} material={dark}>
          <cylinderGeometry args={[0.86, 0.9, 0.55, 56]} />
        </mesh>
        {[0.25, 0.45, 0.65].map((r) => (
          <mesh key={r} position={[-1.745, 0, 0]} rotation-y={Math.PI / 2} material={steel}>
            <torusGeometry args={[r, 0.018, 8, 48]} />
          </mesh>
        ))}
        {/* terminal box + lifting eye */}
        <RoundedBox args={[0.6, 0.3, 0.56]} radius={0.04} position={[-0.25, 1.02, 0]} material={dark} />
        <mesh position={[0.25, 1.07, 0]} material={steel}>
          <torusGeometry args={[0.09, 0.025, 8, 24]} />
        </mesh>
        {/* base and feet */}
        <mesh position={[0, -1.08, 0]} material={dark}>
          <boxGeometry args={[2.5, 0.1, 1.6]} />
        </mesh>
        {[-0.75, 0.75].map((x) => (
          <mesh key={x} position={[x, -0.93, 0]} material={shell}>
            <boxGeometry args={[0.32, 0.24, 1.35]} />
          </mesh>
        ))}

        {/* the SPANDAN sensor: magnet + box + LED */}
        <group position={SENSOR}>
          <mesh position={[0, -0.02, 0]} material={steel}>
            <cylinderGeometry args={[0.15, 0.15, 0.05, 32]} />
          </mesh>
          <RoundedBox args={[0.36, 0.15, 0.26]} radius={0.035} position={[0, 0.08, 0]}>
            <meshStandardMaterial color="#0b0b0b" metalness={0.2} roughness={0.6} />
          </RoundedBox>
          <mesh position={[0.1, 0.165, 0.07]}>
            <sphereGeometry args={[0.028, 16, 12]} />
            <meshStandardMaterial ref={led} color="#111" emissive={VOLT} toneMapped={false} />
          </mesh>
          <mesh position={[-0.06, 0.158, 0]}>
            <boxGeometry args={[0.16, 0.004, 0.16]} />
            <meshStandardMaterial color="#ccff00" emissive="#ccff00" emissiveIntensity={0.4} />
          </mesh>
          {[0, 1, 2].map((i) => (
            <Billboard key={i} position={[0, 0.12, 0]}>
              <mesh ref={(m) => { ringRefs.current[i] = m; }} geometry={ringGeo}>
                <meshBasicMaterial transparent depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
              </mesh>
            </Billboard>
          ))}
        </group>

        {/* the watched bearing, inside the drive end */}
        <group position={[BEARING_X, 0, 0]} scale={0.6}>
          <Bearing spin={spin} damage={crack} />
        </group>
        <pointLight ref={glow} position={[BEARING_X, 0, 0]} distance={3.2} decay={2} />
      </group>

      {/* shaft + pulley (turns; does not shake with the frame for clarity) */}
      <group ref={shaft}>
        <mesh position={[1.62, 0, 0]} rotation-z={Math.PI / 2} material={steel}>
          <cylinderGeometry args={[0.11, 0.11, 0.9, 24]} />
        </mesh>
        <mesh position={[1.98, 0, 0]} rotation-z={Math.PI / 2}>
          <cylinderGeometry args={[0.44, 0.44, 0.34, 48]} />
          <meshStandardMaterial color="#5d636b" metalness={0.9} roughness={0.3} />
        </mesh>
        {[1.9, 2.06].map((x) => (
          <mesh key={x} position={[x, 0, 0]} rotation-y={Math.PI / 2}>
            <torusGeometry args={[0.44, 0.03, 8, 48]} />
            <meshStandardMaterial color="#2b2f34" metalness={0.6} roughness={0.5} />
          </mesh>
        ))}
        <mesh position={[2.16, 0.3, 0]}>
          <boxGeometry args={[0.02, 0.12, 0.06]} />
          <meshBasicMaterial color={VOLT} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}
