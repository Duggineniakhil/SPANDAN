import { useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { fitBaseline, healthIndex, score, type Baseline } from "../lib/detector";
import { extractFeatures, type Spectrum } from "../lib/features";
import { BPFO_RATIO, generateWindow, makeRng } from "../lib/signal";
import { SpectrumChart, Waveform } from "./Charts";

const RPM = 2880;
const CYCLE = 36; // readings per demo cycle: healthy → worn → repaired

/** Landing-page demo: the real detection pipeline running on a simulated bearing that wears out. */
export function LiveSignal() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-100px" });
  const baseline = useRef<Baseline | null>(null);
  const step = useRef(0);
  const [view, setView] = useState<{ wave: Float64Array; env: Spectrum; health: number; severity: number; kurt: number } | null>(null);

  useEffect(() => {
    if (!inView) return;
    if (!baseline.current) {
      const rng = makeRng(7);
      baseline.current = fitBaseline(
        Array.from({ length: 24 }, () => extractFeatures(generateWindow("none", 0, RPM, rng)).features),
      );
    }
    const tick = () => {
      const i = step.current++ % CYCLE;
      // wear from 5 % to 25 %: where health moves from normal through early wear to fault
      const severity = i < 8 ? 0 : i < 30 ? 0.05 + ((i - 8) / 22) * 0.2 : 0;
      const w = generateWindow(severity > 0 ? "bearing_outer" : "none", severity, RPM);
      const { features, envSpectrum } = extractFeatures(w);
      const h = Math.round(healthIndex(baseline.current!, score(baseline.current!, features)));
      setView({ wave: w.y.subarray(0, 480), env: envSpectrum, health: h, severity, kurt: features.kurtosis_y });
    };
    tick();
    const t = setInterval(tick, 700);
    return () => clearInterval(t);
  }, [inView]);

  const bpfo = (BPFO_RATIO * RPM) / 60;
  const state = !view ? "—" : view.health >= 70 ? "NORMAL" : view.health >= 40 ? "EARLY WEAR" : "FAULT · PLAN REPAIR";

  return (
    <div ref={ref} className="live">
      <div className="live-head">
        <div className="live-readout">
          <span className="mono dim">HEALTH</span>
          <span className={`live-health ${view && view.health < 40 ? "bad" : ""}`}>{view ? view.health : "—"}<small>%</small></span>
        </div>
        <div className="live-meta mono">
          <span><i className="dot-volt" /> {state}</span>
          <span>KURTOSIS {view ? view.kurt.toFixed(2) : "—"}</span>
          <span>WEAR {view ? Math.round(view.severity * 100) : 0}%</span>
        </div>
      </div>
      <div className="live-panels">
        <div className="live-panel">
          <span className="panel-label mono">VIBRATION · RADIAL · 150 ms</span>
          <div className="panel-chart"><Waveform data={view?.wave ?? null} color="#e8e8e8" /></div>
        </div>
        <div className="live-panel">
          <span className="panel-label mono">ENVELOPE SPECTRUM · 0–500 Hz</span>
          <div className="panel-chart">
            <SpectrumChart spectrum={view?.env ?? null} maxHz={500} color="#ccff00"
              markers={[{ f: bpfo, label: "BPFO", color: "#ffffff" }, { f: 2 * bpfo, label: "2×", color: "#ffffff" }]} />
          </div>
        </div>
      </div>
    </div>
  );
}
