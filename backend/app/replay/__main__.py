"""Replay a recording through the whole cloud pipeline, as a phone would (M2-34).

    python -m app.replay sim:bearing_outer                       # simulated run to failure, stop at the plan
    python -m app.replay sim:imbalance --approve tap --job-card  # ... approve, job card, new baseline
    python -m app.replay ../ml/results/c4/cwru-bearing_outer-007-load1 --baseline 20
    python -m app.replay sim:none --developing 0 --normal 200    # healthy machine: counts false alerts

Needs the backend running (`--api`, default http://localhost:8000) and `POST /api/v1/sim/reset` done
once. The API token comes from backend/.env. The agent plans in the background as usual (`--plan-now`
runs it synchronously instead). `--approve voice` speaks the owner's "yes" with Gnani TTS.
"""
import argparse
import json
import sys

import httpx

from app.config import get_settings
from app.replay.runner import Replayer, ReplayError
from app.replay.sources import open_source, read_meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.replay", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="sim:<fault> (none, imbalance, misalignment, looseness, bearing_outer, "
                                  "bearing_inner, bearing_ball) or a C4 session folder")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--baseline", type=int, default=30, help="windows to learn the baseline from (phone: 30)")
    p.add_argument("--language", default="kn", choices=["kn", "hi", "en"])
    p.add_argument("--owner-id", help="use an existing owner instead of creating one")
    p.add_argument("--keep-going", action="store_true", help="stream the whole source instead of stopping at the alert")
    p.add_argument("--no-plan", action="store_true", help="stop after the diagnosis")
    p.add_argument("--plan-now", action="store_true", help="run the agent synchronously")
    p.add_argument("--approve", choices=["tap", "voice"], help="approve the plan as the owner")
    p.add_argument("--job-card", action="store_true", help="after approval: job card with the true label, new baseline")
    sim = p.add_argument_group("simulated source")
    sim.add_argument("--normal", type=int, default=40)
    sim.add_argument("--developing", type=int, default=60)
    sim.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)

    if a.source.startswith("sim:"):
        repaired = a.baseline + 2 if a.job_card else 0
        windows, info = open_source(a.source, normal=a.normal, developing=a.developing, seed=a.seed, repaired=repaired)
        count = a.normal + a.developing + repaired
    else:
        windows, info = open_source(a.source)
        count = len(read_meta(a.source)["windows"])

    s = get_settings()
    client = httpx.Client(base_url=a.api, headers={"Authorization": f"Bearer {s.api_token}"}, timeout=200)
    r = Replayer(client, windows, count=count, unit=info["unit"] or "replay", bearing_model=info["bearing_model"] or "6205-2RS",
                 rpm=float(info["rpm"] or 2880), baseline_windows=a.baseline,
                 reading_interval_min=s.reading_interval_min, log=lambda m: print("·", m, flush=True))
    try:
        r.setup(language=a.language, owner_id=a.owner_id)
        r.learn_baseline()
        alert = r.monitor(stop_at_alert=not a.keep_going)
        if alert and not a.no_plan and r.get_plan(plan_now=a.plan_now) and a.approve:
            r.approve(by=a.approve)
            if a.job_card and r.r.decision.get("executed"):
                r.job_card()
                r.relearn_after_repair()
    except ReplayError as e:
        print("replay failed:", e, file=sys.stderr)
        print(json.dumps(r.r.summary(), indent=1, default=str))
        return 1
    print(json.dumps(r.r.summary(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
