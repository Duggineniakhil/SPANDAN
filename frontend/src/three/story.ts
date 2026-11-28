/**
 * The landing page's scroll story as plain functions of scroll progress p (0–1), shared by the 3D scene
 * and the HTML captions so the numbers on screen always match the model.
 */
import { smooth } from "./math";

export const STAGES = [
  { from: 0.0, to: 0.13, key: "title" },
  { from: 0.13, to: 0.3, key: "sense" },
  { from: 0.3, to: 0.49, key: "wear" },
  { from: 0.49, to: 0.68, key: "detect" },
  { from: 0.68, to: 0.86, key: "plan" },
  { from: 0.86, to: 1, key: "fixed" },
] as const;

export const xrayAt = (p: number) => smooth(0.2, 0.34, p) * (1 - smooth(0.84, 0.92, p));
export const crackAt = (p: number) => smooth(0.4, 0.6, p) * (1 - smooth(0.86, 0.9, p));
export const healthAt = (p: number) => Math.round(96 - 55 * smooth(0.32, 0.66, p) + 56 * smooth(0.86, 0.94, p));
export const ringsAt = (p: number) => smooth(0.44, 0.54, p) * (1 - smooth(0.8, 0.88, p));
export const shakeAt = (p: number) => 0.002 + 0.028 * crackAt(p);

type V3 = [number, number, number];
/** camera keyframes: [p, position, look-at] */
const CAM: [number, V3, V3][] = [
  [0.0, [6.4, 2.9, 7.6], [0.2, 1.05, 0]],
  [0.1, [6.0, 2.6, 7.0], [0.2, 0.8, 0]],
  [0.2, [4.1, 1.7, 4.7], [0.2, 0, 0]],
  [0.36, [3.0, 1.05, 3.4], [0.5, 0, 0]],
  [0.56, [2.45, 1.05, 1.75], [0.95, 0.22, 0]],
  [0.66, [2.15, 0.85, 1.3], [0.95, 0.28, 0]],
  [0.8, [3.6, 1.5, 4.0], [0.4, 0, 0]],
  [1.0, [5.4, 2.5, 6.2], [0.1, -0.15, 0]],
];

export function cameraAt(p: number, pos: V3, look: V3): void {
  let i = 0;
  while (i < CAM.length - 2 && p > CAM[i + 1][0]) i++;
  const [p0, a0, l0] = CAM[i];
  const [p1, a1, l1] = CAM[i + 1];
  const t = smooth(p0, p1, p);
  for (let k = 0; k < 3; k++) {
    pos[k] = a0[k] + (a1[k] - a0[k]) * t;
    look[k] = l0[k] + (l1[k] - l0[k]) * t;
  }
}
