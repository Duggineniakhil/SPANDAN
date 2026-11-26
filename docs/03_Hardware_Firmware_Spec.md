# 03 · Hardware & Firmware Spec

## 1. Sensor node bill of materials (target ≤ ₹1,500)

| Item | Part | Approx. price (₹) | Notes |
|------|------|------------------|-------|
| MCU | ESP32-WROOM-32 DevKit (or ESP32-C3 SuperMini) | 350–450 | BLE 4.2/5, enough RAM for chunked streaming |
| Accelerometer | ADXL345 module (SPI) | 150–250 | ±16 g, up to 3,200 Hz ODR, 32-sample FIFO |
| Mount | 25 mm neodymium pot magnet + M3 stud, or epoxy-bonded steel washer | 100–150 | Magnet on bearing housing; stiff mount = good high-frequency response |
| Enclosure | Small ABS box, cable gland | 80 | Keep accelerometer outside the box, on the magnet |
| Cable | 4-core shielded, 50 cm | 50 | Accelerometer ↔ ESP32 |
| Power | 5 V USB adapter + cable (mains) | 150 | No battery in prototype; mill has mains |
| Misc | Perfboard, headers, status LED | 50 | |
| **Total** | | **≈ 950–1,250** | |

**Upgrade option (if budget allows):** ADXL355 (low noise, 4 kHz) for cleaner bearing signatures. Do **not** use MPU6050 — its accelerometer bandwidth is too low for bearing faults.

## 2. Wiring (ESP32 ↔ ADXL345 over SPI)

| ADXL345 | ESP32 |
|---------|-------|
| VCC | 3V3 |
| GND | GND |
| CS | GPIO 5 |
| SDO (MISO) | GPIO 19 |
| SDA (MOSI) | GPIO 23 |
| SCL (SCLK) | GPIO 18 |
| INT1 | GPIO 4 (FIFO watermark interrupt) |

SPI clock 5 MHz. Mount the sensor with the Y axis radial (perpendicular to the shaft), the most sensitive direction for bearing and imbalance faults.

## 3. Sampling plan

| Parameter | Value | Reason |
|-----------|-------|--------|
| ODR | 3,200 Hz | ADXL345 maximum; Nyquist 1.6 kHz |
| Range | ±16 g, full resolution | Avoid clipping on impacts |
| Window | 10 s every 60 s | Frequency resolution 0.1 Hz; low duty cycle |
| Samples / window | 32,000 per axis | |
| Payload / window | 192 KB (3 axes × int16) | Streamed in chunks |

**Why 3.2 kHz is enough for the target faults:** for a 2,880 RPM motor (48 Hz) with a 6205 bearing, BPFO ≈ 3.58 × 48 ≈ 172 Hz, BPFI ≈ 5.42 × 48 ≈ 260 Hz, BSF ≈ 2.36 × 48 ≈ 113 Hz. Their first few harmonics, 1×/2× shaft (imbalance/misalignment) and 100 Hz electrical line all sit well below 1.6 kHz. Limitation: classic high-frequency envelope demodulation (resonances at 3–10 kHz) is out of reach; we do envelope analysis on the 500–1,500 Hz band instead and state this honestly.

## 4. Firmware design (PlatformIO, Arduino-ESP32 + NimBLE)

```
setup(): init SPI, configure ADXL345 (BW_RATE=0x0F → 3200 Hz, DATA_FORMAT=FULL_RES|±16g, FIFO stream mode, watermark 16)
         init BLE GATT server, advertise "SPANDAN-<last4mac>"
loop:    every 60 s (or on phone command):
           send WINDOW_START header
           for 10 s: on FIFO watermark IRQ → read 16 samples → append to 4 KB chunk buffer
                     when chunk full → notify DATA chunk (seq++)
           send WINDOW_END (sample count, CRC32)
         heartbeat notification every 30 s (uptime, RSSI, temp of ESP32)
```

Stream while sampling (don't buffer the whole 192 KB). If the phone isn't connected, skip the window (the phone, not the node, is the store).

### BLE GATT profile

Service UUID `6e400001-b5a3-f393-e0a9-e50e24dcca9e` (custom)

| Characteristic | UUID suffix | Props | Content |
|----------------|-------------|-------|---------|
| DATA | `...0003` | Notify | Chunk: `[seq u16][window_id u32][n u16][int16 x,y,z × n]` |
| CONTROL | `...0002` | Write | Commands: `START`, `STOP`, `SET_PERIOD <s>`, `SET_ODR <hz>`, `IDENTIFY` (blink LED) |
| STATUS | `...0004` | Read/Notify | `{fw, uptime, odr, period, last_window_id, dropped_chunks}` |

Negotiate MTU 247 and 2M PHY where supported. Expected throughput 40–100 KB/s ⇒ a 192 KB window takes 2–5 s, well inside the 60 s period. **Measure this in Phase 1.** If throughput is too low on the target phone: send Y at 3,200 Hz and X/Z decimated to 800 Hz (≈ 96 KB), or compute an FFT on the ESP32 and send spectra.

### Reliability
- Chunk sequence numbers; phone discards a window with missing chunks (counts it in `dropped_chunks`).
- Phone raises **sensor silent** alert if no complete window for 5 minutes.
- Watchdog timer resets ESP32 on hang; BLE auto-reconnect on the phone side.

## 5. Bench rig (stand-in for a flour mill)

Purpose: generate labelled normal and fault data from **our own** hardware, and give a live demo.

| Item | Spec | Approx. ₹ |
|------|------|-----------|
| Motor | 0.5 HP single-phase induction, 1,440 or 2,880 RPM | 3,000–4,500 |
| Shaft + 2 pillow-block bearings | UCP204 (20 mm) on a base plate | 800 |
| Coupling / pulley + V-belt | Flexible jaw coupling or pulley pair | 500 |
| Rotor disc | Steel disc with tapped holes (add bolts for imbalance) | 400 |
| Base | Steel channel or thick plywood, rubber feet | 500 |
| Spare bearings | 4–6 × UCP204 / 6204 inserts to damage deliberately | 600 |
| Safety | Guard over coupling/disc, switch with RCCB, emergency stop | 600 |

### Fault scenarios to record

| Code | Fault | How to induce (safely) | Expected signature |
|------|-------|------------------------|-------------------|
| N | Normal | Clean, aligned, tight | Baseline |
| IMB | Imbalance | Add 1–3 bolts/washers on disc | 1× shaft rises |
| MIS | Misalignment | Shim one bearing block 0.5–1 mm | 2× (and 1×) shaft, axial rises |
| LOOSE | Looseness | Loosen one mounting bolt half a turn | Many harmonics, raised noise floor |
| BRG-OR | Outer-race defect | Spark-erosion/Dremel a small pit on the outer race of a spare bearing | BPFO + harmonics, high kurtosis |
| BRG-DEG | Progressive wear | Remove grease, add fine sand to a spare bearing, run long sessions | Slowly rising RMS/kurtosis → run-to-failure trend |
| BELT | Belt slack (if pulley) | Loosen belt tension | Sub-synchronous belt frequency |

Record **sessions** (one session = one assembly state, 20–60 min), logging: date, session ID, fault code, severity, load, ambient notes. Re-assemble between sessions so normal data is not one single setup. Target at least: normal ≥ 6 sessions, each fault ≥ 3 sessions.

**Safety rules for the bench:** guard on rotating parts, no loose clothing, eye protection when running damaged bearings, stop at temperature > 70 °C or violent vibration, never leave the rig running alone.

## 6. Optional: real mill visit
One visit to a local flour mill to record 2–3 hours of normal running (with the owner's permission) is the single strongest credibility boost. Take nameplate photos (RPM, kW), bearing numbers if visible, and a short owner interview (see doc 08).
