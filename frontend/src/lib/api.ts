/** Thin client for the SPANDAN backend. The Vite proxy adds the bearer token. */

export interface Owner {
  id: string;
  name: string;
  phone: string;
  language: "kn" | "hi" | "en";
  spending_limit_inr: number;
}

export interface Machine {
  id: string;
  owner_id: string;
  name: string;
  motor_rpm: number | null;
  bearing_model: string | null;
  state: string;
  anomaly_threshold: number | null;
  model_version: string | null;
}

export interface TelemetryRow {
  row_id: string;
  ts: string;
  features: Record<string, number>;
  anomaly_score?: number;
  health_index?: number;
  rpm_estimate?: number;
  model_version?: string;
}

export interface BatchResult {
  accepted: number;
  duplicates: number;
  rejected: { row_id: string; reason: string }[];
}

export interface AnomalyEvent {
  id: string;
  machine_id: string;
  started_at: string;
  peak_score: number | null;
  status: "open" | "diagnosed" | "planned" | "resolved" | "false_alarm";
  source: string;
  created_at: string;
}

export interface Fault {
  fault: string;
  confidence: number;
  evidence: string;
}

export interface Diagnosis {
  id: string;
  faults: Fault[];
  rul_days_low: number | null;
  rul_days_high: number | null;
  rul_status: string;
  model_versions: Record<string, string>;
  created_at: string;
}

export type PlanAction =
  | { type: "buy_part"; dealer: string; dealer_id: string; quote_id: string; part_code: string; description: string; qty: number; unit_price_inr: number; price_inr: number; lead_time_days: number | null; payment: string }
  | { type: "book_mechanic"; mechanic: string; mechanic_id: string; slot_id: string; start: string; end: string; rate_inr: number }
  | { type: "schedule_downtime"; start: string; end: string };

export interface Plan {
  id: string;
  event_id: string;
  owner_id: string;
  plan: {
    fault: Fault & { code: string };
    rul_days: { low: number | null; high: number | null; status: string };
    actions: PlanAction[];
    total_cost_inr: number;
    summary_en: string;
    voice_script: { lang: string; text: string };
  };
  total_cost_inr: number;
  state: "draft" | "pending" | "approved" | "rejected" | "expired" | "executed" | "cancelled";
  voice_script: { lang: string; text: string } | null;
  created_at: string;
  expires_at: string | null;
  decided_at: string | null;
  decided_via: string | null;
}

export type ActualFault =
  | "bearing_outer" | "bearing_inner" | "bearing_ball" | "imbalance" | "misalignment" | "looseness"
  | "no_fault_found" | "other";

export interface JobCard {
  actual_fault: ActualFault;
  parts_replaced: string[];
  notes: string;
  submitted_by: "mechanic" | "owner";
  predicted_fault: string | null;
  diagnosis_correct: boolean | null;
}

export interface Job {
  id: string;
  plan_id: string;
  status: "scheduled" | "done" | "no_show";
  mechanic: string;
  start: string;
  end: string;
  job_card: JobCard | null;
}

export interface FalseAlarmResult {
  event: AnomalyEvent;
  machine_state: string;
  anomaly_threshold: number | null;
  threshold_base: number | null;
  threshold_raise_pct: number;
  cancelled_plan_id: string | null;
}

export interface EventDetail extends AnomalyEvent {
  jobs: Job[];
  diagnosis: Diagnosis | null;
  plans: Plan[];
}

export interface Health {
  machine_id: string;
  state: string;
  open_event: AnomalyEvent | null;
  pending_plan_id: string | null;
  minutes_since_last_reading: number | null;
  readings_24h: number;
}

export interface Message {
  id: string;
  kind: string;
  lang: string;
  text: string;
  plan_id: string | null;
  event_id: string | null;
  created_at: string;
}

export interface Decision {
  plan: Plan;
  executed: boolean | null;
  reason: string | null;
  job_id: string | null;
  replanning: boolean;
}

export interface VoiceReply {
  transcript: string;
  intent: "approve" | "reject" | "question" | "unclear";
  intent_source: string;
  action: "approved" | "rejected" | "replanning" | "reask" | "use_buttons";
  attempt: number;
  question: string | null;
  decision: Decision | null;
  say: { lang: string; text: string; audio_url: string | null };
}

export interface PlannerResult {
  status: "planned" | "failed" | "skipped";
  plan_id: string | null;
  provider: string | null;
  reason: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string }>("/health"),
  createOwner: (body: { name: string; phone: string; language: string; spending_limit_inr: number }) =>
    post<Owner>("/api/v1/owners", body),
  getOwner: (id: string) => request<Owner>(`/api/v1/owners/${id}`),
  createMachine: (body: { owner_id: string; name: string; motor_rpm: number; bearing_model: string; sensor_id: string }) =>
    post<Machine>("/api/v1/machines", body),
  getMachine: (id: string) => request<Machine>(`/api/v1/machines/${id}`),
  startBaseline: (id: string) => post<Machine>(`/api/v1/machines/${id}/baseline/start`),
  completeBaseline: (id: string, anomaly_threshold: number, model_version: string) =>
    post<Machine>(`/api/v1/machines/${id}/baseline/complete`, { anomaly_threshold, model_version }),
  uploadBatch: (machine_id: string, device_id: string, rows: TelemetryRow[]) =>
    post<BatchResult>("/api/v1/telemetry/batch", { machine_id, device_id, rows }),
  uploadWindows: (machineId: string, kind: "baseline" | "alert", fs: number, rpm: number, windows: number[][]) =>
    post<{ stored: number; rediagnosed: boolean }>(`/api/v1/machines/${machineId}/windows`, { kind, ts: new Date().toISOString(), fs, rpm, windows }),
  // Cloud side: events, diagnosis, plans, approval (Member 2 backend)
  reportAnomaly: (machine_id: string, started_at: string, peak_score: number) =>
    post<AnomalyEvent>("/api/v1/events/anomaly", { machine_id, started_at, peak_score }),
  getEvent: (id: string) => request<EventDetail>(`/api/v1/events/${id}`),
  planEvent: (id: string) => post<PlannerResult>(`/api/v1/events/${id}/plan`),
  machineHealth: (id: string) => request<Health>(`/api/v1/machines/${id}/health`),
  decide: (planId: string, decision: "approve" | "reject", from_phone: string) =>
    post<Decision>(`/api/v1/plans/${planId}/decision`, { decision, channel: "tap", from_phone }),
  ownerMessages: (ownerId: string) => request<Message[]>(`/api/v1/owners/${ownerId}/messages`),
  // Feedback: the mechanic's job card, the owner's false alarm
  jobCard: (jobId: string, body: { actual_fault: ActualFault; parts_replaced: string[]; notes: string; from_phone: string }) =>
    post<{ job: Job; event_status: string; machine_state: string; diagnosis_correct: boolean | null }>(`/api/v1/jobs/${jobId}/job-card`, body),
  falseAlarm: (eventId: string, from_phone: string, note = "") =>
    post<FalseAlarmResult>(`/api/v1/alerts/${eventId}/false-alarm`, { from_phone, note }),
  // Voice (Gnani on the server): the note is an OGG/Opus file; the reply is the owner's recording.
  voiceNoteUrl: (planId: string) => `/api/v1/plans/${planId}/voice-note`,
  voiceReply: async (planId: string, audio: Blob, from_phone: string): Promise<VoiceReply> => {
    const form = new FormData();
    form.append("audio", audio, audio.type.includes("ogg") ? "reply.ogg" : "reply.webm");
    form.append("from_phone", from_phone);
    const res = await fetch(`/api/v1/plans/${planId}/voice-reply`, { method: "POST", body: form });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
    return body as VoiceReply;
  },
};

/** IDs of the machine set up in this browser. */
export const session = {
  get(): { ownerId: string; machineId: string } | null {
    const raw = localStorage.getItem("spandan.session");
    return raw ? JSON.parse(raw) : null;
  },
  set(v: { ownerId: string; machineId: string }) {
    localStorage.setItem("spandan.session", JSON.stringify(v));
  },
  clear() {
    localStorage.removeItem("spandan.session");
  },
};
