# Driver thermal sweep — 2026-10-17

Which motor current the TMC2209 modules can hold under real load, in each
chopper mode, at two speeds. Run with `firmware/bench/thermal_sweep.py` on
the assembled frame with a mould loaded, the shipped regulated 12 V supply,
a fan blowing on the driver modules, ratio 2.00 (inner motor at twice the
cage speed), BTT TMC2209 V1.3 modules with heatsinks.

A setting **passes** if neither driver crosses 120 °C in 150 s of running.
**Warm** means it crossed 120 °C but never reached the 143 °C stop in 150 s.
The search starts at 14/31 and steps by 2 until the boundary is found.
StallGuard (StealthChop only) is the driver's own load reading, 0–510,
0 = stall; it only compares at equal speed.

| Mode | Cage speed | 12/31 · 0.72 A | 14/31 · 0.83 A | StallGuard min M1 / M2 at 12/31 |
|---|---|---|---|---|
| StealthChop | 25 rpm | PASS | warm from 38 s | 226 / 302 |
| SpreadCycle | 25 rpm | PASS | warm from 38 s | — |
| StealthChop | 12 rpm | PASS | warm from 27 s | 168 / 226 |
| SpreadCycle | 12 rpm | PASS | warm from 33 s | — |

## What it says

- **12/31 (0.72 A rms) is the ceiling with this cooling**, at every speed
  and in both modes. That is `TMC_RUN_CURRENT = 12`.
- **Chopper mode makes no thermal difference here.** SpreadCycle's advantage
  is at speeds this machine never reaches. StealthChop (silent) stays on at
  all speeds (`SPREAD_ABOVE_RPM = None`).
- **Slower runs hotter.** At 12 rpm the drivers crossed 120 °C sooner than at
  25 rpm, because at low speed the coils carry the full set current almost
  continuously. Long slow casts are the hard case.
- **M1 (J2) is the hot one**, even though M2 was doing twice the speed. That
  points at fan placement, not electronics: more air on J2 is the cheapest
  way to raise the ceiling.
- **Torque margin at 0.72 A is healthy** under this load (StallGuard never
  below ~170 on a 510 scale).
- 14/31 never tripped the 143 °C stop. The old controller ran these same
  modules at roughly 1.5 A with no temperature readout, so it almost
  certainly lived in the 120–143 °C band. Running there is a choice (shorter
  driver life, amber `HOT` strip on screen), not a fault.

## Earlier bench points, for the record

From the bring-up report (bare motors, no cage, heatsinks, **no fan**, 10 rpm):
8/31 held under 120 °C; 12/31 crossed 120 °C at 35 s; 16/31 reached thermal
shutdown in 20 s. The fan is worth about one current step and the
difference between a warning and a shutdown.

## To re-run

```bash
python3 -m mpremote connect /dev/cu.usbmodemXXXX run firmware/bench/thermal_sweep.py
```

The Start/Stop button is inactive while it runs; Ctrl-C stops the motors.
Speeds, currents and the hold time are constants at the top of the script.
Results also land in `sweep_log.txt` on the board.
