import { describe, expect, it } from "vitest";
import { AlertRule, fitBaseline, healthIndex, score } from "./detector";
import { extractFeatures, moment, rms } from "./features";
import { fft } from "./fft";
import { FS, generateWindow, makeRng, type FaultType } from "./signal";

describe("fft", () => {
  it("puts a pure tone in the right bin", () => {
    const n = 1024;
    const re = new Float64Array(n);
    const im = new Float64Array(n);
    for (let i = 0; i < n; i++) re[i] = Math.sin((2 * Math.PI * 50 * i) / n);
    fft(re, im);
    const mags = Array.from(re.slice(0, n / 2), (r, k) => Math.hypot(r, im[k]));
    expect(mags.indexOf(Math.max(...mags))).toBe(50);
  });
});

describe("statistics", () => {
  it("rms of a sine is amplitude / √2", () => {
    const a = Float64Array.from({ length: FS }, (_, i) => Math.sin((2 * Math.PI * 10 * i) / FS));
    expect(rms(a)).toBeCloseTo(Math.SQRT1_2, 3);
  });

  it("gaussian noise has kurtosis ≈ 3", () => {
    const w = generateWindow("none", 0, 2880, makeRng(1));
    expect(moment(w.z, 4)).toBeGreaterThan(2.5);
    expect(moment(w.z, 4)).toBeLessThan(3.6);
  });
});

describe("features", () => {
  it("estimates shaft speed from the 1× peak", () => {
    const { rpmEstimate } = extractFeatures(generateWindow("none", 0, 2880, makeRng(2)));
    expect(Math.abs(rpmEstimate - 2880)).toBeLessThan(60);
  });

  it("bearing wear raises kurtosis and the BPFO envelope line", () => {
    const healthy = extractFeatures(generateWindow("none", 0, 2880, makeRng(3))).features;
    const worn = extractFeatures(generateWindow("bearing_outer", 0.7, 2880, makeRng(3))).features;
    expect(worn.kurtosis_y).toBeGreaterThan(healthy.kurtosis_y + 1);
    expect(worn.env_bpfo_y).toBeGreaterThan(3 * healthy.env_bpfo_y);
  });

  it("imbalance raises the 1× amplitude", () => {
    const healthy = extractFeatures(generateWindow("none", 0, 2880, makeRng(4))).features;
    const imb = extractFeatures(generateWindow("imbalance", 0.6, 2880, makeRng(4))).features;
    expect(imb.amp_1x_y).toBeGreaterThan(3 * healthy.amp_1x_y);
  });
});

describe("detector", () => {
  const rng = makeRng(42);
  const baseline = fitBaseline(
    Array.from({ length: 30 }, () => extractFeatures(generateWindow("none", 0, 2880, rng)).features),
  );

  it("rarely flags healthy windows", () => {
    const scores = Array.from({ length: 60 }, () =>
      score(baseline, extractFeatures(generateWindow("none", 0, 2880, rng)).features),
    );
    const falseAlarms = scores.filter((s) => s > baseline.threshold).length;
    expect(falseAlarms).toBeLessThanOrEqual(1);
    expect(healthIndex(baseline, scores[0])).toBeGreaterThan(70);
  });

  it.each<FaultType>(["bearing_outer", "imbalance", "looseness"])("detects %s at moderate severity", (fault) => {
    const rule = new AlertRule(3);
    let raised = false;
    for (let i = 0; i < 5; i++) {
      const s = score(baseline, extractFeatures(generateWindow(fault, 0.5, 2880, rng)).features);
      raised = rule.update(s, baseline.threshold) === "raised" || raised;
    }
    expect(raised).toBe(true);
  });

  it("does not flag very early wear as a failure", () => {
    const s = score(baseline, extractFeatures(generateWindow("bearing_outer", 0.02, 2880, rng)).features);
    expect(healthIndex(baseline, s)).toBeGreaterThan(40);
  });
});
