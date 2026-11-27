"""Server-side replay (M2-34): the phone's features/detector in Python, C4 sessions, and full replays
through the API in-process (fake LLM; no network)."""
import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select

from app.agent.planner import run_planner
from app.db import SessionLocal
from app.models import AuditLog, Diagnosis
from app.replay.phone import AlertRule, fit_baseline, phone_features, welch_amplitude
from app.replay.runner import Replayer
from app.replay.sources import (ReplayWindow, c4_windows, read_meta, sim_run_to_failure, write_session)
from app.sim.vibration import generate_window
from tests.test_agent import FakeProvider, good_script
from tests.test_events_sim import setup_monitoring

FS = 3200


def tone(f=48.0, a=0.1, seconds=10, fs=FS):
    t = np.arange(int(seconds * fs)) / fs
    return a * np.sin(2 * np.pi * f * t)


# ---------- phone features + detector ----------

def test_features_on_known_signals():
    y = tone(48.0, 0.1)
    f, rpm = phone_features(0.5 * y, y, 0 * y, FS, 2880)
    assert f["rms_y"] == pytest.approx(0.1 / np.sqrt(2), rel=1e-3)
    assert f["rms_x"] == pytest.approx(0.05 / np.sqrt(2), rel=1e-3)
    assert f["crest_y"] == pytest.approx(np.sqrt(2), rel=1e-3)
    assert f["kurtosis_y"] == pytest.approx(1.5, rel=1e-2)  # a sine's kurtosis
    assert rpm == pytest.approx(2880, abs=2 * 60 * FS / 2048)  # 1× peak, within a bin or two
    assert f["amp_1x_y"] == pytest.approx(0.1, rel=0.1)  # coherent-gain corrected amplitude
    assert f["band_25_75_y"] > 100 * f["band_150_300_y"]
    assert len(f) == 22 and all(np.isfinite(v) for v in f.values())
    noise = np.random.default_rng(0).standard_normal(32000)
    assert phone_features(noise, noise, noise, FS, 2880)[0]["kurtosis_y"] == pytest.approx(3, abs=0.15)
    freqs, amp = welch_amplitude(tone(100, 1.0), FS)
    assert freqs[np.argmax(amp)] == pytest.approx(100, abs=FS / 2048)


def test_detector_separates_fault_from_normal():
    feats = lambda fault, sev, seed: phone_features(*(lambda w: (w.x, w.y, w.z))(  # noqa: E731
        generate_window(fault, sev, rpm=2880, seconds=10, seed=seed)), FS, 2880)[0]
    b = fit_baseline([feats("none", 0, s) for s in range(30)])
    healthy = [b.score(feats("none", 0, 100 + s)) for s in range(15)]
    # a single healthy reading may cross (≈0.2 % do); the 3-in-a-row rule keeps that from alerting
    assert sum(h > b.threshold for h in healthy) <= 1
    rule = AlertRule(3)
    assert not any(rule.update(h, b.threshold) == "raised" for h in healthy)
    assert b.score(feats("bearing_outer", 0.6, 7)) > 3 * b.threshold
    assert b.score(feats("imbalance", 0.6, 8)) > b.threshold
    assert b.health(b.p50) == 100 and b.health(10 * b.threshold) == 0
    rule = AlertRule(3)
    assert [rule.update(s, 1.0) for s in (2, 2, 2, 0.5, 0.5, 0.5)] == [None, None, "raised", None, None, "cleared"]
    with pytest.raises(ValueError):
        fit_baseline([feats("none", 0, 1)] * 4)


# ---------- C4 sessions ----------

def test_c4_round_trip(tmp_path):
    src = list(sim_run_to_failure("imbalance", normal=2, developing=2, seconds=1, seed=1))
    path = write_session(tmp_path / "s1", src, unit="u1", session="s1")
    meta = read_meta(path)
    assert meta["format"] == "spandan-c4" and len(meta["windows"]) == 4 and meta["windows"][3]["label"] == "imbalance"
    arr = np.load(path / "w0000.npy")
    assert arr.dtype == np.int16 and arr.shape == (FS, 3)
    back = list(c4_windows(path))
    assert np.max(np.abs(back[0].y - src[0].y)) <= 0.0039 / 2 + 1e-9  # one ADXL345 count
    assert back[3].severity == pytest.approx(src[3].severity, abs=1e-4)
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "meta.json").write_text('{"format": "other"}')
    with pytest.raises(ValueError):
        read_meta(tmp_path / "bad")


def test_sim_run_to_failure_shape():
    ws = list(sim_run_to_failure("bearing_outer", normal=3, developing=5, repaired=2, seconds=1))
    assert [w.label for w in ws] == ["normal"] * 3 + ["bearing_outer"] * 5 + ["normal"] * 2
    sev = [w.severity for w in ws[3:8]]
    assert sev == sorted(sev) and sev[-1] == pytest.approx(1.0)


# ---------- full replays through the API ----------

def replayer(client, fault, **kw):
    normal, developing, repaired = kw.pop("normal", 35), kw.pop("developing", 60), kw.pop("repaired", 0)
    ws = sim_run_to_failure(fault, normal=normal, developing=developing, repaired=repaired, seed=kw.pop("seed", 0))
    return Replayer(client, ws, count=normal + developing + repaired, unit=f"test-{fault}", **kw)


def test_full_replay_alert_plan_approve_job_card(client):
    client.post("/api/v1/sim/reset")
    r = replayer(client, "bearing_outer", repaired=32)
    r.setup(phone="+919812345678")
    r.learn_baseline()
    alert = r.monitor()
    assert alert and alert.label == "bearing_outer" and r.r.false_alerts == 0
    assert alert.index >= 35  # never during the healthy part
    top = r.r.diagnosis["faults"][0]
    assert top["fault"] == "bearing_outer" and "BPFO" in top["evidence"]
    with SessionLocal() as db:
        res = run_planner(db, uuid.UUID(alert.event_id), providers=[FakeProvider("fake", good_script)])
    assert res.status == "planned"
    assert r.get_plan(timeout_s=0)["state"] == "pending"
    assert r.approve(by="tap")["executed"] is True
    card = r.job_card()
    assert card["diagnosis_correct"] is True and card["machine_state"] == "baseline"
    assert r.relearn_after_repair() is not None
    m = client.get(f"/api/v1/machines/{r.r.machine_id}").json()
    assert m["state"] == "monitoring" and m["model_version"] == "zscore-replay-v0"
    s = r.r.summary()
    assert s["diagnosis"]["correct"] and s["job_card"]["actual_fault"] == "bearing_outer"


def test_early_unclear_alert_is_rediagnosed_as_the_fault_grows(client):
    r = replayer(client, "bearing_outer")
    r.setup()
    r.learn_baseline()
    alert = r.monitor()
    log = "\n".join(r.r.log)
    # this run alerts at ~12 % severity, before the fault has a clear signature
    assert "not clear yet" in log and "re-diagnosed" in log
    assert r.r.diagnosis["faults"][0]["fault"] == "bearing_outer"
    with SessionLocal() as db:
        diags = db.scalars(select(Diagnosis).where(Diagnosis.event_id == uuid.UUID(alert.event_id))
                           .order_by(Diagnosis.created_at)).all()
        assert [d.faults[0]["fault"] for d in diags][0] == "unknown" and diags[-1].faults[0]["fault"] == "bearing_outer"
        assert db.scalars(select(AuditLog).where(AuditLog.action == "event_rediagnosed")).first()


def test_healthy_machine_raises_no_alert(client):
    r = replayer(client, "none", normal=30, developing=60)
    r.setup()
    r.learn_baseline()
    assert r.monitor() is None and r.r.false_alerts == 0 and r.r.windows == 90
    assert client.get(f"/api/v1/events?machine_id={r.r.machine_id}").json() == []


def test_rediagnosis_only_for_unclear_unplanned_alerts(client, machine):
    setup_monitoring(client, machine)
    mid = machine["id"]
    win = lambda f, s, seed: generate_window(f, s, rpm=2880, seconds=2, seed=seed).y.round(5).tolist()  # noqa: E731
    up = lambda f, s: client.post(f"/api/v1/machines/{mid}/windows", json={  # noqa: E731
        "kind": "alert", "ts": datetime.now(UTC).isoformat(), "fs": FS, "rpm": 2880,
        "windows": [win(f, s, k) for k in (1, 2, 3)]}).json()
    assert up("none", 0)["rediagnosed"] is False  # no open alert
    client.post("/api/v1/events/anomaly", json={"machine_id": mid, "started_at": datetime.now(UTC).isoformat(),
                                                "peak_score": 9})
    assert up("none", 0)["rediagnosed"] is False  # still unclear
    assert up("bearing_inner", 0.6)["rediagnosed"] is True
    assert up("bearing_outer", 0.6)["rediagnosed"] is False  # already clear: not overwritten


def test_cli_runs_a_replay(client, monkeypatch, capsys):
    import json

    import app.replay.__main__ as cli
    monkeypatch.setattr(cli.httpx, "Client", lambda **kw: client)
    assert cli.main(["sim:imbalance", "--no-plan", "--normal", "30", "--developing", "40"]) == 0
    out = capsys.readouterr().out
    summary = json.loads(out[out.index("{"):])
    assert summary["alert"]["true_label"] == "imbalance" and summary["false_alerts"] == 0
    assert summary["diagnosis"]["top"] == "imbalance" and summary["diagnosis"]["correct"] is True
