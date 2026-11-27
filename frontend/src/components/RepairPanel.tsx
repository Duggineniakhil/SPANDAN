/**
 * Cloud side of an alert, as the owner's app shows it (M1-23 plan card, doc 06 §5):
 * diagnosis + days left → the agent's plan → Approve / Reject → booking, plus the owner's messages.
 * Polls the backend; decisions are sent with the owner's registered number (the server checks it).
 */
import { AnimatePresence, motion } from "framer-motion";
import { Bot, CalendarClock, Check, MessageSquare, Package, RefreshCw, ShieldCheck, Stethoscope, Wrench, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import VoicePanel from "./VoicePanel";
import { api, type EventDetail, type Health, type Message, type Owner, type Plan, type PlanAction } from "../lib/api";

const POLL_MS = 3000;

const FAULT_NAMES: Record<string, string> = {
  bearing_outer: "Bearing outer-race wear",
  bearing_inner: "Bearing inner-race wear",
  bearing_ball: "Bearing ball damage",
  imbalance: "Imbalance",
  looseness: "Mechanical looseness",
  misalignment: "Misalignment",
  unknown: "Unclear cause",
};

const MESSAGE_LABEL: Record<string, string> = {
  plan_ready: "Repair plan", reminder: "Reminder", booking_confirmed: "Booked", rejected: "Plan cancelled",
  expired: "Plan expired", slot_lost: "Slot lost", could_not_plan: "Couldn't plan", inspection: "Inspection",
};

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
/** Days → "2–5 days", or hours when it is short (the web demo runs ~60× faster than a mill). */
function span(low: number, high?: number): string {
  const top = high ?? low;
  if (top < 2) {
    const h = (d: number) => Math.max(0, Math.round(d * 24 * 10) / 10);
    return high == null ? `${h(low)} hours` : `${h(low)}–${h(high)} hours`;
  }
  const r = (d: number) => Math.round(d * 10) / 10;
  return high == null ? `${r(low)} days` : `${r(low)}–${r(high)} days`;
}
const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;
const maskPhone = (p: string) => p.replace(/\d(?=\d{4})/g, "•");

function useCloud(machineId: string, ownerId: string) {
  const [health, setHealth] = useState<Health | null>(null);
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastEventId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, msgs] = await Promise.all([api.machineHealth(machineId), api.ownerMessages(ownerId)]);
      setHealth(h);
      setMessages(msgs);
      // Keep showing the last event after it is planned/booked, until a new one opens.
      const id = h.open_event?.id ?? lastEventId.current;
      lastEventId.current = id;
      setEvent(id ? await api.getEvent(id) : null);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [machineId, ownerId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return { health, event, messages, error, refresh };
}

export default function RepairPanel({ machineId, owner }: { machineId: string; owner: Owner }) {
  const { event, messages, error, refresh } = useCloud(machineId, owner.id);
  const [busy, setBusy] = useState<"approve" | "reject" | "plan" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const plan: Plan | undefined = event?.plans[0];
  const eventMessages = messages.filter((m) => m.event_id === event?.id);
  const couldNotPlan = eventMessages.find((m) => m.kind === "could_not_plan" || m.kind === "inspection");

  async function decide(decision: "approve" | "reject") {
    if (!plan) return;
    setBusy(decision);
    setNotice(null);
    try {
      const r = await api.decide(plan.id, decision, owner.phone);
      setNotice(r.executed === false ? `Not booked: ${r.reason}.${r.replanning ? " A new plan is being prepared." : ""}` : null);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(null);
      void refresh();
    }
  }

  async function replan() {
    if (!event) return;
    setBusy("plan");
    setNotice("The coordinator agent is planning (can take up to a minute)…");
    try {
      const r = await api.planEvent(event.id);
      setNotice(r.status === "planned" ? null : `No plan: ${r.reason}`);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(null);
      void refresh();
    }
  }

  return (
    <section className="card repair-card wide">
      <div className="card-head">
        <h2><Stethoscope size={18} /> Cloud diagnosis &amp; repair plan</h2>
        <span className="muted small">owner's app view · {owner.language.toUpperCase()}</span>
      </div>
      {error && <p className="error small">Backend: {error}</p>}

      {!event ? (
        <div className="repair-empty">
          <ShieldCheck size={22} />
          <p>No open alerts. Inject a fault: when the alert fires, the cloud diagnoses it, the agent plans the repair, and the plan appears here for the owner to approve.</p>
        </div>
      ) : (
        <div className="repair-grid">
          <Diagnosis event={event} />
          <div className="plan-col">
            <AnimatePresence mode="wait">
              {plan ? (
                <PlanCard key={plan.id + plan.state} plan={plan} owner={owner} busy={busy} onDecide={decide} onVoice={() => void refresh()}
                  failBy={event.diagnosis?.rul_status === "ok" && event.diagnosis.rul_days_low != null
                    ? Date.now() + event.diagnosis.rul_days_low * 86_400_000 : null} />
              ) : couldNotPlan ? (
                <motion.div key="noplan" className="plan-waiting" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <p>{couldNotPlan.text}</p>
                </motion.div>
              ) : (
                <motion.div key="wait" className="plan-waiting" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <Bot className="spin-slow" size={22} />
                  <p>The coordinator agent is asking dealers for quotes and finding a mechanic slot…</p>
                </motion.div>
              )}
            </AnimatePresence>
            {event.status === "diagnosed" && (!plan || ["rejected", "expired", "cancelled"].includes(plan.state)) && (
              <button className="btn btn-ghost" disabled={busy !== null} onClick={replan}>
                <RefreshCw size={15} className={busy === "plan" ? "spin" : ""} /> {plan ? "Ask for a new plan" : "Plan now"}
              </button>
            )}
            {notice && <p className="small notice">{notice}</p>}
          </div>
          <Inbox messages={messages.slice(0, 6)} />
        </div>
      )}
    </section>
  );
}

function Diagnosis({ event }: { event: EventDetail }) {
  const d = event.diagnosis;
  if (!d) return <div className="diag-col"><p className="muted">Diagnosing…</p></div>;
  const top = d.faults[0];
  return (
    <div className="diag-col">
      <span className="kicker">Likely fault</span>
      <h3 className="diag-fault">{FAULT_NAMES[top.fault] ?? top.fault}</h3>
      <p className="muted small">{top.evidence}</p>
      <ul className="fault-bars">
        {d.faults.map((f) => (
          <li key={f.fault}>
            <span>{FAULT_NAMES[f.fault] ?? f.fault}</span>
            <div className="bar"><motion.i initial={{ width: 0 }} animate={{ width: `${f.confidence * 100}%` }} /></div>
            <b>{Math.round(f.confidence * 100)}%</b>
          </li>
        ))}
      </ul>
      {d.rul_status === "ok" && d.rul_days_low != null && d.rul_days_high != null ? (
        <div className="rul">
          <CalendarClock size={16} />
          <span><b>{span(d.rul_days_low, d.rul_days_high)}</b> before it is likely to fail</span>
          <em className="muted small">from the wear trend · repair before the low end</em>
        </div>
      ) : d.rul_status === "default_window" && d.rul_days_low != null ? (
        <div className="rul">
          <CalendarClock size={16} />
          <span>No clear wear trend yet: <b>repair within {span(d.rul_days_low)}</b></span>
          <em className="muted small">safety window; updates as readings arrive</em>
        </div>
      ) : (
        <p className="muted small">Cause unclear, so no days-left estimate: get the machine inspected.</p>
      )}
      <p className="mono dim model-tag">{d.model_versions.diagnosis}{d.model_versions.windows !== "0" ? ` · ${d.model_versions.windows} raw windows` : " · features only"}</p>
    </div>
  );
}

function PlanCard({ plan, owner, busy, onDecide, onVoice, failBy }: {
  plan: Plan; owner: Owner; busy: string | null; onDecide: (d: "approve" | "reject") => void; onVoice: () => void;
  failBy: number | null;
}) {
  const p = plan.plan;
  const part = p.actions.find((a): a is Extract<PlanAction, { type: "buy_part" }> => a.type === "buy_part");
  const mech = p.actions.find((a): a is Extract<PlanAction, { type: "book_mechanic" }> => a.type === "book_mechanic");
  const pending = plan.state === "pending";
  // Days-left is recomputed as readings arrive; warn if it now ends before the booked slot.
  const tooLate = pending && mech != null && failBy != null && new Date(mech.start).getTime() > failBy;
  const stateLabel: Record<Plan["state"], string> = {
    draft: "Draft", pending: "Waiting for the owner", approved: "Approved", executed: "Booked",
    rejected: "Rejected by the owner", expired: "Expired (no reply)", cancelled: "Cancelled",
  };
  return (
    <motion.div className={`plan-card state-${plan.state}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <div className="plan-head">
        <span className="kicker">Repair plan</span>
        <span className={`plan-state ${plan.state}`}>{plan.state === "executed" && <Check size={13} />} {stateLabel[plan.state]}</span>
      </div>
      <ul className="plan-actions">
        {part && (
          <li><Package size={16} /><div><b>{part.description}</b><span className="muted small">{part.qty} × {part.part_code} from {part.dealer} · pay at pickup</span></div><em>{inr(part.price_inr)}</em></li>
        )}
        {mech && (
          <li><Wrench size={16} /><div><b>{mech.mechanic}</b><span className="muted small">{when(mech.start)} – {new Date(mech.end).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })} · machine stopped</span></div><em>{inr(mech.rate_inr)}</em></li>
        )}
      </ul>
      <div className="plan-total"><span>Total</span><b>{inr(plan.total_cost_inr)}</b><span className="muted small">limit {inr(owner.spending_limit_inr)}</span></div>
      {plan.voice_script && (
        <blockquote className="voice" lang={plan.voice_script.lang}>
          <MessageSquare size={14} /> {plan.voice_script.text}
        </blockquote>
      )}
      {tooLate && (
        <p className="late-warn small">The latest wear trend says it may fail before this slot. Ask for a new plan or call a mechanic sooner.</p>
      )}
      {pending ? (
        <>
          <VoicePanel planId={plan.id} phone={owner.phone} lang={plan.voice_script?.lang ?? owner.language} onDone={onVoice} />
          <div className="plan-buttons">
            <button className="btn btn-primary" disabled={busy !== null} onClick={() => onDecide("approve")}><Check size={16} /> Approve</button>
            <button className="btn btn-ghost" disabled={busy !== null} onClick={() => onDecide("reject")}><X size={16} /> Reject</button>
          </div>
          <p className="muted small">Sent from the owner's number {maskPhone(owner.phone)}; any other number is refused. No reply in 48 h → the plan expires; nothing is ever approved automatically.</p>
        </>
      ) : plan.state === "executed" ? (
        <p className="small">Mechanic booked, dealer order confirmed, downtime scheduled. The system never pays: the owner pays at pickup.</p>
      ) : null}
    </motion.div>
  );
}

function Inbox({ messages }: { messages: Message[] }) {
  return (
    <div className="inbox-col">
      <span className="kicker">Owner's messages</span>
      {messages.length === 0 ? <p className="muted small">Nothing yet.</p> : (
        <ul className="inbox">
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <motion.li key={m.id} layout initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}>
                <span className="mono dim">{MESSAGE_LABEL[m.kind] ?? m.kind} · {new Date(m.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })}</span>
                <p lang={m.lang}>{m.text}</p>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}
