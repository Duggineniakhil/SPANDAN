/**
 * Judge dashboard (M2-35, doc 01 F-dashboard): every machine at a glance, then one machine's health
 * chart, diagnosis with evidence, alerts, the step-by-step timeline of an alert (who did what: device,
 * system, agent, owner, mechanic) and the raw audit log. Read-only; refreshes every few seconds.
 */
import { Activity, AlertTriangle, Bot, Cpu, Mic, RefreshCw, User, Wrench } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { healthColor } from "../components/Charts";
import {
  api, type AnomalyEvent, type AuditEntry, type EventDetail, type FleetMachine, type Stats, type TelemetryPoint,
} from "../lib/api";

const REFRESH_MS = 5000;

const FAULT: Record<string, string> = {
  bearing_outer: "Bearing outer race", bearing_inner: "Bearing inner race", bearing_ball: "Bearing ball",
  imbalance: "Imbalance", looseness: "Looseness", misalignment: "Misalignment", unknown: "Unclear",
};
const fault = (f: string | null | undefined) => (f ? FAULT[f] ?? f : "—");

/** Human wording for audit actions; `null` = noise that the alert timeline leaves out. */
function describe(a: AuditEntry): string | null {
  const d = a.details as Record<string, any>;
  const top = (faults: any) => (Array.isArray(faults) && faults[0] ? `${fault(faults[0].fault)} ${Math.round(faults[0].confidence * 100)}%` : "");
  switch (a.action) {
    case "anomaly_event_opened": return `Alert raised by the ${d.source === "server" ? "cloud's backup rule" : "phone"} (score ${Number(d.peak_score ?? 0).toFixed(1)})`;
    case "event_diagnosed": return `Diagnosed: ${top(d.faults)}`;
    case "event_rediagnosed": return `Diagnosed again from fresh windows: ${top(d.faults)}`;
    case "rul_updated": return `Days left updated: ${d.to}${d.low != null ? ` (${Number(d.low).toFixed(1)}–${d.high != null ? Number(d.high).toFixed(1) : "?"} d)` : ""}`;
    case "agent_started": return `Agent started (${String(d.provider ?? "").split(":")[0]})${d.owner_request ? `, owner asked: “${d.owner_request}”` : ""}`;
    case "agent_provider_failed": return `Agent provider failed, falling back (${String(d.provider ?? "").split(":")[0]})`;
    case "agent_skipped": return `Agent skipped: ${d.reason}`;
    case "agent_stopped": return `Agent stopped: ${d.reason}`;
    case "agent_failed": return `Agent could not plan: ${d.reason}`;
    case "plan_submitted": return `Plan submitted (${d.tool_calls} tool calls)`;
    case "plan_pending": return `Plan passed the rules: ₹${d.total_cost_inr}, waiting for the owner`;
    case "plan_approved": return `Owner approved by ${d.channel}${d.transcript ? `: “${d.transcript}”` : ""}`;
    case "plan_rejected": return `Owner rejected by ${d.channel}`;
    case "plan_expired": return "Plan expired (no reply in 48 h)";
    case "plan_cancelled": return `Plan cancelled: ${d.reason}${d.request ? ` (“${d.request}”)` : ""}`;
    case "plan_executed": return "Plan executed in the sandbox";
    case "plan_reminder_sent": return "24 h reminder sent to the owner";
    case "mechanic_booked": return `Mechanic booked, ₹${d.rate_inr}`;
    case "dealer_order_confirmed": return `Part ordered: ${d.qty} × ${d.part_code}, ₹${d.price_inr}, paid at pickup by the owner`;
    case "downtime_scheduled": return "Downtime scheduled";
    case "slot_released": return "Mechanic slot released";
    case "decision_refused": return `Decision refused: ${d.reason}`;
    case "voice_note_ready": return "Voice note ready";
    case "voice_note_failed": return "Voice note failed: owner sees the text";
    case "voice_reply": return `Owner spoke: “${d.transcript}” → ${d.intent} (${d.source})`;
    case "voice_stt_failed": return "Could not transcribe the owner's reply";
    case "job_card_submitted": return `Job card: ${fault(d.actual_fault)}${d.diagnosis_correct === true ? " (diagnosis right)" : d.diagnosis_correct === false ? ` (diagnosis said ${fault(d.predicted_fault)})` : ""}`;
    case "job_card_refused": return `Job card refused: ${d.reason}`;
    case "event_resolved": return "Alert resolved";
    case "false_alarm_marked": return `Owner: false alarm (threshold +${d.raise_pct}%)`;
    case "false_alarm_refused": return `False alarm refused: ${d.reason}`;
    case "baseline_started": return `New baseline started${d.reason ? `: ${d.reason}` : ""}`;
    case "baseline_completed": return `Baseline learned (threshold ${Number(d.anomaly_threshold).toFixed(2)})`;
    default:
      if (a.action.startsWith("tool:")) return d.error ? `Agent tool ${a.action.slice(5)} → error` : `Agent: ${a.action.slice(5).replace(/_/g, " ")}`;
      return null;
  }
}

const ACTOR_ICON: Record<string, ReactNode> = {
  device: <Cpu size={13} />, system: <Activity size={13} />, agent: <Bot size={13} />,
  owner: <User size={13} />, mechanic: <Wrench size={13} />, operator: <User size={13} />,
};

const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const ago = (iso: string | null) => {
  if (!iso) return "never";
  const m = (Date.now() - new Date(iso).getTime()) / 60000;
  return m < 1 ? "just now" : m < 60 ? `${Math.round(m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
};

export default function Dashboard() {
  const [params, setParams] = useSearchParams();
  const [fleet, setFleet] = useState<FleetMachine[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const selected = params.get("machine") ?? fleet.find((m) => m.open_event_id)?.machine_id ?? fleet[0]?.machine_id ?? null;

  const refresh = useCallback(async () => {
    try {
      const [f, s] = await Promise.all([api.fleet(), api.stats()]);
      setFleet(f);
      setStats(s);
      setError(null);
      setTick((t) => t + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <main className="page dash">
      <header className="dash-head">
        <div>
          <span className="kicker">Judge dashboard</span>
          <h1>Every machine, every decision</h1>
        </div>
        <span className="muted small"><RefreshCw size={13} className={tick % 2 ? "spin-once" : ""} /> live · every {REFRESH_MS / 1000} s</span>
      </header>
      {error && <p className="error small">Backend: {error}</p>}
      {stats && <Kpis s={stats} />}
      <div className="dash-grid">
        <Fleet fleet={fleet} selected={selected} onSelect={(id) => setParams({ machine: id })} />
        {selected ? <MachineView key={selected} machineId={selected} tick={tick}
          info={fleet.find((m) => m.machine_id === selected)} /> : <p className="muted">No machines yet.</p>}
      </div>
    </main>
  );
}

function Kpis({ s }: { s: Stats }) {
  const items: [string, string, string?][] = [
    ["Machines", `${s.machines}`, `${s.monitoring} monitoring`],
    ["Open alerts", `${s.open_alerts}`, `${s.alerts_total} in total`],
    ["Waiting for owner", `${s.plans_pending}`, "plans"],
    ["Repairs", `${s.repairs_booked}`, `${s.repairs_done} done`],
    ["Diagnosis right", s.diagnosis_checked ? `${s.diagnosis_correct}/${s.diagnosis_checked}` : "—", "per job cards"],
    ["Alert → plan", s.alert_to_plan_median_s != null ? `${Math.round(s.alert_to_plan_median_s)} s` : "—", "median"],
    ["Owner replies", `${s.voice_decisions + s.tap_decisions}`, `${s.voice_decisions} by voice`],
    ["False alarms", `${s.false_alarms}`, "marked by owners"],
  ];
  return (
    <section className="kpis">
      {items.map(([label, value, sub]) => (
        <div key={label} className="kpi"><span className="kicker">{label}</span><b>{value}</b><em className="muted small">{sub}</em></div>
      ))}
    </section>
  );
}

function Fleet({ fleet, selected, onSelect }: { fleet: FleetMachine[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <section className="card fleet">
      <div className="card-head"><h2>Machines</h2><span className="muted small">{fleet.length}</span></div>
      <ul>
        {fleet.map((m) => (
          <li key={m.machine_id}>
            <button className={`fleet-row ${m.machine_id === selected ? "active" : ""}`} onClick={() => onSelect(m.machine_id)}>
              <span className="fleet-health" style={{ color: healthColor(m.health_index) }}>
                {m.health_index != null ? Math.round(m.health_index) : "—"}
              </span>
              <span className="fleet-name">
                <b>{m.name}</b>
                <em className="muted small">{m.owner_name} · {m.owner_language.toUpperCase()} · {m.state} · {ago(m.last_ts)}</em>
                {m.open_event_id && (
                  <em className="fleet-alert small"><AlertTriangle size={12} /> {fault(m.top_fault)}
                    {m.pending_plan_id ? " · plan waiting" : m.open_event_status === "planned" ? " · booked" : ""}</em>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MachineView({ machineId, tick, info }: { machineId: string; tick: number; info?: FleetMachine }) {
  const [points, setPoints] = useState<TelemetryPoint[]>([]);
  const [events, setEvents] = useState<AnomalyEvent[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [eventId, setEventId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [actor, setActor] = useState("all");

  useEffect(() => {
    let stale = false;
    void Promise.all([api.telemetry(machineId), api.events(machineId), api.audit(machineId)]).then(([t, e, a]) => {
      if (stale) return;
      setPoints(t.points);
      setEvents(e);
      setAudit(a);
    }).catch(() => undefined);
    return () => { stale = true; };
  }, [machineId, tick]);

  const current = eventId ?? events[0]?.id ?? null;
  useEffect(() => {
    if (!current) return setDetail(null);
    let stale = false;
    void api.getEvent(current).then((d) => !stale && setDetail(d)).catch(() => undefined);
    return () => { stale = true; };
  }, [current, tick]);

  const chart = useMemo(() => points.map((p) => ({
    t: new Date(p.ts).getTime(), health: p.health_index, score: p.anomaly_score,
  })), [points]);

  // The selected alert's story: entries about the event, its plans, jobs and quotes.
  const timeline = useMemo(() => {
    if (!detail) return [];
    const ids = new Set([detail.id, ...detail.plans.map((p) => p.id), ...detail.jobs.map((j) => j.id)]);
    const plans = new Set(detail.plans.map((p) => p.id));
    const start = new Date(detail.created_at).getTime() - 1000;
    return audit
      .filter((a) => (a.entity_id && ids.has(a.entity_id)) || plans.has(String((a.details as any).plan_id ?? ""))
        || (a.entity === "machine" && a.action === "baseline_started" && new Date(a.ts).getTime() >= start))
      .map((a) => ({ a, text: describe(a) }))
      .filter((x): x is { a: AuditEntry; text: string } => x.text !== null)
      .sort((x, y) => new Date(x.a.ts).getTime() - new Date(y.a.ts).getTime() || x.a.id - y.a.id);
  }, [audit, detail]);

  const shownAudit = audit.filter((a) => actor === "all" || a.actor === actor).slice(0, 120);
  const d = detail?.diagnosis;

  return (
    <div className="machine-view">
      <section className="card">
        <div className="card-head">
          <h2>{info?.name ?? "Machine"}</h2>
          <span className="legend"><i className="lg-health" /> health <i className="lg-score" /> anomaly score <i className="lg-thr" /> threshold</span>
        </div>
        <div className="chart-box">
          {chart.length === 0 ? <div className="empty">No readings in the last 24 h.</div> : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chart} margin={{ top: 6, right: 6, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#1c1c1c" vertical={false} />
                <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time"
                  tickFormatter={(v) => new Date(v).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })}
                  tick={{ fill: "#666", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }} />
                <YAxis yAxisId="h" domain={[0, 100]} tick={{ fill: "#666", fontSize: 10 }} />
                <YAxis yAxisId="s" orientation="right" scale="log" domain={[0.1, "auto"]} allowDataOverflow tick={{ fill: "#666", fontSize: 10 }} />
                <Tooltip contentStyle={{ background: "#000", border: "1px solid #2a2a2a" }}
                  labelFormatter={(v) => new Date(Number(v)).toLocaleString("en-IN", { hour12: false })}
                  formatter={(v, n) => [typeof v === "number" ? v.toFixed(n === "health" ? 0 : 2) : "—", String(n)]} />
                <Line yAxisId="h" dataKey="health" stroke="#ccff00" dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls />
                <Line yAxisId="s" dataKey="score" stroke="#e8e8e8" dot={false} strokeWidth={1} isAnimationActive={false} connectNulls />
                {info?.anomaly_threshold && <ReferenceLine yAxisId="s" y={info.anomaly_threshold} stroke="#ff4d3d" strokeDasharray="6 4" />}
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      <div className="dash-two">
        <section className="card">
          <div className="card-head"><h2>Alerts</h2><span className="muted small">{events.length}</span></div>
          {events.length === 0 ? <p className="muted small">None.</p> : (
            <ul className="event-list">
              {events.slice(0, 8).map((e) => (
                <li key={e.id}>
                  <button className={`event-row ${e.id === current ? "active" : ""}`} onClick={() => setEventId(e.id)}>
                    <span className={`event-status ${e.status}`}>{e.status.replace("_", " ")}</span>
                    <span className="mono small">{new Date(e.started_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })}</span>
                    <span className="muted small">{e.source}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {d && (
            <div className="dash-diag">
              <span className="kicker">Diagnosis</span>
              <ul className="fault-bars">
                {d.faults.map((f) => (
                  <li key={f.fault}><span>{fault(f.fault)}</span><div className="bar"><i style={{ width: `${f.confidence * 100}%` }} /></div><b>{Math.round(f.confidence * 100)}%</b></li>
                ))}
              </ul>
              <p className="muted small">{d.faults[0]?.evidence}</p>
              <p className="small">Days left: <b>{d.rul_days_low != null ? `${d.rul_days_low.toFixed(1)}${d.rul_days_high != null ? `–${d.rul_days_high.toFixed(1)}` : "+"} d` : "—"}</b> <span className="muted">({d.rul_status.replace("_", " ")})</span></p>
              <p className="mono dim model-tag">{d.model_versions.diagnosis} · {d.model_versions.rul}</p>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head"><h2>Alert timeline</h2><span className="muted small">{timeline.length} steps</span></div>
          {timeline.length === 0 ? <p className="muted small">Select an alert.</p> : (
            <ol className="timeline">
              {timeline.map(({ a, text }) => (
                <li key={a.id} className={`actor-${a.actor}`}>
                  <span className="tl-icon" title={a.actor}>{a.action === "voice_reply" ? <Mic size={13} /> : ACTOR_ICON[a.actor]}</span>
                  <span className="mono dim tl-time">{time(a.ts)}</span>
                  <span className="tl-text">{text}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Audit log</h2>
          <select className="actor-filter" value={actor} onChange={(e) => setActor(e.target.value)}>
            {["all", "device", "system", "agent", "owner", "mechanic", "operator"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </div>
        <p className="muted small">Append-only: a database trigger blocks edits and deletes.</p>
        <div className="audit-table">
          <table>
            <thead><tr><th>time</th><th>actor</th><th>action</th><th>details</th></tr></thead>
            <tbody>
              {shownAudit.map((a) => (
                <tr key={a.id}>
                  <td className="mono">{time(a.ts)}</td>
                  <td>{a.actor}</td>
                  <td className="mono">{a.action}</td>
                  <td className="mono dim">{JSON.stringify(a.details).slice(0, 140)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
