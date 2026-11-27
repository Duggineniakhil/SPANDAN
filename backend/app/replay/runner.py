"""Server-side replay (M2-34): play the phone's part against the real API, from a window source.

    setup (owner + machine) → baseline (rows without a score, then baseline/complete + 3 raw windows)
    → monitoring (score, health, batched telemetry) → 3 readings in a row over the threshold
    → the last 3 raw windows, then the readings, then POST /events/anomaly
    → the cloud diagnoses it and the agent plans it → approve (tap or voice) → booked
    → job card with the true label → a new baseline from the repaired windows.

It talks HTTP only (any httpx-style client: `httpx.Client` against a running server, or FastAPI's
TestClient in tests), so it exercises exactly what the phone does. Timestamps run on a virtual clock,
one reading per `reading_interval_min` ending at "now", so days-left is computed as on a phone.
"""
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.replay.phone import MODEL_VERSION, AlertRule, Baseline, fit_baseline, phone_features
from app.replay.sources import ReplayWindow

API = "/api/v1"
MAX_RAW = 65536  # samples per raw window the API accepts


class ReplayError(Exception):
    pass


@dataclass
class Alert:
    index: int            # window number in the source
    ts: datetime
    score: float
    label: str            # ground truth at that window
    severity: float | None
    event_id: str | None = None
    created: bool = False


@dataclass
class ReplayResult:
    owner_id: str = ""
    machine_id: str = ""
    owner_phone: str = ""
    windows: int = 0
    threshold: float | None = None
    max_score_before_fault: float = 0.0
    false_alerts: int = 0   # alerts raised on windows labelled normal
    alert: Alert | None = None
    diagnosis: dict | None = None
    plan: dict | None = None
    decision: dict | None = None
    job_card: dict | None = None
    new_threshold: float | None = None
    log: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        d = self.diagnosis or {}
        top = (d.get("faults") or [{}])[0]
        a = self.alert
        return {
            "machine_id": self.machine_id, "windows": self.windows, "threshold": self.threshold,
            "false_alerts": self.false_alerts,
            "alert": a and {"window": a.index, "true_label": a.label, "severity": a.severity, "score": round(a.score, 2),
                            "event_id": a.event_id},
            "diagnosis": d and {"top": top.get("fault"), "confidence": top.get("confidence"),
                                "correct": a is not None and top.get("fault") == a.label,
                                "rul_days": [d.get("rul_days_low"), d.get("rul_days_high")], "rul_status": d.get("rul_status")},
            "plan": self.plan and {"id": self.plan["id"], "total_inr": self.plan["total_cost_inr"],
                                   "state": self.plan["state"]},
            "decision": self.decision, "job_card": self.job_card, "new_threshold": self.new_threshold,
        }


class Replayer:
    def __init__(self, client, windows: Iterator[ReplayWindow], *, count: int, unit: str = "replay",
                 bearing_model: str = "6205-2RS", rpm: float = 2880, baseline_windows: int = 30,
                 batch_size: int = 60, reading_interval_min: float = 1.0, device_id: str = "replay-tool",
                 log: Callable[[str], None] | None = None):
        self.c = client
        self.windows = windows
        self.count = count
        self.unit, self.bearing_model, self.rpm = unit, bearing_model, rpm
        self.baseline_windows = baseline_windows
        self.batch_size = batch_size
        self.step = timedelta(minutes=reading_interval_min)
        self.device_id = device_id
        self.t0 = datetime.now(UTC) - self.step * count  # the last reading lands at about "now"
        self.i = -1
        self.queue: list[dict] = []
        self.recent: deque[ReplayWindow] = deque(maxlen=3)
        self.baseline: Baseline | None = None
        self.r = ReplayResult()
        self._print = log or (lambda s: None)

    # ---------- plumbing ----------

    def log(self, msg: str) -> None:
        self.r.log.append(msg)
        self._print(msg)

    def _call(self, method: str, path: str, ok=(200, 201), **kw):
        res = self.c.request(method, API + path, **kw)
        if res.status_code not in ok:
            raise ReplayError(f"{method} {path} → {res.status_code}: {res.text[:300]}")
        return res.json()

    def _next(self) -> ReplayWindow | None:
        w = next(self.windows, None)
        if w is not None:
            self.i += 1
            self.r.windows += 1
        return w

    def _ts(self) -> datetime:
        return self.t0 + self.step * self.i

    def _flush(self) -> None:
        while self.queue:
            batch, self.queue = self.queue[:1000], self.queue[1000:]
            self._call("POST", "/telemetry/batch", json={"device_id": self.device_id,
                                                          "machine_id": self.r.machine_id, "rows": batch})

    def _upload_recent(self, kind: str) -> None:
        if not self.recent:
            return
        w = self.recent[-1]
        self._call("POST", f"/machines/{self.r.machine_id}/windows", json={
            "kind": kind, "ts": self._ts().isoformat(), "fs": w.fs, "rpm": w.rpm,
            "windows": [[round(float(v), 5) for v in x.y[:MAX_RAW]] for x in self.recent]})

    # ---------- the phone's steps ----------

    def setup(self, *, phone: str | None = None, language: str = "kn", spending_limit_inr: int = 2500,
              owner_id: str | None = None) -> None:
        if owner_id:
            owner = self._call("GET", f"/owners/{owner_id}")
        else:
            phone = phone or "+9197" + str(uuid.uuid4().int)[:8]
            owner = self._call("POST", "/owners", json={"name": "Replay owner", "phone": phone, "language": language,
                                                        "spending_limit_inr": spending_limit_inr})
        machine = self._call("POST", "/machines", json={
            "owner_id": owner["id"], "name": f"Replay · {self.unit}", "motor_rpm": int(round(self.rpm)),
            "bearing_model": self.bearing_model, "sensor_id": f"replay-{self.unit}-{uuid.uuid4().hex[:6]}"})
        self.r.owner_id, self.r.owner_phone, self.r.machine_id = owner["id"], owner["phone"], machine["id"]
        self.log(f"machine {machine['id']} for owner {owner['id']} ({owner['language']})")

    def learn_baseline(self, n: int | None = None, *, tell_server: bool = True) -> Baseline:
        """Next `n` windows → baseline rows; fit; baseline/complete; 3 raw baseline windows."""
        n = n or self.baseline_windows
        if tell_server:
            self._call("POST", f"/machines/{self.r.machine_id}/baseline/start")
        samples = []
        while len(samples) < n:
            w = self._next()
            if w is None:
                raise ReplayError(f"source ended during the baseline ({len(samples)} of {n} windows)")
            f, rpm = phone_features(w.x, w.y, w.z, w.fs, w.rpm)
            samples.append(f)
            self.recent.append(w)
            self.queue.append({"row_id": str(uuid.uuid4()), "ts": self._ts().isoformat(), "features": f,
                               "rpm_estimate": rpm})
        self._flush()
        self.baseline = fit_baseline(samples)
        self._call("POST", f"/machines/{self.r.machine_id}/baseline/complete",
                   json={"anomaly_threshold": self.baseline.threshold, "model_version": MODEL_VERSION})
        self._upload_recent("baseline")
        self.log(f"baseline learned from {n} windows; threshold {self.baseline.threshold:.2f}")
        return self.baseline

    def monitor(self, *, stop_at_alert: bool = True, resend_every: int = 5) -> Alert | None:
        """Stream windows until the alert rule fires (or the source ends), reporting it like the phone.
        If the cloud can't name the fault yet, keep streaming and re-send fresh alert windows every
        `resend_every` readings while the alert is active, until it can (as the phone app does)."""
        if self.baseline is None:
            raise ReplayError("learn the baseline first")
        rule = AlertRule(3)
        first: Alert | None = None
        unclear = False
        since_resend = 0
        while (w := self._next()) is not None:
            f, rpm = phone_features(w.x, w.y, w.z, w.fs, w.rpm)
            sc = self.baseline.score(f)
            if w.label == "normal":
                self.r.max_score_before_fault = max(self.r.max_score_before_fault, sc)
            self.recent.append(w)
            self.queue.append({"row_id": str(uuid.uuid4()), "ts": self._ts().isoformat(), "features": f,
                               "anomaly_score": sc, "health_index": round(self.baseline.health(sc), 2),
                               "rpm_estimate": rpm, "model_version": MODEL_VERSION})
            change = rule.update(sc, self.baseline.threshold)
            if change == "raised":
                alert = Alert(self.i, self._ts(), sc, w.label, w.severity)
                if w.label == "normal":
                    self.r.false_alerts += 1
                # as the phone: raw windows first, then the readings, then the report
                self._upload_recent("alert")
                self._flush()
                ev = self.c.post(API + "/events/anomaly", json={"machine_id": self.r.machine_id,
                                                                "started_at": alert.ts.isoformat(), "peak_score": sc})
                if ev.status_code not in (200, 201):
                    raise ReplayError(f"anomaly report → {ev.status_code}: {ev.text[:200]}")
                alert.event_id, alert.created = ev.json()["id"], ev.status_code == 201
                self.log(f"ALERT at window {alert.index} (true: {w.label}"
                         f"{f', severity {w.severity:.2f}' if w.severity is not None else ''}), score {sc:.1f} "
                         f"vs {self.baseline.threshold:.2f} → event {alert.event_id}")
                first = first or alert
                unclear = self._top_fault(alert.event_id) == "unknown"
                since_resend = 0
                if unclear:
                    self.log("cloud: cause not clear yet; keep sending fresh windows while the alert lasts")
                elif stop_at_alert:
                    break
            elif rule.active and unclear:
                since_resend += 1
                if since_resend >= resend_every:
                    since_resend = 0
                    self._flush()
                    res = self._call("POST", f"/machines/{self.r.machine_id}/windows", ok=(201,), json={
                        "kind": "alert", "ts": self._ts().isoformat(), "fs": w.fs, "rpm": w.rpm,
                        "windows": [[round(float(v), 5) for v in x.y[:MAX_RAW]] for x in self.recent]})
                    if res.get("rediagnosed"):
                        unclear = False
                        self.log(f"cloud re-diagnosed at window {self.i} (true: {w.label}"
                                 f"{f', severity {w.severity:.2f}' if w.severity is not None else ''})")
                        if stop_at_alert:
                            break
            if len(self.queue) >= self.batch_size:
                self._flush()
        self._flush()
        self.r.alert = first
        self.r.threshold = self.baseline.threshold
        if first and first.event_id:
            self.r.diagnosis = self._call("GET", f"/events/{first.event_id}")["diagnosis"]
            d = self.r.diagnosis or {}
            if d.get("faults"):
                top = d["faults"][0]
                self.log(f"cloud diagnosis: {top['fault']} ({top['confidence']:.0%}); {top['evidence'][:110]}")
                self.log(f"days left: {d.get('rul_status')} {d.get('rul_days_low')}–{d.get('rul_days_high')}")
        elif not first:
            self.log("no alert raised")
        return first

    def _top_fault(self, event_id: str) -> str | None:
        d = self._call("GET", f"/events/{event_id}")["diagnosis"] or {}
        return (d.get("faults") or [{}])[0].get("fault")

    def get_plan(self, *, plan_now: bool = False, timeout_s: float = 150) -> dict | None:
        """Wait for the agent's plan (or run it now, synchronously)."""
        ev_id = self.r.alert.event_id if self.r.alert else None
        if not ev_id:
            return None
        if plan_now:
            res = self._call("POST", f"/events/{ev_id}/plan")
            self.log(f"agent: {res['status']} {res.get('reason') or res.get('provider') or ''}")
        end = time.monotonic() + timeout_s
        while True:
            ev = self._call("GET", f"/events/{ev_id}")
            pending = [p for p in ev["plans"] if p["state"] == "pending"]
            if pending:
                self.r.plan = pending[0]
                p = pending[0]
                self.log(f"plan {p['id']}: ₹{p['total_cost_inr']} · {p['voice_script']['text'][:90]}…")
                return p
            if plan_now or time.monotonic() > end:
                self.log("no plan")
                return None
            time.sleep(3)

    def approve(self, *, by: str = "tap", decision: str = "approve") -> dict:
        p = self.r.plan
        if p is None:
            raise ReplayError("no plan to approve")
        if by == "voice":
            from app.voice.provider import default_provider

            provider = default_provider()
            if provider is None:
                raise ReplayError("voice approval needs GNANI_API_KEY (the owner's 'yes' is spoken by TTS)")
            lang = p["voice_script"]["lang"]
            word = {"kn": {"approve": "ಹೌದು", "reject": "ಬೇಡ"}, "hi": {"approve": "हाँ", "reject": "नहीं"}}.get(
                lang, {"approve": "yes", "reject": "no"})[decision]
            audio = provider.tts(word, lang)
            res = self._call("POST", f"/plans/{p['id']}/voice-reply", data={"from_phone": self.r.owner_phone},
                             files={"audio": ("reply.ogg", audio, "audio/ogg")})
            self.log(f"owner said «{word}» → heard «{res['transcript']}» → {res['action']}")
            out = {"by": "voice", "said": word, "heard": res["transcript"], "action": res["action"],
                   "executed": (res.get("decision") or {}).get("executed"),
                   "job_id": (res.get("decision") or {}).get("job_id")}
        else:
            res = self._call("POST", f"/plans/{p['id']}/decision", json={
                "decision": decision, "channel": "tap", "from_phone": self.r.owner_phone})
            out = {"by": "tap", "action": res["plan"]["state"], "executed": res["executed"], "job_id": res["job_id"]}
            self.log(f"owner tapped {decision} → {res['plan']['state']}")
        self.r.decision = out
        return out

    def job_card(self, actual_fault: str | None = None) -> dict:
        """The mechanic's job card with the true label (from the source), sent from the owner's phone."""
        ev = self._call("GET", f"/events/{self.r.alert.event_id}")
        job = next((j for j in ev["jobs"] if j["status"] == "scheduled"), None)
        if job is None:
            raise ReplayError("no booked job for this alert")
        fault = actual_fault or (self.r.alert.label if self.r.alert.label != "normal" else "no_fault_found")
        if fault not in {"bearing_outer", "bearing_inner", "bearing_ball", "imbalance", "misalignment", "looseness",
                         "no_fault_found"}:
            fault = "other"
        res = self._call("POST", f"/jobs/{job['id']}/job-card", json={
            "actual_fault": fault, "parts_replaced": ["6205-2RS"] if fault.startswith("bearing_") else [],
            "notes": "replay: true label from the dataset", "from_phone": self.r.owner_phone})
        self.r.job_card = {"actual_fault": fault, "diagnosis_correct": res["diagnosis_correct"],
                           "machine_state": res["machine_state"]}
        self.log(f"job card: {fault} (diagnosis correct: {res['diagnosis_correct']}) → machine {res['machine_state']}")
        return res

    def relearn_after_repair(self) -> float | None:
        """Skip the rest of the fault, then learn a new baseline from the repaired (normal) windows."""
        seen_fault = self.r.alert is not None and self.r.alert.label != "normal"
        buffered: list[ReplayWindow] = []
        while (w := self._next()) is not None:
            if w.label == "normal" or not seen_fault:
                buffered.append(w)
                break
        if not buffered:
            self.log("no repaired windows in the source; skipping the new baseline")
            return None
        rest = self.windows
        self.windows = iter([*buffered, *rest])
        self.i -= 1  # the buffered window is read again
        self.r.windows -= 1
        b = self.learn_baseline(tell_server=False)  # the job card already started the baseline
        self.r.new_threshold = b.threshold
        return b.threshold
