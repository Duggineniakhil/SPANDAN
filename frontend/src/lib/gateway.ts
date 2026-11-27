/**
 * Phone-gateway engine running in the browser (Member 1's pipeline, doc 04):
 * sensor window → features → anomaly score → health index → alert → queue → sync.
 *
 * Demo speed: one window every `intervalMs` stands for one minute on a real mill.
 */
import { api, type BatchResult, type TelemetryRow } from "./api";
import { AlertRule, MODEL_VERSION, ema, fitBaseline, healthIndex, score, topContributors, type Baseline } from "./detector";
import { extractFeatures, type Spectrum } from "./features";
import { FS, generateWindow, type FaultType } from "./signal";

export const BASELINE_WINDOWS = 30;
const SYNC_EVERY = 10;
const DEVICE_ID = "web-gateway-01";
const MAX_HISTORY = 120;

export type Phase = "idle" | "baseline" | "monitoring";

export interface Point {
  t: number;
  score: number | null;
  health: number | null;
  threshold: number | null;
}

export interface LogEntry {
  id: number;
  at: Date;
  kind: "info" | "alert" | "ok" | "sync" | "error";
  text: string;
}

export interface GatewayState {
  phase: Phase;
  running: boolean;
  online: boolean;
  fault: FaultType;
  severity: number;
  progressive: boolean;
  windowCount: number;
  baselineProgress: number;
  baseline: Baseline | null;
  lastWave: Float64Array | null;
  spectrum: Spectrum | null;
  envSpectrum: Spectrum | null;
  rpm: number;
  health: number | null;
  scoreValue: number | null;
  alertActive: boolean;
  contributors: { name: string; z: number }[];
  history: Point[];
  queued: number;
  synced: number;
  duplicates: number;
  log: LogEntry[];
}

type Listener = (s: GatewayState) => void;

export class Gateway {
  private timer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<Listener>();
  private baselineSamples: Record<string, number>[] = [];
  private queue: TelemetryRow[] = [];
  private alertRule = new AlertRule(3);
  private smoothHealth: number | null = null;
  private logId = 0;
  private syncing = false;
  private pendingReport: { startedAt: string; peak: number; windows: number[][] } | null = null;
  private recent: Float64Array[] = []; // last raw windows (radial axis): sent with an alert for diagnosis

  state: GatewayState;

  constructor(private machineId: string, private rpm: number, private intervalMs = 1000) {
    const saved = loadBaseline(machineId);
    this.state = {
      phase: "idle", running: false, online: true, fault: "none", severity: 0, progressive: true,
      windowCount: 0, baselineProgress: 0, baseline: saved, lastWave: null, spectrum: null,
      envSpectrum: null, rpm, health: null, scoreValue: null, alertActive: false, contributors: [],
      history: [], queued: 0, synced: 0, duplicates: 0, log: [],
    };
  }

  /** Continue monitoring with the baseline saved on this device, if any. */
  resume(): boolean {
    if (!this.state.baseline) return false;
    this.set({ phase: "monitoring" });
    this.log("info", "Resumed monitoring with the baseline saved on this device.");
    this.start();
    return true;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<GatewayState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn(this.state);
  }

  private log(kind: LogEntry["kind"], text: string) {
    const entry = { id: ++this.logId, at: new Date(), kind, text };
    this.set({ log: [entry, ...this.state.log].slice(0, 40) });
  }

  async startBaseline() {
    this.baselineSamples = [];
    this.alertRule = new AlertRule(3);
    this.smoothHealth = null;
    this.set({ phase: "baseline", baseline: null, baselineProgress: 0, fault: "none", severity: 0, history: [] });
    try {
      await api.startBaseline(this.machineId);
    } catch (e) {
      this.log("error", `Baseline start not recorded on server: ${(e as Error).message}`);
    }
    this.log("info", `Learning this machine's normal vibration (${BASELINE_WINDOWS} readings)…`);
    this.start();
  }

  start() {
    if (this.timer) return;
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
    this.set({ running: true });
  }

  pause() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.set({ running: false });
  }

  dispose() {
    this.pause();
    this.listeners.clear();
  }

  setSpeed(ms: number) {
    this.intervalMs = ms;
    if (this.timer) {
      this.pause();
      this.start();
    }
  }

  injectFault(fault: FaultType, progressive: boolean) {
    this.set({ fault, progressive, severity: fault === "none" ? 0 : progressive ? 0.05 : 0.7 });
    this.log("info", fault === "none" ? "Machine repaired — running healthy." : `Fault injected on the motor: ${fault.replace("_", " ")}.`);
  }

  setOnline(online: boolean) {
    this.set({ online });
    this.log("info", online ? "Network back — syncing queued readings." : "Network off — readings are stored on the device.");
    if (online) void this.sync().then(() => this.reportAlert());
  }

  /** Tell the cloud about a confirmed alert (doc 07: POST /events/anomaly). Readings go first, so the
   *  diagnosis sees them. Offline: kept and sent when the network is back. */
  private async reportAlert() {
    const r = this.pendingReport;
    if (!r || !this.state.online) return;
    try {
      // Raw windows first: the cloud diagnoses from them, even if its own backup rule opens the event
      // as soon as the readings arrive.
      if (r.windows.length) {
        await api.uploadWindows(this.machineId, "alert", FS, this.rpm, r.windows);
        r.windows = [];
      }
    } catch (e) {
      this.log("error", `Raw windows not sent: ${(e as Error).message}`);
    }
    await this.sync();
    try {
      const ev = await api.reportAnomaly(this.machineId, r.startedAt, r.peak);
      this.pendingReport = null;
      this.log("sync", ev.status === "diagnosed" || ev.status === "open"
        ? "Alert sent to the cloud: diagnosing and preparing a repair plan…"
        : `Alert sent to the cloud (already ${ev.status}).`);
    } catch (e) {
      this.log("error", `Alert not delivered, will retry: ${(e as Error).message}`);
    }
  }

  private async tick() {
    const s = this.state;
    let severity = s.severity;
    if (s.fault !== "none" && s.progressive) severity = Math.min(1, severity + 0.015);

    const w = generateWindow(s.fault, severity, this.rpm);
    this.recent = [...this.recent, w.y].slice(-3);
    const { features, spectrum, envSpectrum, rpmEstimate } = extractFeatures(w);
    const windowCount = s.windowCount + 1;
    const t = Date.now();
    const patch: Partial<GatewayState> = {
      windowCount, severity, lastWave: w.y.subarray(0, 640), spectrum, envSpectrum, rpm: rpmEstimate,
    };

    if (s.phase === "baseline") {
      this.baselineSamples.push(features);
      patch.baselineProgress = this.baselineSamples.length / BASELINE_WINDOWS;
      this.queueRow({ row_id: crypto.randomUUID(), ts: new Date(t).toISOString(), features, rpm_estimate: rpmEstimate });
      if (this.baselineSamples.length >= BASELINE_WINDOWS) {
        const baseline = fitBaseline(this.baselineSamples);
        saveBaseline(this.machineId, baseline);
        patch.baseline = baseline;
        patch.phase = "monitoring";
        this.set(patch);
        this.log("ok", `Baseline learned. Alert threshold ${baseline.threshold.toFixed(2)}.`);
        try {
          await api.completeBaseline(this.machineId, baseline.threshold, MODEL_VERSION);
          // A few raw healthy windows: the cloud's reference for imbalance and diagnosis.
          await api.uploadWindows(this.machineId, "baseline", FS, this.rpm, this.recent.map(toList));
        } catch (e) {
          this.log("error", `Baseline not saved on server: ${(e as Error).message}`);
        }
        return;
      }
    } else if (s.phase === "monitoring" && s.baseline) {
      const sc = score(s.baseline, features);
      this.smoothHealth = ema(this.smoothHealth, healthIndex(s.baseline, sc));
      const health = Math.round(this.smoothHealth);
      const change = this.alertRule.update(sc, s.baseline.threshold);
      const contributors = topContributors(s.baseline, features);
      patch.scoreValue = sc;
      patch.health = health;
      patch.contributors = contributors;
      patch.alertActive = this.alertRule.active;
      patch.history = [...s.history, { t, score: sc, health, threshold: s.baseline.threshold }].slice(-MAX_HISTORY);
      this.queueRow({
        row_id: crypto.randomUUID(), ts: new Date(t).toISOString(), features,
        anomaly_score: sc, health_index: health, rpm_estimate: rpmEstimate, model_version: MODEL_VERSION,
      });
      if (change === "raised") {
        const why = contributors.map((c) => c.name).join(", ");
        this.log("alert", `Unusual vibration for 3 readings in a row (score ${sc.toFixed(1)}). Biggest changes: ${why}.`);
        if (!s.online) this.log("alert", "No network: SMS alert sent to the owner (simulated).");
        this.pendingReport = { startedAt: new Date(t).toISOString(), peak: sc, windows: this.recent.map(toList) };
        void this.reportAlert();
      } else if (change === "cleared") {
        this.log("ok", "Vibration back to normal.");
      }
    }

    this.set(patch);
    if (this.queue.length >= SYNC_EVERY && this.state.online) void this.sync();
  }

  private queueRow(row: TelemetryRow) {
    this.queue.push(row);
    this.set({ queued: this.queue.length });
  }

  async sync(): Promise<BatchResult | null> {
    if (this.syncing || this.queue.length === 0 || !this.state.online) return null;
    this.syncing = true;
    const batch = this.queue.slice(0, 500);
    try {
      const res = await api.uploadBatch(this.machineId, DEVICE_ID, batch);
      this.queue = this.queue.slice(batch.length);
      this.set({
        queued: this.queue.length,
        synced: this.state.synced + res.accepted,
        duplicates: this.state.duplicates + res.duplicates,
      });
      this.log("sync", `Uploaded ${res.accepted} readings${res.duplicates ? ` (${res.duplicates} already stored)` : ""}.`);
      return res;
    } catch (e) {
      this.log("error", `Upload failed, will retry: ${(e as Error).message}`);
      return null;
    } finally {
      this.syncing = false;
    }
  }
}

/** Raw window → plain numbers, rounded to 0.1 mg (keeps the upload small). */
function toList(y: Float64Array): number[] {
  return Array.from(y, (v) => Math.round(v * 1e4) / 1e4);
}

// The phone keeps its baseline locally (doc 04 §6); here that's localStorage.
const baselineKey = (machineId: string) => `spandan.baseline.${machineId}`;

function saveBaseline(machineId: string, b: Baseline) {
  try {
    localStorage.setItem(baselineKey(machineId), JSON.stringify(b));
  } catch {
    /* storage unavailable (e.g. tests) */
  }
}

function loadBaseline(machineId: string): Baseline | null {
  try {
    const raw = localStorage.getItem(baselineKey(machineId));
    return raw ? (JSON.parse(raw) as Baseline) : null;
  } catch {
    return null;
  }
}
