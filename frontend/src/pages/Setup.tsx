import { motion } from "framer-motion";
import { CheckCircle2, Loader2, Server, ServerOff } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { SensorArt } from "../art/Illustrations";
import { api, session } from "../lib/api";

type Lang = "kn" | "hi" | "en";

export default function Setup() {
  const nav = useNavigate();
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const existing = session.get();

  const [owner, setOwner] = useState({ name: "", phone: "", language: "kn" as Lang, spending_limit_inr: 2000 });
  const [machine, setMachine] = useState({ name: "Main grinder motor", motor_rpm: 2880, bearing_model: "6205-2RS" });

  useEffect(() => {
    api.health().then(() => setBackendUp(true)).catch(() => setBackendUp(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const o = await api.createOwner(owner);
      const m = await api.createMachine({
        owner_id: o.id, ...machine, sensor_id: `sim-${crypto.randomUUID().slice(0, 8)}`,
      });
      session.set({ ownerId: o.id, machineId: m.id });
      nav("/monitor?start=baseline");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page setup">
      <motion.div className="setup-intro" initial={{ opacity: 0, x: -30 }} animate={{ opacity: 1, x: 0 }}>
        <span className="kicker">Café operator setup</span>
        <h1>Pair a machine</h1>
        <p className="muted">
          Register the owner and the motor. SPANDAN then learns this machine's normal vibration before it starts
          watching for faults. Until the hardware sensor is ready, a simulated sensor stands in for it.
        </p>
        <SensorArt className="art-lg" />
        <div className={`backend-pill ${backendUp ? "up" : backendUp === false ? "down" : ""}`}>
          {backendUp === null ? <Loader2 className="spin" size={16} /> : backendUp ? <Server size={16} /> : <ServerOff size={16} />}
          {backendUp === null ? "Checking server…" : backendUp ? "Server connected" : "Server not reachable — start the backend"}
        </div>
        {existing && (
          <button className="btn btn-ghost small" onClick={() => nav("/monitor")}>
            <CheckCircle2 size={16} /> Continue with the machine already set up
          </button>
        )}
      </motion.div>

      <motion.form className="card form" onSubmit={submit} initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <h2>Owner</h2>
        <label>Name<input required value={owner.name} onChange={(e) => setOwner({ ...owner, name: e.target.value })} placeholder="e.g. Ramesh" /></label>
        <label>Phone<input required pattern="\+?[0-9]{10,13}" value={owner.phone} onChange={(e) => setOwner({ ...owner, phone: e.target.value })} placeholder="+91 98xxxxxxxx" /></label>
        <div className="row">
          <label>Language
            <select value={owner.language} onChange={(e) => setOwner({ ...owner, language: e.target.value as Lang })}>
              <option value="kn">ಕನ್ನಡ Kannada</option>
              <option value="hi">हिन्दी Hindi</option>
              <option value="en">English</option>
            </select>
          </label>
          <label>Spending limit (₹)
            <input type="number" min={0} step={100} value={owner.spending_limit_inr} onChange={(e) => setOwner({ ...owner, spending_limit_inr: Number(e.target.value) })} />
          </label>
        </div>

        <h2>Machine</h2>
        <label>Name<input required value={machine.name} onChange={(e) => setMachine({ ...machine, name: e.target.value })} /></label>
        <div className="row">
          <label>Motor speed (RPM)
            <input type="number" min={300} max={6000} value={machine.motor_rpm} onChange={(e) => setMachine({ ...machine, motor_rpm: Number(e.target.value) })} />
          </label>
          <label>Bearing
            <input value={machine.bearing_model} onChange={(e) => setMachine({ ...machine, bearing_model: e.target.value })} />
          </label>
        </div>

        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary wide" disabled={busy || backendUp === false}>
          {busy ? <Loader2 className="spin" size={18} /> : null} Save and start learning
        </button>
      </motion.form>
    </div>
  );
}
