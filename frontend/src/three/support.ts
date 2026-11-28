/**
 * Should this device get the WebGL scenes? Mill owners use cheap phones, so 3D is opt-out by default on
 * weak hardware and for anyone who asked the OS for less motion. Everything 3D has a 2D fallback.
 * Override for testing: ?3d=on or ?3d=off.
 */
let cached: boolean | null = null;

export function can3D(): boolean {
  if (cached !== null) return cached;
  cached = detect();
  return cached;
}

function detect(): boolean {
  if (typeof window === "undefined") return false;
  const forced = new URLSearchParams(window.location.search).get("3d");
  if (forced === "on") return hasWebGL();
  if (forced === "off") return false;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
  const nav = navigator as Navigator & { deviceMemory?: number };
  if (nav.deviceMemory !== undefined && nav.deviceMemory < 4) return false;
  if (nav.hardwareConcurrency !== undefined && nav.hardwareConcurrency <= 2) return false;
  return hasWebGL();
}

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}
