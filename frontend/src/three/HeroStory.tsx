/** Landing hero (3D): the motor wears out, is caught, planned and repaired as you scroll. */
import { ContactShadows, Sparkles } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import type { MotionValue } from "framer-motion";
import { useRef } from "react";
import * as THREE from "three";
import { Motor } from "./Motor";
import { Stage, Studio } from "./kit";
import { cameraAt, crackAt, healthAt, ringsAt, shakeAt, xrayAt } from "./story";

function Rig({ progress }: { progress: MotionValue<number> }) {
  const p = useRef(progress.get());
  const turn = useRef<THREE.Group>(null!);
  const pos = useRef<[number, number, number]>([0, 0, 0]);
  const look = useRef<[number, number, number]>([0, 0, 0]);
  const lookV = useRef(new THREE.Vector3());
  const { camera, size, pointer } = useThree();

  useFrame((_, dt) => {
    // ease toward the scroll position: smooth, cinematic, still tied to the scrollbar
    p.current += (progress.get() - p.current) * Math.min(1, dt * 5);
    cameraAt(p.current, pos.current, look.current);
    const far = size.width / size.height < 1 ? 1.7 : size.width < 900 ? 1.25 : 1; // portrait screens: step back
    camera.position.set(
      pos.current[0] * far + pointer.x * 0.25, pos.current[1] * far + pointer.y * 0.15, pos.current[2] * far,
    );
    lookV.current.set(...look.current);
    camera.lookAt(lookV.current);
    turn.current.rotation.y = 0.35 - p.current * 0.5;
  });

  const at = (f: (p: number) => number) => () => f(p.current);
  return (
    <>
      <Studio rim={0.7} />
      <group ref={turn}>
        <Motor health={at(healthAt)} xray={at(xrayAt)} crack={at(crackAt)} shake={at(shakeAt)}
          mode="bearing_outer" rings={at(ringsAt)} spin={() => 2.2 - 1.2 * crackAt(p.current)} />
      </group>
      <ContactShadows position={[0, -1.14, 0]} opacity={0.6} scale={9} blur={2.6} far={2.5} />
      <gridHelper args={[40, 80, "#1f1f1f", "#121212"]} position={[0, -1.135, 0]} />
      <Sparkles count={90} scale={[9, 4, 9]} size={1.6} speed={0.25} opacity={0.35} color="#f2f2f2" />
    </>
  );
}

export default function HeroStory({ progress }: { progress: MotionValue<number> }) {
  return (
    <Stage className="story-canvas" camera={{ position: [4.9, 2.2, 5.8], fov: 34 }}>
      <Rig progress={progress} />
    </Stage>
  );
}
