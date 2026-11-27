import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, Bell, CheckCircle2, CloudUpload, Info, Pause, Play, RotateCcw, Wifi, WifiOff, Wrench, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HealthRing, SpectrumChart, Waveform, healthColor, type Marker } from "../components/Charts";
import RepairPanel from "../components/RepairPanel";
import { api, session, type Machine, type Owner } from "../lib/api";
import { BASELINE_WINDOWS, Gateway, type GatewayState, type LogEntry } from "../lib/gateway";
import { BPFO_RATIO, FAULT_LABELS, type FaultType } from "../lib/signal";

const FAULTS: { id: FaultType; emoji: string }[] = [
  { id: "none", emoji: "OK" },
  { id: "bearing_outer", emoji: "BRG" },
  { id: "imbalance", emoji: "IMB" },
  { id: "looseness", emoji: "LSE" },
];

const LOG_ICON: Record<LogEntry["kind"], typeof Info> = {
  info: Info, alert: AlertTriangle, ok: CheckCircle2, sync: CloudUpload, error: XCircle,
};

export default function Monitor() {
  const ids = session.get();
  const [params, setParams] = useSearchParams();
  const [machine, setMachine] = useState<Machine | null>(null);
  const [owner, setOwner] = useState<Owner | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [state, setState] = useState<GatewayState | null>(null);
  const gwRef = useRef<Gateway | null>(null);

  useEffect(() => {
    if (!ids) return;
    let gw: Gateway | null = null;
    let unsub = () => {};
    let cancelled = false; // StrictMode runs effects twice; ignore the stale request
    api.getOwner(ids.ownerId).then((o) => !cancelled && setOwner(o)).catch(() => {});
    api.getMachine(ids.machineId).then((m) => {
      if (cancelled) return;
      setMachine(m);
      gw = new Gateway(m.id, m.motor_rpm ?? 2880, 1000);
      gwRef.current = gw;
      unsub = gw.subscribe(setState);
      if (params.get("start") === "baseline" || m.state === "setup") {
        void gw.startBaseline();
        setParams({}, { replace: true });
      } else if (!gw.resume()) {
        // No baseline on this device (new browser, or cleared): learn it again.
        void gw.startBaseline();
      }
    }).catch((e) => !cancelled && setLoadError((e as Error).message));
    return () => {
      cancelled = true;
      unsub();
      gw?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids?.machineId]);

  const markers = useMemo<Marker[]>(() => {
    const f1 = (state?.rpm ?? 2880) / 60;
    return [
      { f: f1, label: "1×", color: "#f2f2f2" },
      { f: 2 * f1, label: "2×", color: "#f2f2f2" },
    ];
  }, [state?.rpm]);
  const envMarkers = useMemo<Marker[]>(() => {
    const f1 = (state?.rpm ?? 2880) / 60;
    return [
      { f: BPFO_RATIO * f1, label: "BPFO", color: "#ff4d3d" },
      { f: 2 * BPFO_RATIO * f1, label: "2×BPFO", color: "#ff4d3d" },
    ];
  }, [state?.rpm]);

  if (!ids) {
    return (
      <div className="page center-page">
        <h1>No machine set up yet</h1>
        <p className="muted">Pair a machine first, then come back here to watch it live.</p>
        <Link to="/setup" className="btn btn-primary">Go to setup</Link>
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="page center-page">
        <h1>Couldn't load the machine</h1>
        <p className="error">{loadError}</p>
        <p className="muted">Is the backend running? If the database was reset, set the machine up again.</p>
        <button className="btn btn-ghost" onClick={() => { session.clear(); location.href = "/setup"; }}>Set up again</button>
      </div>
    );
  }
  if (!state || !machine) return <div className="page center-page"><div className="loader" /></div>;

  const gw = gwRef.current!;
  const learning = state.phase === "baseline";
  const status = learning ? "Learning normal vibration" : state.alertActive ? "Fault warning" : state.phase === "monitoring" ? "Running normally" : "Idle";
  const chartData = state.history.map((p, i) => ({ i, score: Number(p.score?.toFixed(2)), threshold: p.threshold }));

  return (
    <div className="page monitor">
      <header className="monitor-head">
        <div>
          <span className="kicker">Live monitor · simulated sensor</span>
          <h1>{machine.name}</h1>
          <p className="muted small">{machine.motor_rpm} RPM · bearing {machine.bearing_model} · 1 reading/second (stands for 1/minute)</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-ghost" onClick={() => (state.running ? gw.pause() : gw.start())}>
            {state.running ? <><Pause size={16} /> Pause</> : <><Play size={16} /> Resume</>}
          </button>
          <button className={`btn ${state.online ? "btn-ghost" : "btn-warn"}`} onClick={() => gw.setOnline(!state.online)}>
            {state.online ? <><Wifi size={16} /> Online</> : <><WifiOff size={16} /> Offline</>}
          </button>
          <button className="btn btn-ghost" onClick={() => void gw.startBaseline()} title="Re-learn normal vibration, e.g. after a repair">
            <RotateCcw size={16} /> Re-learn
          </button>
        </div>
      </header>

      <AnimatePresence>
        {state.alertActive && (
          <motion.div className="alert-banner" initial={{ opacity: 0, y: -20, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -20 }}>
            <Bell className="ring-bell" size={22} />
            <div>
              <strong>Unusual vibration on {machine.name}.</strong>{" "}
              Biggest changes: {state.contributors.map((c) => c.name.replace(/_/g, " ")).join(", ")}.
              <span className="muted"> Sent to the cloud: diagnosis and a repair plan appear below.</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="monitor-grid">
        <section className="card health-card">
          <HealthRing health={learning ? null : state.health} label={learning ? "learning…" : "machine health"} />
          <div className="status-chip" style={{ borderColor: learning ? "#f2f2f2" : healthColor(state.health), color: learning ? "#f2f2f2" : healthColor(state.health) }}>
            <span className="dot" style={{ background: "currentColor" }} /> {status}
          </div>
          {learning && (
            <div className="progress">
              <motion.div className="progress-bar" animate={{ width: `${state.baselineProgress * 100}%` }} />
              <span>{Math.round(state.baselineProgress * BASELINE_WINDOWS)} / {BASELINE_WINDOWS} readings</span>
            </div>
          )}
          <dl className="mini-stats">
            <div><dt>Anomaly score</dt><dd>{state.scoreValue?.toFixed(2) ?? "—"}</dd></div>
            <div><dt>Threshold</dt><dd>{state.baseline?.threshold.toFixed(2) ?? "—"}</dd></div>
            <div><dt>Speed</dt><dd>{Math.round(state.rpm)} rpm</dd></div>
            <div><dt>Readings</dt><dd>{state.windowCount}</dd></div>
          </dl>
        </section>

        <section className="card controls-card">
          <h2><Wrench size={18} /> Test the machine</h2>
          <p className="muted small">Inject a fault into the simulated motor and watch SPANDAN react.</p>
          <div className="fault-grid">
            {FAULTS.map((f) => (
              <motion.button key={f.id} whileTap={{ scale: 0.95 }} whileHover={{ y: -2 }} disabled={learning}
                className={`fault-btn ${state.fault === f.id ? "active" : ""}`} onClick={() => gw.injectFault(f.id, state.progressive)}>
                <span className="fault-emoji">{f.emoji}</span>
                {f.id === "none" ? "Healthy / repaired" : FAULT_LABELS[f.id]}
              </motion.button>
            ))}
          </div>
          <label className="toggle">
            <input type="checkbox" checked={state.progressive} onChange={(e) => gw.injectFault(state.fault, e.target.checked)} />
            Wear gets worse over time
          </label>
          {state.fault !== "none" && (
            <div className="severity">
              <span>Fault severity</span>
              <div className="sev-track"><motion.div className="sev-fill" animate={{ width: `${state.severity * 100}%` }} /></div>
              <span>{Math.round(state.severity * 100)}%</span>
            </div>
          )}
          {learning && <p className="hint">Faults unlock once the baseline is learned.</p>}
          <div className="sync-row">
            <CloudUpload size={16} />
            <span><b>{state.synced}</b> uploaded</span>
            <span><b>{state.queued}</b> waiting{!state.online && " (offline)"}</span>
            {state.duplicates > 0 && <span><b>{state.duplicates}</b> already stored</span>}
          </div>
        </section>

        {owner && (
          <RepairPanel machineId={machine.id} owner={owner}
            onRepaired={() => void gwRef.current?.afterRepair()}
            onFalseAlarm={(t, pct) => gwRef.current?.applyThreshold(t, pct)} />
        )}

        <section className="card chart-card wide">
          <div className="card-head"><h2>Anomaly score</h2><span className="legend"><i className="lg-score" /> score <i className="lg-thr" /> alert threshold</span></div>
          <div className="chart-box">
            {chartData.length === 0 ? (
              <div className="empty">{learning ? "Scores start once the baseline is learned." : "Waiting for readings…"}</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
                  <defs>
                    <linearGradient id="scoreFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0" stopColor="#ccff00" stopOpacity={0.45} />
                      <stop offset="1" stopColor="#ccff00" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1a1a1a" vertical={false} />
                  <XAxis dataKey="i" hide />
                  <YAxis scale="log" domain={[0.1, "auto"]} allowDataOverflow tick={{ fill: "#666", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }} />
                  <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #2a2a2a", borderRadius: 2, fontFamily: "JetBrains Mono, monospace", fontSize: 12 }} labelFormatter={() => ""} />
                  {state.baseline && <ReferenceLine y={state.baseline.threshold} stroke="#ff4d3d" strokeDasharray="6 4" />}
                  <Area type="monotone" dataKey="score" stroke="#ccff00" fill="url(#scoreFill)" strokeWidth={2} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </section>

        <section className="card chart-card">
          <div className="card-head"><h2>Vibration (radial axis)</h2><span className="muted small">0.2 s</span></div>
          <div className="chart-box short"><Waveform data={state.lastWave} /></div>
        </section>

        <section className="card chart-card">
          <div className="card-head"><h2>Spectrum</h2><span className="muted small">shaft 1× / 2×</span></div>
          <div className="chart-box short"><SpectrumChart spectrum={state.spectrum} maxHz={1600} markers={markers} /></div>
        </section>

        <section className="card chart-card">
          <div className="card-head"><h2>Envelope spectrum</h2><span className="muted small">bearing impacts</span></div>
          <div className="chart-box short"><SpectrumChart spectrum={state.envSpectrum} maxHz={500} markers={envMarkers} color="#e8e8e8" /></div>
        </section>

        <section className="card log-card">
          <h2>Events</h2>
          <ul className="log">
            <AnimatePresence initial={false}>
              {state.log.map((e) => {
                const Icon = LOG_ICON[e.kind];
                return (
                  <motion.li key={e.id} className={`log-${e.kind}`} layout initial={{ opacity: 0, x: -20, height: 0 }} animate={{ opacity: 1, x: 0, height: "auto" }} exit={{ opacity: 0 }}>
                    <Icon size={15} />
                    <span className="log-time">{e.at.toLocaleTimeString()}</span>
                    <span>{e.text}</span>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        </section>
      </div>
    </div>
  );
}
