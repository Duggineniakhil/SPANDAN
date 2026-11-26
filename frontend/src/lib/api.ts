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
