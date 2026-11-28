# SPANDAN web app

React + Vite. Stands in for the phone gateway (Member 1's part) until the Android app and hardware exist:
a simulated sensor → vibration features → anomaly detector → health index → alerts → upload to the backend.

## Run

Start the backend first (`backend/README.md`), then:

```bash
cd frontend
cp .env.example .env        # API_TOKEN must match backend/.env
npm install
npm run dev                 # http://localhost:5173
```

The dev server proxies `/api` to the backend and adds the bearer token, so the token never reaches the browser.

## Pages

| Path | What it does |
|------|-------------|
| `/` | Landing page: background video, animated headline, illustrated how-it-works, example story, safety rules |
| `/setup` | Registers owner + machine in the backend, then starts baseline learning |
| `/monitor` | Live monitor: health ring, anomaly score vs threshold, waveform, spectrum, envelope spectrum (BPFO), fault injection, offline mode, upload status, event log, and the cloud panel: diagnosis + days left, the agent's repair plan with Approve/Reject, owner's messages |

| `/dashboard` | Judge dashboard: every machine, headline numbers, health chart, diagnosis, alert timeline, audit log |

## 3D (`src/three/`)

Built with three.js + React Three Fiber; every model is made from simple shapes in code (no downloaded models or HDRs).

| Where | What |
|-------|------|
| Landing, "inside the bearing" | A 6205 bearing pulls apart as it scrolls in; hover a part (in 3D or the list) to see the frequency it fails at (BPFO 172 Hz, BPFI 260 Hz, 2×BSF 226 Hz, FTF 19 Hz) |
| `/monitor` | Digital twin driven by the live readings: imbalance wobbles at 1×, looseness rattles, bearing wear buzzes and the casing goes x-ray to show the damage; plus a 3D spectrum waterfall of the last 48 readings |
| `/dashboard` | "Mill floor": each machine as a small motor on a plinth, glowing in its health colour, alerts pulse red; click one to select it |
| Everywhere (CSS 3D) | Cards tilt toward the mouse with a glare, sections rise in from depth, the health ring is extruded, pages swing in on navigation |

three.js loads lazily (its own ~260 kB gzip chunk) and only on devices that get 3D: not with "reduce motion",
under 4 GB RAM or 2 CPU cores, or without WebGL. Those get the 2D site (flat charts, no 3D models). Force it with
`?3d=on` / `?3d=off`. Canvases stop rendering when scrolled off screen. Labels on 3D objects are plain HTML moved
by projecting their 3D point (`PinLayer` in `kit.tsx`).

## How detection works (`src/lib/`)

| File | Role |
|------|------|
| `signal.ts` | Simulated ADXL345 at 3.2 kHz: shaft 1×/2×, 100 Hz line, noise; faults: bearing outer race (impacts at BPFO ringing a 1.2 kHz resonance), imbalance, looseness |
| `fft.ts` | Radix-2 FFT, Welch amplitude spectrum |
| `features.ts` | ~25 features (contract C1): RMS, peak, crest, kurtosis, skew, 7 band energies, 1×/2×/3×, spectral centroid/flatness, envelope RMS, envelope BPFO amplitude |
| `detector.ts` | Baseline (30 readings) → standardised-distance score → threshold → health index; 3-in-a-row alert rule. Same interface the TFLite autoencoder will use |
| `gateway.ts` | Runs the loop once per second (stands for once per minute), queues rows, uploads in batches of 10, keeps the baseline in localStorage, simulates offline + SMS |

## Test

```bash
npm test
```

Checks the FFT, statistics, fault signatures (kurtosis, BPFO envelope line, 1× rise), < 2 % false alarms on healthy data, and detection of all three faults at 50 % severity.

## Media

Put the hero background video at `public/media/hero.mp4` and list its credit in `src/media.ts`.
Use only free-licence media (e.g. Pexels / Pixabay licence). Without the file, the hero falls back to the animated vibration waves.
All illustrations are original SVGs in `src/art/`.
