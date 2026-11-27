/**
 * Mechanic's job card (M1-27 on the phone): what was actually wrong and what was replaced.
 * It runs on the owner's phone, so it is sent from the owner's number. On success the cloud resolves the
 * alert, keeps the label for retraining, and the device learns a new baseline.
 */
import { ClipboardCheck, Loader2 } from "lucide-react";
import { useState } from "react";
import { api, type ActualFault, type Job } from "../lib/api";

export const ACTUAL_FAULTS: { id: ActualFault; label: string }[] = [
  { id: "bearing_outer", label: "Bearing outer-race wear" },
  { id: "bearing_inner", label: "Bearing inner-race wear" },
  { id: "bearing_ball", label: "Bearing ball damage" },
  { id: "imbalance", label: "Imbalance" },
  { id: "misalignment", label: "Misalignment" },
  { id: "looseness", label: "Mechanical looseness" },
  { id: "no_fault_found", label: "No fault found" },
  { id: "other", label: "Something else" },
];

export default function JobCardForm({ job, predicted, defaultPart, phone, onDone }: {
  job: Job; predicted: string | undefined; defaultPart: string | undefined; phone: string; onDone: () => void;
}) {
  const known = ACTUAL_FAULTS.some((f) => f.id === predicted);
  const [fault, setFault] = useState<ActualFault>(known ? (predicted as ActualFault) : "other");
  const [parts, setParts] = useState(defaultPart ?? "");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const parts_replaced = parts.split(",").map((p) => p.trim()).filter(Boolean);
      await api.jobCard(job.id, { actual_fault: fault, parts_replaced, notes: notes.trim(), from_phone: phone });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="job-card" onSubmit={submit}>
      <span className="kicker"><ClipboardCheck size={13} /> Job card · {job.mechanic}</span>
      <label>
        <span>What was actually wrong?</span>
        <select value={fault} onChange={(e) => setFault(e.target.value as ActualFault)}>
          {ACTUAL_FAULTS.map((f) => <option key={f.id} value={f.id}>{f.label}{f.id === predicted ? " (diagnosed)" : ""}</option>)}
        </select>
      </label>
      <label>
        <span>Parts replaced <em className="muted">(comma separated)</em></span>
        <input value={parts} onChange={(e) => setParts(e.target.value)} placeholder="6205-2RS" maxLength={200} />
      </label>
      <label>
        <span>Notes</span>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. outer race pitted" maxLength={1000} />
      </label>
      <button className="btn btn-primary" disabled={busy}>
        {busy ? <Loader2 size={15} className="spin" /> : <ClipboardCheck size={15} />} Repair done: submit job card
      </button>
      {error && <p className="error small">{error}</p>}
    </form>
  );
}
