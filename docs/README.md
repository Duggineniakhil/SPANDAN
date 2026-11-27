# SPANDAN — Prototype Documentation Pack

Team CREED · Amrita Vishwa Vidyapeetham · Tech4Bharat 2026 (JanAI Mass Entrepreneurship Challenge)
Theme: Manufacturing & Industry · PS 4.3 Machine breakdowns · Track: Agentic AI

SPANDAN predicts breakdowns in small flour mills. A clip-on vibration sensor sends readings to an Android phone. The phone detects anomalies offline. Cloud models diagnose the fault and estimate days left. One LLM agent drafts a repair plan (part, mechanic, slot, cost). The owner approves or rejects it by voice in Kannada or Hindi.

## Documents (read in this order)

| # | Document | What it answers |
|---|----------|-----------------|
| 01 | [Product Requirements (PRD)](01_PRD.md) | What the prototype must do, for whom, and what "done" means |
| 02 | [System Architecture](02_System_Architecture.md) | Components, data flow, tech stack, repo layout, deployment |
| 03 | [Hardware & Firmware Spec](03_Hardware_Firmware_Spec.md) | Bill of materials, wiring, sampling, BLE protocol, bench rig |
| 04 | [Android App Spec](04_Android_App_Spec.md) | Phone gateway: BLE, features, TFLite, storage, sync, SMS, UI |
| 05 | [ML Models Spec](05_ML_Models_Spec.md) | Datasets, features, 3 models, evaluation protocol, export |
| 06 | [Agent & Approval Workflow Spec](06_Agent_Workflow_Spec.md) | LLM coordinator, tools, rules engine, approval state machine, voice |
| 07 | [API & Data Model](07_API_Data_Model.md) | REST endpoints, payloads, PostgreSQL schema |
| 08 | [Test, Demo & Risk Plan](08_Test_Demo_Risk_Plan.md) | Testing, the demo script, metrics to report, risks |
| 09 | [Roadmap](09_Roadmap.md) | Phase-by-phase build plan with tasks, owners and exit criteria |
| 10 | [Task Split — Two Members](10_Task_Split_Two_Members.md) | Software-only development tasks (hardware deferred) for Member 1 (Edge & Detection) and Member 2 (Cloud & Intelligence) |
| 11 | [Member 1 Sync Guide](11_Member1_Sync_Guide.md) | What the cloud already does, the exact API the phone must use, and the build order for Member 1 |

## Golden rules for the whole build

1. **The demo must work end to end before any part is polished.** Build a thin slice through every box first (Phase 1 in the roadmap).
2. **Only one LLM component.** Detection, diagnosis and RUL are trained models. Quote comparison, scheduling and approvals are rules.
3. **No action without owner approval.** No reply means no action. The system never pays or starts/stops a machine.
4. **No data leakage.** Train/test splits are by machine and session, never random windows.
5. **Everything external is sandboxed** in the prototype: dealers, mechanics and WhatsApp are simulated or use sandbox numbers.
