/**
 * Monitor page: a live 3D twin of the motor, driven by the same gateway state as the charts.
 * Healthy → calm and volt; a fault shakes it the way that fault really shakes a motor (imbalance wobbles at
 * 1×, looseness rattles, bearing wear buzzes) and the casing goes x-ray to show the damaged bearing.
 * Drag to turn it.
 */
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { useRef } from "react";
import { Motor, type ShakeMode } from "./Motor";
import { Stage, Studio } from "./kit";

export interface TwinState {
  health: number | null;
  fault: ShakeMode;
  severity: number;
  rpm: number;
  running: boolean;
  alert: boolean;
}

export default function MotorTwin(props: TwinState) {
  // the scene reads the latest props every frame without re-rendering
  const s = useRef(props);
  s.current = props;
  const h = () => s.current.health ?? 96;
  const sev = () => (s.current.fault === "none" ? 0 : s.current.severity);
  // x-ray eases in and out, so the scan ring sweeps the casing once and then hides
  const xr = useRef({ v: 0, t: 0 });
  const xray = () => {
    const now = performance.now();
    const dt = xr.current.t ? Math.min(0.1, (now - xr.current.t) / 1000) : 0;
    xr.current.t = now;
    const target = s.current.alert || sev() > 0.25 ? 1 : 0;
    xr.current.v += (target - xr.current.v) * Math.min(1, dt * 1.6);
    return xr.current.v;
  };
  return (
    <Stage className="twin-canvas" camera={{ position: [4.2, 2.3, 4.6], fov: 34 }}>
      <Studio rim={0.7} />
      <group position={[-0.25, 0.1, 0]} scale={0.95}>
        <Motor
          health={h}
          xray={xray}
          crack={() => (s.current.fault === "bearing_outer" ? Math.min(1, sev() * 1.4) : 0)}
          shake={() => (s.current.running ? 0.0015 + 0.05 * sev() * (s.current.fault === "looseness" ? 0.8 : 1) : 0)}
          mode={() => s.current.fault}
          rings={() => (s.current.running ? (s.current.alert ? 1 : 0.25) : 0)}
          spin={() => (s.current.running ? (1.4 * s.current.rpm) / 2880 : 0)}
        />
      </group>
      <ContactShadows position={[0, -1.06, 0]} opacity={0.55} scale={8} blur={2.4} far={2.5} />
      <gridHelper args={[20, 40, "#1f1f1f", "#131313"]} position={[0, -1.055, 0]} />
      <OrbitControls enableZoom={false} enablePan={false} minPolarAngle={0.6} maxPolarAngle={1.45} autoRotate autoRotateSpeed={0.5} />
    </Stage>
  );
}
