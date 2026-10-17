# thermal_sweep.py - find the highest motor current the drivers can hold
# under load, in StealthChop (silent) and SpreadCycle (hiss), at each
# test speed. Runs on the board in place of the main firmware:
#
#   python3 -m mpremote connect /dev/cu.usbmodemXXXX run firmware/bench/thermal_sweep.py
#
# !! The machine's Start/Stop button does NOTHING while this runs. !!
# Ctrl-C in the terminal stops the motors. The board resets back into
# the normal firmware when the sweep finishes.
#
# Each test ramps to the speed, holds for HOLD_S seconds and watches the
# drivers' temperature flags every 2 s. A setting PASSES if neither
# driver crosses 120C. Crossing 143C aborts the test at once. From the
# starting current it searches up after a pass and down after anything
# else until the boundary is found. In StealthChop the StallGuard load
# value is logged too: higher means more torque margin, 0 is a stall.
#
# Pins, gearing and register values are those of rotocast_v4.py.

from machine import Pin, PWM, SPI, UART, reset
from time import sleep_ms, ticks_ms, ticks_diff
import framebuf
import gc

# ---------------- what to test ----------------

TEST_RPMS = (25, 12)                  # cage rpm, worst case first
CURRENTS = (8, 10, 12, 14, 16, 18, 20) # IRUN 0-31, ~ (n+1)/32 * 1.77 A rms
START_AT = 14
MODES = (("StealthChop", True), ("SpreadCycle", False))
HOLD_S = 150                           # pass = under 120C for this long
COOL_EXTRA_S = 60                      # after the flag clears, before the next test
COOL_MAX_S = 600
SAMPLE_MS = 2000

# ---------------- logging ----------------

LOG_FILE = "sweep_log.txt"            # on the board, survives a dropped USB link

def log(*args):
    line = " ".join(str(a) for a in args)
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

try:
    import os
    os.remove(LOG_FILE)
except Exception:
    pass

# ---------------- hardware ----------------

screen_buf = bytearray(160 * 80 * 2)   # before anything else, see rotocast_v4

import st7789py
import rotocast_ui as ui

M1_EN = Pin(14, Pin.OUT, value=1)
M2_EN = Pin(15, Pin.OUT, value=1)
Pin(22, Pin.OUT, value=1)              # M1 DIR
Pin(17, Pin.OUT, value=1)              # M2 DIR
m1_step = PWM(Pin(23)); m1_step.freq(1000); m1_step.duty_u16(0)
m2_step = PWM(Pin(18)); m2_step.freq(1000); m2_step.duty_u16(0)

fan = PWM(Pin(16)); fan.freq(25000); fan.duty_u16(65535)   # full for the whole sweep

uart = UART(1, baudrate=115200, tx=Pin(20), rx=Pin(21), timeout=50)

MICROSTEPS = 64
STEPS_PER_REV = 200 * MICROSTEPS
GEAR_RATIO = 4
ADDRS = (0, 1)
GCONF_BASE = 0x000001C0
MRES = 2                               # 64 microsteps

def rpm_to_hz(cage_rpm):
    return int(cage_rpm * GEAR_RATIO * STEPS_PER_REV / 60)

# ---------------- TMC2209 UART ----------------

def tmc_crc(data):
    crc = 0
    for byte in data:
        for _ in range(8):
            if (crc >> 7) ^ (byte & 1):
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
            byte >>= 1
    return crc

def tmc_write(addr, reg, value):
    p = bytearray(8)
    p[0] = 0x05; p[1] = addr & 3; p[2] = reg | 0x80
    p[3] = (value >> 24) & 0xFF; p[4] = (value >> 16) & 0xFF
    p[5] = (value >> 8) & 0xFF; p[6] = value & 0xFF
    p[7] = tmc_crc(p[:7])
    while uart.any():
        uart.read()
    uart.write(p)
    sleep_ms(3)

def tmc_read(addr, reg):
    r = bytearray(4)
    r[0] = 0x05; r[1] = addr & 3; r[2] = reg & 0x7F; r[3] = tmc_crc(r[:3])
    while uart.any():
        uart.read()
    uart.write(r)
    sleep_ms(10)
    d = uart.read(12)
    if d is None or len(d) < 12:
        return None
    rep = d[4:12]
    if rep[7] != tmc_crc(rep[:7]):
        return None
    return (rep[3] << 24) | (rep[4] << 16) | (rep[5] << 8) | rep[6]

def configure(addr, irun, stealth):
    gconf = GCONF_BASE | (0 if stealth else 0x04)        # bit 2 = en_spreadcycle
    tmc_write(addr, 0x00, gconf)
    tmc_write(addr, 0x10, (8 << 16) | (irun << 8) | 4)
    tmc_write(addr, 0x6C, 0x10010053 | (MRES << 24))
    tmc_write(addr, 0x13, 0)                              # no speed switch-over
    return gconf

def band(status):
    """Temperature band from DRV_STATUS, as a number of degrees crossed."""
    if status is None:
        return None
    if status & (1 << 11): return 157
    if status & (1 << 10): return 150
    if status & (1 << 9):  return 143
    if status & (1 << 8):  return 120
    return 0

def sample(addr, stealth):
    status = tmc_read(addr, 0x6F)
    sg = tmc_read(addr, 0x41) if stealth else None
    return band(status), sg

# ---------------- motion ----------------

ratio = 1.0
try:
    import json
    with open("settings.json") as f:
        ratio = float(json.load(f).get("ratio", 1.0))
except Exception:
    pass

def set_speed(cage_rpm):
    for pwm, en, hz in ((m1_step, M1_EN, rpm_to_hz(cage_rpm)),
                        (m2_step, M2_EN, rpm_to_hz(cage_rpm * ratio))):
        if hz > 0:
            pwm.freq(hz); pwm.duty_u16(32768); en.value(0)
        else:
            pwm.duty_u16(0); en.value(1)

def ramp(frm, to, ms=3000):
    steps = 40
    for i in range(1, steps + 1):
        set_speed(frm + (to - frm) * i / steps)
        sleep_ms(ms // steps)

def motors_off():
    m1_step.duty_u16(0); m2_step.duty_u16(0)
    M1_EN.value(1); M2_EN.value(1)

# ---------------- screen ----------------

ui.init(True)
spi = SPI(1, baudrate=24_000_000, polarity=0, phase=0, sck=Pin(10), mosi=Pin(11))
tft = st7789py.ST77xx(spi, 160, 80, reset=Pin(9, Pin.OUT), dc=Pin(8, Pin.OUT),
                      cs=Pin(12, Pin.OUT), xstart=0, ystart=24)
fb = framebuf.FrameBuffer(screen_buf, 160, 80, framebuf.RGB565)
Pin(13, Pin.OUT, value=1)

def show(title, l1="", l2="", l3="", colour=None):
    fb.fill(ui.BG)
    ui.text(fb, 2, 2, title, colour or ui.CYAN, 2)
    ui.text(fb, 2, 24, l1, ui.INK)
    ui.text(fb, 2, 40, l2, ui.INK)
    ui.text(fb, 2, 56, l3, ui.DIM)
    tft.blit_buffer(screen_buf, 0, 0, 160, 80)

def fmt_band(b):
    return "--" if b is None else ("OK" if b == 0 else ">%d" % b)

# ---------------- the tests ----------------

def wait_cool(stealth):
    """Motors off, fan on, until both drivers are under 120C, then a bit more."""
    motors_off()
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) < COOL_MAX_S * 1000:
        bands = [sample(a, False)[0] for a in ADDRS]
        show("COOLING", "M1 %s  M2 %s" % (fmt_band(bands[0]), fmt_band(bands[1])),
             "%ds" % (ticks_diff(ticks_ms(), t0) // 1000), "fan 100%", ui.AMBER)
        if all(b == 0 for b in bands):
            break
        sleep_ms(2000)
    t1 = ticks_ms()
    while ticks_diff(ticks_ms(), t1) < COOL_EXTRA_S * 1000:
        show("COOLING", "M1 OK  M2 OK", "settling %ds" % (COOL_EXTRA_S - ticks_diff(ticks_ms(), t1) // 1000), "", ui.AMBER)
        sleep_ms(1000)

def run_test(rpm, mode_name, stealth, irun):
    amps = (irun + 1) / 32 * 1.77
    label = "%s %2d/31 (%.2f A) at %d rpm" % (mode_name, irun, amps, rpm)
    log("\n=== TEST", label)
    gconfs = [configure(a, irun, stealth) for a in ADDRS]
    show(mode_name[:5].upper(), "%d/31  %.2f A" % (irun, amps), "%d rpm  ramping" % rpm, "")
    ramp(0, rpm)

    t0 = ticks_ms()
    first120 = None
    peak = 0
    sg_min = [None, None]
    dropouts = 0
    result = "PASS"

    while True:
        el = ticks_diff(ticks_ms(), t0) // 1000
        bands = []
        sgs = []
        for i, a in enumerate(ADDRS):
            g = tmc_read(a, 0x00)
            if g is not None and (g & GCONF_BASE) != GCONF_BASE:
                configure(a, irun, stealth)
                dropouts += 1
                log("   driver %d lost its settings (12V dip) - reconfigured" % a)
            b, sg = sample(a, stealth)
            bands.append(b); sgs.append(sg)
            if sg is not None and (sg_min[i] is None or sg < sg_min[i]):
                sg_min[i] = sg
        worst = max([b or 0 for b in bands])
        peak = max(peak, worst)
        log("  %3ds  M1 %-5s M2 %-5s" % (el, fmt_band(bands[0]), fmt_band(bands[1])) +
              ("   load M1 %s M2 %s" % (sgs[0], sgs[1]) if stealth else ""))
        show(mode_name[:5].upper(), "%d/31  %.2f A" % (irun, amps),
             "%d rpm  %3ds" % (rpm, el),
             "M1 %s  M2 %s" % (fmt_band(bands[0]), fmt_band(bands[1])),
             ui.RED if worst >= 120 else ui.GREEN)
        if worst >= 143:
            result = "FAIL >143C at %ds" % el
            break
        if worst >= 120 and first120 is None:
            first120 = el
        if el >= HOLD_S:
            if first120 is not None:
                result = "WARM >120C from %ds, held" % first120
            break
        sleep_ms(SAMPLE_MS)

    ramp(rpm, 0, 2000)
    motors_off()
    if dropouts:
        result += " (+%d 12V dropouts)" % dropouts
    log("  RESULT:", result,
          ("  min load M1 %s M2 %s" % (sg_min[0], sg_min[1])) if stealth else "")
    return result, first120, sg_min

def search(rpm, mode_name, stealth):
    """Walk the current ladder from START_AT until the pass/fail boundary is found."""
    results = {}
    cur = START_AT
    while True:
        wait_cool(stealth)
        res = run_test(rpm, mode_name, stealth, cur)
        results[cur] = res
        passed = res[0] == "PASS"
        i = CURRENTS.index(cur)
        nxt = None
        if passed:
            if i + 1 < len(CURRENTS) and CURRENTS[i + 1] not in results:
                nxt = CURRENTS[i + 1]
        else:
            if i - 1 >= 0 and CURRENTS[i - 1] not in results:
                nxt = CURRENTS[i - 1]
        if nxt is None:
            return results
        cur = nxt

# ---------------- main ----------------

summary = []

try:
    gc.collect()
    log("Rotocast thermal sweep: speeds", TEST_RPMS, "ratio %.2f, hold %ds, currents %s" % (ratio, HOLD_S, CURRENTS))
    log("Start/Stop button is inactive. Ctrl-C stops the motors.")
    for rpm in TEST_RPMS:
        for mode_name, stealth in MODES:
            results = search(rpm, mode_name, stealth)
            passing = [c for c, r in results.items() if r[0] == "PASS"]
            best = max(passing) if passing else None
            summary.append((rpm, mode_name, best, results))
            log("\n--- %s at %d rpm: best passing current %s" % (mode_name, rpm, best))
    motors_off()

    log("\n\n================ SUMMARY ================")
    for rpm, mode_name, best, results in summary:
        log("\n%s at %d rpm (ratio %.2f):" % (mode_name, rpm, ratio))
        for c in sorted(results):
            r = results[c]
            sg = ("  load M1 %s M2 %s" % (r[2][0], r[2][1])) if r[2][0] is not None else ""
            log("   %2d/31  %.2f A  %-32s%s" % (c, (c + 1) / 32 * 1.77, r[0], sg))
        if best is None:
            log("   -> nothing passed; lowest tested still ran hot")
        else:
            log("   -> highest clean current: %d/31 (%.2f A rms)" % (best, (best + 1) / 32 * 1.77))
    log("\nSweep done. Resetting into the normal firmware.")
    show("DONE", "sweep finished", "see console", "", ui.GREEN)
finally:
    motors_off()

sleep_ms(2000)
reset()
