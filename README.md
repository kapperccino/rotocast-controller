# Rotocast Controller V4

Controller for the HackMakeMod rotational-casting machine: two stepper-driven
cages (outer and inner) that tumble a mould so resin coats the inside evenly.
V4 replaces the two-year-old Arduino controller with a custom RP2040 board
running MicroPython. It keeps the old controls — cage speed, inner/outer ratio,
run timer, one start/stop button and one knob — and adds a colour screen, an
automatic fan, TMC2209 drivers configured over UART, per-driver temperature
readout with an over-temperature stop, and settings that survive a power cycle.

## Where it stands (October 2026)

Running on the assembled frame with the shipped regulated 12 V supply:
0.72 A rms motor current (`TMC_RUN_CURRENT = 12`), StealthChop at every
speed (silent, like the original controller), a fan on the driver modules,
and the over-temperature and 12 V-dropout stops armed. This is the highest
current that stayed under 120 °C in the thermal sweep; more torque needs
more air over the J2 module (M1), which is the one that runs hot. Firmware
1.1.0. New boards are flashed by drag-and-drop and controllers are updated,
tested and watched from **https://kapperccino.github.io/rotocast-controller/**
— no software to install.

## Folder layout

| Path | What |
|---|---|
| `firmware/rotocast_v4.py` | The firmware. Goes onto the board as `main.py`. |
| `firmware/rotocast_ui.py` | The screen: layout, font, icons. `rotocast_v4.py` tells it what state to show. |
| `firmware/selftest.py` | The hardware self-test (knob held at power-up, or `selftest` over serial). |
| `firmware/st7789py.py` | Display driver (copy of `vendor/`), goes onto the board unchanged. |
| `firmware/RPI_PICO-*.uf2` | MicroPython 1.29.0 for a blank board. |
| `firmware/bench/thermal_sweep.py` | Finds the highest motor current the drivers hold under load. Runs from the Mac and pauses the firmware while it does. |
| `hardware/schematic-rev2.pdf` | Rev 2 schematic (KiCad 9). |
| `hardware/002_Rotocast_ControllerV2_Y819/` | The fab package exactly as ordered (order 2963065A_Y819). |
| `docs/Rotocast Controller V4 - Bring-Up Report.pdf` | First power-up findings: two board faults and their reworks, thermal limits, supply notes. Read this before ordering another batch. |
| `docs/thermal-sweep-2026-10-17.md` | Measured current ceiling under load, per chopper mode and speed. Where `TMC_RUN_CURRENT` comes from. |
| `docs/design_handoff_rotocast_ui/` | The screen design: spec, reference PNGs, font and icon data, interactive review board. |
| `web/index.html` | The flasher / diagnostics page, published to GitHub Pages. |
| `tools/flash.sh` | Developer flash of a connected board, blank or not. |
| `tools/build_uf2.py` | Builds the single-file release image (MicroPython + firmware). |
| `tools/build_site.py` | Assembles the Pages site with the firmware files and release. |
| `tools/verify_ui.py` | Renders every screen state on the Mac, no hardware needed. |
| `.github/workflows/pages.yml` | On every push: build the release and publish the site. |
| `vendor/` | Third-party source as downloaded. |
| `archive/` | The original 2023 Arduino firmware, its 2024 rewrite, and the bring-up test scripts. Reference only; see its README. |

## Hardware

Board `002_Rotocast_ControllerV2`, RP2040 with 2 MB flash, USB-C for power
and programming, 12 V input for the motors. Every board from the first fab
run needs the same two hand reworks before it is usable (SW3 and Q3 — see
the bring-up report and the table at the end); the self-test tells you
whether a board has had them.

| Function | Part | GPIO |
|---|---|---|
| Screen | 0.96″ IPS TFT, 160 × 80, ST7735-class, SPI1 | DC 8, RST 9, SCK 10, MOSI 11, CS 12, backlight 13 (hard-wired on after rework) |
| Start/Stop button | SW3, 12 mm tactile | 25 |
| Knob | SW5, rotary encoder with push | A 6, B 5, push 4 |
| Status LED | WS2812 addressable | 1 |
| Motor 1 (outer cage) | TMC2209 module in J2, UART address 0 | DIR 22, STEP 23, EN 14 (active low) |
| Motor 2 (inner cage) | TMC2209 module in J3, UART address 1 | DIR 17, STEP 18, EN 15 (active low) |
| Driver UART | single wire through R6, UART1 | TX 20, RX 21 |
| Fan | 12 V through Q2, PWM | 16 |

Both cages are driven through a 20-tooth motor gear onto an 80-tooth cage
gear (4:1), so the motors turn four times faster than the speed on screen.

**Use a regulated 12 V supply.** On a sagging supply (a LiPo, say) the drivers
brown out and silently revert to their pin defaults, which makes one motor run
eight times too fast. The firmware detects and repairs this every half second
and stops the run with a `12V DROPOUT` fault if it keeps happening, but the
machine should not be run that way. An unlabelled shop brick did exactly this
on the frame; the shipped supply does not.

## Operating it

Three physical controls, no touch:

- **Button** — Start / Stop.
- **Knob press** — moves the selection between `RPM` and `RATIO` (the cyan chip).
- **Knob turn** — changes the selected value immediately, also while running.
- **Knob held while powering on** — runs the hardware self-test (see Programming).

A controller plugged into a computer by USB can also be watched and driven
from the web page (see *The web flasher and dashboard*).

The screen and the status LED share one colour language:

| Colour | Column reads | Meaning |
|---|---|---|
| Red | `STOP` | Stopped. With a warning triangle: the machine stopped itself (driver overheated, or 12 V dropping out) |
| Amber | `RAMP` | Accelerating to the set speed (5 s from standstill) — the big digits show the *actual* speed and `→10` the target |
| Green | `RUN` | At speed |

Left side, top to bottom: the run timer (resets on start, holds after stop),
the cage speed in RPM (1–25), the ratio (0.00–2.00 in 0.05 steps, inner motor
runs at RPM × ratio) and the resulting inner-cage speed. Right column: state,
`M1`/`M2` driver temperature bands (`OK`, `>120`, `>143`…, or `--` if the
driver isn't answering, usually meaning no 12 V), and the fan (`100%` when a
driver is hot, `COOL` during the 90 s run-on after a stop).

A driver over 120 °C shows an amber `DRIVER n HOT - FAN MAX` strip and the
fan goes to full. Over 143 °C the machine stops and a red `OVERHEATED` strip
stays up until the next start, so you know why it stopped. A supply that
keeps dipping stops the run the same way with a red `12V DROPOUT` strip.

Speed and ratio are saved 3 s after the last knob change (`SAVED` flashes)
and restored at power-up.

## How the firmware works

Everything is in `firmware/rotocast_v4.py`, a single main loop that runs
every ~2 ms. Constants at the top are the tuning knobs; the sections below
match the section headers in the file.

**Motors.** Step pulses come from hardware PWM on the STEP pins, so the loop
never bit-bangs. `rpm_to_hz()` converts cage RPM to step frequency through
the 4:1 gearing and 64 microsteps (200 × 64 × 4 = 51 200 steps per cage
revolution). Speed ramps linearly at 25 ms intervals so 0→25 RPM takes 5 s,
matching the old machine. Each driver is only enabled while it actually has
pulses, so a ratio of 0.00 leaves the inner motor de-energised.

**TMC2209 over UART.** At boot and at every start, `configure_driver()`
writes each driver's registers directly: run current `TMC_RUN_CURRENT` (see
below), hold current 4/31, 64 microsteps, the chip's default chopper timing
(`CHOPCONF 0x12010053`, 32-clock blank time), and the chopper mode.
`SPREAD_ABOVE_RPM = None` keeps **StealthChop at every speed** — silent, and
what the original controller's standalone modules did. Set it to a cage RPM
to switch to SpreadCycle (hiss) above that speed; the thermal sweep found no
cooling benefit from doing so on this machine. If a threshold is set, note
that the driver measures it in 1/256-microstep units regardless of the
microstep setting — the firmware scales for that. Without the UART setup the
module's trim pot sets the current and the MS pins set the microstepping — and
because MS1 also sets the UART address, the two modules default to
*different* microstep rates. `verify_drivers()` re-checks `GCONF` every
0.5 s while running, reconfigures if a brownout reset a driver, and after
three such resets in one run stops the machine with a `12V DROPOUT` fault.

**Thermals.** The driver reports temperature *bands*, not degrees
(`DRV_STATUS` bits for >120, >143, >150, >157 °C). `check_drivers()` reads
both every 0.5 s. Over 120 °C the fan goes to full; over 143 °C the machine
stops itself (the driver would shut its own outputs down anyway) and latches
the reason for the screen. `TMC_RUN_CURRENT` sets the motor current:
12/31 ≈ 0.72 A rms, the ceiling found by the sweep in
`docs/thermal-sweep-2026-10-17.md` (loaded frame, fan on the drivers, both
chopper modes, 12 and 25 RPM). The original controller ran the same modules
at roughly 1.5 A with no temperature readout, almost certainly inside the
120–143 °C band. Slow runs are the hard case: at low speed the coils carry
the full set current continuously. The bring-up measurements show anything
above 8/31 (0.5 A) overheats within a minute *without airflow*, so this
setting assumes a fan on J2/J3; if the machine keeps stopping with
`OVERHEATED`, that is why. M1 (J2) is the module that runs hot.

**Fan.** Not user-adjustable. 60 % while running, 100 % when a driver is
hot, 60 % for 90 s after a stop, then off. The fitted fan won't turn below
55 % duty, so the 1–100 % range is mapped onto 55–100 % and the fan gets a
400 ms full-power kick from standstill.

**Inputs.** The encoder is decoded in a hard IRQ on both A and B; this knob
has a detent at both quadrature rest states, so one click is two transitions.
The main button is debounced by edge timing. If SW3 reads permanently pressed
at boot (the unreworked footprint fault), the firmware falls back to knob tap
= start/stop, knob hold = next item, and says so on the serial console.

**Screen.** `rotocast_v4.py` builds a small state dict (`run_state()`,
`fan_state()`, temperatures, warnings) and hands it to
`rotocast_ui.draw()`, which paints the whole 160 × 80 frame into a RAM
framebuffer that is then blitted over SPI. Redraw happens every 200 ms or
immediately on input, and takes ~12 ms on the board. The layout, palette,
5 × 7 font and icons follow `docs/design_handoff_rotocast_ui/`; the font and
icons are pre-rendered to 1-bit sprites at import so each character is one
C-level blit. If colours ever look wrong on a new panel batch, flip
`SWAP_COLOUR_BYTES`.

**Serial console.** The firmware prints what it is doing (driver
configuration, temperature band changes, run/stop with settings, warnings)
at 115200 on the USB port, and takes the text commands listed under *The web
flasher and dashboard*. The easiest way to see it is the site's *Console*
tab; from a terminal, `python3 -m mpremote connect /dev/cu.usbmodemXXXX repl`
(Ctrl-] leaves). The port name depends on the USB socket — `ls
/dev/cu.usbmodem*` finds it.

## Programming a board

Everything below needs no software on the computer except Chrome. The
developer path with `mpremote` is further down.

### A blank board — drag and drop

1. Open **https://kapperccino.github.io/rotocast-controller/** → *New board*
   and download `rotocast-v4-<version>.uf2`. It contains MicroPython and the
   firmware together.
2. Hold the **BOOTSEL** button on the board while plugging in the USB cable.
   A drive called `RPI-RP2` appears.
3. Drag the `.uf2` onto it. About 25 seconds later the drive disappears and
   the board restarts into the firmware: LED red, splash screen, `STOP`.
   A "disk not ejected properly" message is normal.

The file is a linear image of the whole 2 MB flash, so a reused board ends up
identical to a blank one (saved speed/ratio are reset). It also works as a
no-tools way to update an existing controller.

### Updating a controller that already runs — from the browser

Open the same site in Chrome or Edge, plug the controller into USB, click
**Connect**, choose the `usbmodem` port, then *Update firmware* → **Install**.
About 20 seconds; saved settings are kept. The *Dashboard* shows the version
it is running.

### Self-test

Hold the **knob** down while powering the controller on (or press *Run
self-test* on the site). It shows colour bars, flashes the LED, asks for the
button and knob, reads both drivers' chip versions, jogs each motor slowly
for 3 s while watching for open or shorted coils, runs the fan, and lists
PASS/FAIL per line on the screen (knob scrolls, knob press exits). The same
report streams on the serial console. On an unreworked Rev 2 board it says
`BUTTON FAIL STUCK ON - SW3`; a dark screen with a red LED is Q3.

### Developer path

```bash
pip3 install --user mpremote littlefs-python "mpy-cross==1.29.0.post2"
```

```bash
tools/flash.sh
```

copies the source files to a connected board (blank or not — it installs
MicroPython first if it sees `RPI-RP2`) and restarts it. Saved settings are
kept, and any compiled `.mpy` copies left by a release image are removed so
the source always wins.

```bash
python3 tools/build_uf2.py
```

builds `releases/rotocast-v4-<version>.uf2` locally; the GitHub workflow
does the same on every push, so normally you never run it.

Programming over USB is safe with the motors connected: the drivers are
disabled at boot and stay disabled until Start. On USB only, the console says
`No TMC replies` and the screen shows `M1 --` / `M2 --` with `NO 12V?` — the
drivers answer once they have 12 V, and the firmware picks them up by itself.

## The web flasher and dashboard

**https://kapperccino.github.io/rotocast-controller/** — a static page that
talks to a controller over USB with Web Serial (Chrome or Edge on a Mac or
PC; not Safari, not Firefox, not phones). Source in `web/index.html`, one
file, no build step.

- **Dashboard** — live state, timer, speed, ratio, each driver's temperature
  band and StallGuard load with a chart, fan, firmware version, warnings;
  Start/Stop, set RPM and ratio, reboot.
- **Self-test** — runs the on-board test and shows prompts and results live.
- **Update firmware** — installs the site's version over the raw REPL (the
  same protocol `mpremote` uses), then restarts the controller.
- **New board** — the drag-and-drop steps and the `.uf2` download.
- **Console** — everything the controller prints, a command line, and a
  download of the thermal-sweep log.

The controller side is the *serial console* in `rotocast_v4.py`: plain-text
commands (`help`, `status`, `telemetry on`, `start`, `stop`, `rpm N`,
`ratio X`, `selftest`, `log`, `reboot`) with machine-readable replies as
`@{json}` lines, one status object a second while telemetry is on.

## Releasing a new firmware

1. Edit under `firmware/`, test with `tools/flash.sh`.
2. Bump `FW_VERSION` in `firmware/rotocast_v4.py`.
3. Commit and push to `main`.

Within a minute the GitHub Actions workflow (`.github/workflows/pages.yml`)
compiles the modules, builds the `.uf2`, and republishes the site. Anyone who
reloads the page gets the new version; the dashboard shows what each
controller is running.

## Working on the screen without a board

```bash
python3 tools/verify_ui.py
```

renders every state (stopped, ramping, running, hot, fault, no drivers,
cooldown, splash, and a max-values check) to `tools/renders/*_8x.png` using a
desktop stand-in for MicroPython's `framebuf`. Add `--diff-handoff` to
compare against the designer's reference PNGs pixel for pixel — the right
column and splash match exactly; the left side has since been changed at the
operator's request (larger labels, left of the numbers), so expect
differences there.

## Known hardware issues (Rev 2)

From the bring-up report; both built boards were reworked by hand.

| Item | Problem | Rework / fix for Rev 3 |
|---|---|---|
| SW3 | Signal and ground on legs from the same internal rail — button reads pressed forever | Leg lifted and jumpered. Use pads 2 & 4 or 1 & 3. |
| Q3 | Symbol pinout is C-B-E, the SOT-23 part is B-E-C — backlight never switches | Q3 removed, collector pad bridged to ground; backlight always on. Fix the symbol, and pull R21 to ground rather than 3V3. |
| J2/J3 thermals | Drivers overheat above ≈0.5 A with no airflow, which limits torque | Aim the fan at the drivers or add a thermal path in Rev 3. |
| `/BTN` clearance | 0.065 mm to ground pour near C19 (below fab minimum) | Open to 0.2 mm. |
| 12 V supply | Battery sag resets the drivers | Specify a regulated supply. |
