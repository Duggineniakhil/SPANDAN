# 01 · Product Requirements Document (Prototype)

## 1. Goal of the prototype

Show, on a real (bench) machine, the full loop:

> vibration → anomaly on phone → fault + days-left in cloud → agent drafts repair plan → owner hears it in Kannada/Hindi → owner approves by voice → plan is executed (sandbox) → repair feedback resets baseline.

The prototype must convince judges of three things:
1. **Detection is real** — models trained and evaluated on public datasets + our own recordings, with honest metrics.
2. **The agent is useful and safe** — it does the phoning-around work but cannot act without approval.
3. **It fits Bharat** — cheap hardware, works offline, voice in local languages.

## 2. Users and personas

| Persona | Description | Needs from SPANDAN |
|---------|-------------|--------------------|
| **Owner** (primary) | Runs a 1–2 machine flour mill; basic Android phone; prefers Kannada/Hindi voice over reading | Early warning, a ready plan, a simple yes/no |
| **Mechanic** | Local freelance motor/mill mechanic | Clear job request with slot, fault, part; job card at end |
| **Dealer** | Local bearing/belt/spares shop | Quote requests in a simple format |
| **JanAI Café operator** | Helps set up sensor, phone, permissions | Setup wizard, pairing, baseline status |

## 3. Scope

### In scope (must have — P0)
- **F1 Sensor node:** ESP32 + accelerometer streams 10 s windows every minute over BLE.
- **F2 Phone gateway:** receives windows, extracts features, runs TFLite anomaly model, stores 30 days, syncs when online, SMS on high score when offline.
- **F3 Baseline learning:** per-machine baseline period (prototype: compressed to ~1–2 hours on the bench; production: 3–5 days).
- **F4 Ingestion API:** idempotent batch upload of feature rows.
- **F5 Fault diagnosis:** top-3 faults with confidence (rules on bearing fault frequencies + classifier).
- **F6 RUL estimate:** days-to-limit range or "not enough data".
- **F7 Coordinator agent:** one LLM with tools: get quotes, check mechanic availability, find idle slot, draft plan + voice script.
- **F8 Approval workflow:** rules engine with states pending → approved / rejected / expired, spending limit, 24 h reminder, never auto-approve, audit log.
- **F9 Voice:** TTS voice note in Kannada and Hindi; owner replies by voice ("haan / houdu / illa / nahi") → STT → intent. Speech provider: **Gnani API** (TTS + STT), called from the backend.
- **F10 Repair feedback:** mechanic job card (fault label) + post-repair data → new baseline.
- **F11 Owner app screens:** health score, alerts, plan card with Approve/Reject buttons (fallback to voice), false-alarm button.

### Should have (P1)
- WhatsApp sandbox delivery of the voice note and mechanic/dealer messages (Twilio or Meta Cloud API test number).
- Web dashboard for judges: live health index, anomaly score chart, plan timeline, audit log.
- Phone microphone as a second channel (UNPROCESSED audio source, features only).

### Out of scope for the prototype
- Real payments (never in scope).
- Real dealers/mechanics (simulated directory with 5–10 entries).
- Multi-tenant auth, billing, mechanic job-planner product.
- Machines other than the bench rig + one optional real mill visit.

## 4. User stories (acceptance-tested)

| ID | Story | Acceptance criteria |
|----|-------|---------------------|
| US1 | As an owner, I see my machine's health at a glance | Home screen shows health % (0–100), colour band, last reading time |
| US2 | As an owner, I am warned before a breakdown | Induced fault on bench raises an alert within 5 min; anomaly score above threshold for ≥3 consecutive windows |
| US3 | As an owner without internet, I still get warned | With mobile data off, a high score sends an SMS within 2 min |
| US4 | As an owner, I hear what's wrong and the plan in my language | Voice note in Kannada or Hindi naming fault, days left, part, price, mechanic, slot |
| US5 | As an owner, I approve or reject by voice | "Haan"/"Houdu" → approved; "Nahi"/"Illa" → rejected; unclear → asks again; nothing executes before approval |
| US6 | As an owner, my spending limit is respected | A plan above limit is never offered as approvable; agent must find cheaper option or flag "needs higher limit" |
| US7 | As an owner, I can mark a false alarm | Button records label; threshold for this machine adjusts |
| US8 | As a mechanic, I get a clear job and submit a job card | Job message has fault, part, slot; job card form records actual fault |
| US9 | As a Café operator, I can set up a machine in < 15 min | Pair sensor, name machine, enter RPM + bearing type, start baseline |
| US10 | As a judge, I can see every action the system took | Audit log lists each tool call, approval, state change with timestamp |

## 5. Non-functional requirements

| Area | Requirement |
|------|-------------|
| Cost | Sensor node BOM ≤ ₹1,500; runs on an Android 9+ phone with 3 GB RAM |
| Offline | Detection + alerting work with no internet; 30 days of features stored |
| Latency | Window → anomaly score on phone < 2 s; anomaly → plan ready < 2 min (online) |
| Privacy | No raw audio stored or uploaded; only feature rows leave the phone; data sharing needs approval |
| Safety | No payments, no machine control, no action without approval; every action audited |
| Reliability | Sensor silent > 5 min → alert; batch upload retried with idempotency keys |
| Language | All owner-facing output available in Kannada and Hindi (English for judges) |

## 6. Success metrics for the prototype

| Metric | Target (prototype) |
|--------|-------------------|
| Anomaly detection AUC (MIMII, held-out machine IDs) | ≥ 0.85 |
| False alarms per machine per week (bench, normal running) | ≤ 1 |
| Fault classification accuracy (CWRU, split by load/session) | ≥ 90 % |
| RUL interval coverage (NASA IMS) | ≥ 80 % of true failures inside predicted range |
| Bench detection lead time | Fault detected before "failure" threshold in ≥ 4/5 runs |
| Voice intent accuracy (yes/no, Kn/Hi, 40 test clips) | ≥ 95 % |
| Unauthorised actions | 0 (proved by tests) |

## 7. Assumptions & open questions
- Bench rig substitutes for a real mill; ideally one real mill recording session for credibility.
- Mill motor RPM is known (nameplate) — needed for bearing fault frequencies.
- Prototype deadline is not stated in the folder — the roadmap uses relative weeks; compress or stretch phases to fit.
