/** Plain helpers with no three.js import, safe for the main bundle. */

/** A value that may change every frame without re-rendering React. */
export type Sig<T = number> = T | (() => T);
export const read = <T,>(s: Sig<T>): T => (typeof s === "function" ? (s as () => T)() : s);

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const smooth = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
