
# Rotocast Controller V4
#
# Keeps the controls from the machine that has been running for two
# years (speed in RPM, ratio for the inside motor, run timer, start/
# stop button, knob to pick a menu item and set it) and adds the new
# hardware: an automatic fan, the colour screen and TMC2209 drivers on
# UART.
#
#   Button     = start / stop
#   Knob press = next menu item (SPEED / RATIO)
#   Knob turn  = change the selected item
#
# MOTOR 2 is the inside motor. Its speed is RPM * ratio.
#
# The screen layout lives in rotocast_ui.py, which follows the designer's
# handoff in docs/design_handoff_rotocast_ui/. This file decides what
# state the screen shows; that one decides how it looks.
#
# Goes onto the board as main.py - see README.md and tools/flash.sh.

from machine import Pin, PWM, SPI, UART, disable_irq, enable_irq
from time import sleep_ms, ticks_ms, ticks_diff, ticks_add
import micropython
import framebuf
import neopixel
import gc

# The screen's framebuffer (160 x 80 x 2 bytes) is the one big
# allocation. Take it now, before the modules below are compiled and
# the UI builds its font sprites: asked for later, the heap is too
# fragmented for a 25.6 KB block even with 200 KB free, and the board
# dies at boot with a MemoryError and a dark screen.
gc.collect()
screen_buf = bytearray(160 * 80 * 2)

import st7789py
import rotocast_ui as ui
import sys
import select
import json

micropython.alloc_emergency_exception_buf(100)

# Shown on the splash screen and reported over serial. Bump it when the
# behaviour changes; tools/build_uf2.py names the release file after it.
FW_VERSION = "1.1.0"

# ============================================================
# PINS (from the V4 PCB netlist)
# ============================================================

TFT_DC   = 8
TFT_RST  = 9
TFT_SCK  = 10
TFT_MOSI = 11
TFT_CS   = 12
TFT_BL   = 13

BTN_PIN    = 25
ENC_A_PIN  = 6
ENC_B_PIN  = 5
ENC_SW_PIN = 4

M1_DIR_PIN  = 22
M1_STEP_PIN = 23
M1_EN_PIN   = 14   # active LOW
M2_DIR_PIN  = 17
M2_STEP_PIN = 18
M2_EN_PIN   = 15   # active LOW

FAN_PIN = 16
LED_PIN = 1

TMC_UART_ID = 1
TMC_UART_TX = 20
TMC_UART_RX = 21

# ============================================================
# MACHINE SETTINGS
# ============================================================

MICROSTEPS     = 64          # set over UART, matches the old machine
STEPS_PER_REV  = 200 * MICROSTEPS

# 20 tooth gear on the motor drives an 80 tooth gear on the cage, on
# both motors. Speeds on screen are CAGE rpm, so the motor turns four
# times faster. This matches the old machine, whose STEPS_PER_ROT of
# 12800 was 3200 motor steps (1/16 microstepping) times the 4:1
# gearing, i.e. one cage revolution - so its 25 rpm was 25 at the cage,
# same as here.
MOTOR_TEETH = 20
CAGE_TEETH = 80
GEAR_RATIO = CAGE_TEETH / MOTOR_TEETH

MIN_RPM = 1
MAX_RPM = 25                 # at the cage
MIN_RATIO = 0.0
MAX_RATIO = 2.0
RATIO_STEP = 0.05

M1_REVERSE = False
M2_REVERSE = False

RAMP_MS = 5000               # 0 -> full speed, as on the old machine
RAMP_UPDATE_MS = 25
RPM_RAMP_STEP = MAX_RPM * RAMP_UPDATE_MS / RAMP_MS

KNOB_REVERSED = True

# The fan is not a menu item, it looks after itself. It runs while the
# motors run, goes to full if a driver reports over 120C, keeps going
# for a while after a run to carry the heat away, then stops.
FAN_RUN_PCT = 60
FAN_HOT_PCT = 100
FAN_COOLDOWN_MS = 90000

FAN_PWM_HZ = 25000
FAN_RAMP_STEP = 2
FAN_RAMP_UPDATE_MS = 30

# This fan will not turn below about 55% duty, so the 1-100% on screen
# is mapped onto the part of the range where it actually runs, and it
# gets a short full-power kick to get it moving from stopped.
FAN_MIN_DUTY_PCT = 55
FAN_KICK_MS = 400

TMC_ADDRESSES = (0, 1)       # M1 = 0, M2 = 1 (set by the MS1 straps)
# Motor current, 0-31. On these modules (0.11 ohm sense) the rms current
# is about (n + 1) / 32 * 1.77 A:  8 = 0.50 A, 14 = 0.83 A, 16 = 0.94 A,
# 20 = 1.16 A, 24 = 1.38 A, 31 = 1.77 A.
#
# The old machine ran the same BTT TMC2209 modules in standalone mode
# with the pot at 7/8 turn, roughly 1.5 A rms, with no way to see how
# hot they got. The sweep in docs/thermal-sweep-2026-10-17.md (loaded
# frame, fan on the drivers, ratio 2.0) found 12/31 the highest setting
# that stays under 120C at both 12 and 25 rpm, in either chopper mode;
# 14/31 sits in the 120-143C warning band but never trips the stop.
# Anything above 8 NEEDS A FAN ON THE DRIVER MODULES; the
# over-temperature stop will end the run otherwise. Better airflow over
# J2 (M1 runs hottest) is what buys more current.
TMC_RUN_CURRENT = 12
TMC_HOLD_CURRENT = 4
USE_TMC_UART_CONFIG = True

# StealthChop is silent; SpreadCycle hisses but runs cooler and holds
# torque better at speed. The old machine was silent at every speed, so
# None here keeps StealthChop throughout and relies on the fan over the
# drivers. Set a cage rpm instead to switch to SpreadCycle above it
# (6 was the earlier compromise) if the drivers run hot.
SPREAD_ABOVE_RPM = None
TMC_CLOCK_HZ = 12000000

LONG_PRESS_MS = 800
DEBOUNCE_MS = 40
UI_UPDATE_MS = 200
SPLASH_MS = 1000             # boot screen
SAVED_SHOW_MS = 1000         # how long "SAVED" stays up

# Settings are remembered across power cycles
SETTINGS_FILE = "settings.json"
SETTINGS_SAVE_DELAY_MS = 3000

# The drivers are watched while running; over 143C they are stopped.
# A driver whose 12V dips forgets its settings and comes back on its
# trim pot current, so the check is frequent to keep that short, and a
# run that loses settings this many times is stopped as a power fault.
DRIVER_CHECK_MS = 500
POWER_FAULT_RESETS = 3

# Flip if the screen's colours look wrong once you can see it
SWAP_COLOUR_BYTES = True
INVERT_DISPLAY = False

# ============================================================
# SAFETY FIRST
# ============================================================

m1_en = Pin(M1_EN_PIN, Pin.OUT, value=1)     # disabled
m2_en = Pin(M2_EN_PIN, Pin.OUT, value=1)

fan_pwm = PWM(Pin(FAN_PIN))
fan_pwm.freq(FAN_PWM_HZ)
fan_pwm.duty_u16(0)

# ============================================================
# STATE
# ============================================================

OPT_SPEED = 0
OPT_RATIO = 1
OPT_COUNT = 2

selected = OPT_SPEED

running = False
rpm_target = 10               # what the knob sets
rpm_now = 0.0                 # what the motors are actually doing
ratio = 1.0
fan_now = 0
driver_temp = {}              # driver address -> 'OK', '>120' ... '>157', '--'
driver_load = {}              # driver address -> StallGuard value while running (0 = stall, 510 = free)

run_started_ms = 0
run_time_ms = 0
run_stopped_ms = 0            # when the motors last stopped, for the fan
drivers_hot = False
driver_resets = 0             # settings lost to a 12V dip, this run
driver_reset_addr = 0         # which driver lost them last

m1_applied_hz = -1
m2_applied_hz = -1
fan_applied = -1
fan_kick_ms = 0

last_ramp_ms = 0
last_fan_ms = 0
last_ui_ms = 0
last_driver_check_ms = 0
settings_dirty_ms = 0
saved_ms = 0                  # when settings were last written

# Warnings are ('hot', n) or ('over', n) with n the motor number as the
# screen names it, or None.
driver_warning = None         # what the drivers report right now
stop_reason = None            # why the machine stopped itself, until next start

# ============================================================
# SAVED SETTINGS
# ============================================================

def load_settings():
    global rpm_target, ratio

    try:
        import json

        with open(SETTINGS_FILE) as f:
            data = json.load(f)

        rpm_target = int(clamp(data.get("rpm", rpm_target), MIN_RPM, MAX_RPM))
        ratio = round(clamp(data.get("ratio", ratio), MIN_RATIO, MAX_RATIO), 2)
        print("settings loaded:", rpm_target, "RPM, ratio", ratio)
    except Exception:
        print("no saved settings, using defaults")

def save_settings():
    global settings_dirty_ms, saved_ms

    settings_dirty_ms = 0

    try:
        import json

        with open(SETTINGS_FILE, "w") as f:
            json.dump({"rpm": rpm_target, "ratio": ratio}, f)

        saved_ms = ticks_ms()
    except Exception as e:
        print("could not save settings:", e)

# ============================================================
# SCREEN
# ============================================================

WIDTH = 160
HEIGHT = 80
XSTART = 0
YSTART = 24

Pin(TFT_BL, Pin.OUT, value=1)                # backlight is hard-wired on

spi = SPI(1, baudrate=24_000_000, polarity=0, phase=0,
          sck=Pin(TFT_SCK), mosi=Pin(TFT_MOSI))

tft = st7789py.ST77xx(spi, WIDTH, HEIGHT,
                      reset=Pin(TFT_RST, Pin.OUT), dc=Pin(TFT_DC, Pin.OUT),
                      cs=Pin(TFT_CS, Pin.OUT), xstart=XSTART, ystart=YSTART)

ui.init(SWAP_COLOUR_BYTES)

def init_screen():
    tft.hard_reset()
    tft.write(0x01)
    sleep_ms(150)
    tft.write(0x11)
    sleep_ms(255)
    tft.write(0x3A, b'\x05')
    tft.write(0x36, b'\x68')
    tft.write(0x21 if INVERT_DISPLAY else 0x20)
    tft.write(0x13)
    tft.write(0x29)
    sleep_ms(50)

buf = screen_buf             # allocated at the top of the file
fb = framebuf.FrameBuffer(buf, WIDTH, HEIGHT, framebuf.RGB565)

def format_time(ms):
    seconds = ms // 1000
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)

def run_state():
    if stop_reason:
        return 'fault'
    if not running:
        return 'stopped'
    if abs(rpm_now - rpm_target) > 0.05:
        return 'ramping'
    return 'running'

def fan_state(now):
    if fan_now <= 0 and fan_wanted(now) == 0:
        return 'off'
    if drivers_hot:
        return 'max'
    if running:
        return 'run'
    return 'cool'

def draw_screen():
    now = ticks_ms()
    m1 = driver_temp.get(TMC_ADDRESSES[0], '--')
    m2 = driver_temp.get(TMC_ADDRESSES[1], '--')

    ui.draw(fb, {
        'state': run_state(),
        'timer': format_time(run_time_ms),
        'rpm': rpm_target,
        'actual': int(rpm_now + 0.5),
        'ratio': ratio,
        'sel': 'rpm' if selected == OPT_SPEED else 'ratio',
        'm1': m1,
        'm2': m2,
        'fan': fan_state(now),
        'warn': stop_reason or driver_warning,
        'no_drivers': m1 == '--' and m2 == '--',
        'saved': saved_ms != 0 and ticks_diff(now, saved_ms) < SAVED_SHOW_MS,
    })

    tft.blit_buffer(buf, 0, 0, WIDTH, HEIGHT)

# ============================================================
# LED
# ============================================================

np = neopixel.NeoPixel(Pin(LED_PIN), 1)
led_last = None

def update_led():
    global led_last

    if running:
        if abs(rpm_now - rpm_target) > 0.05:
            colour = (60, 40, 0)      # ramping
        else:
            colour = (0, 60, 0)       # running
    else:
        colour = (40, 0, 0)           # idle

    if colour != led_last:
        np[0] = colour
        np.write()
        led_last = colour

# ============================================================
# TMC2209 over UART
# ============================================================

if USE_TMC_UART_CONFIG:
    uart = UART(TMC_UART_ID, baudrate=115200,
                tx=Pin(TMC_UART_TX), rx=Pin(TMC_UART_RX), timeout=50)

    def tmc_crc(data):
        crc = 0

        for byte in data:
            for _ in range(8):
                if (crc >> 7) ^ (byte & 0x01):
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF

                byte >>= 1

        return crc

    def tmc_write(addr, reg, value):
        packet = bytearray(8)
        packet[0] = 0x05
        packet[1] = addr & 0x03
        packet[2] = reg | 0x80
        packet[3] = (value >> 24) & 0xFF
        packet[4] = (value >> 16) & 0xFF
        packet[5] = (value >> 8) & 0xFF
        packet[6] = value & 0xFF
        packet[7] = tmc_crc(packet[:7])

        while uart.any():
            uart.read()

        uart.write(packet)
        sleep_ms(3)

    def tmc_read(addr, reg):
        """The bus is single wire, so our own request echoes back first."""
        request = bytearray(4)
        request[0] = 0x05
        request[1] = addr & 0x03
        request[2] = reg & 0x7F
        request[3] = tmc_crc(request[:3])

        while uart.any():
            uart.read()

        uart.write(request)
        sleep_ms(10)

        data = uart.read(12)

        if data is None or len(data) < 12:
            return None

        reply = data[4:12]

        if reply[7] != tmc_crc(reply[:7]):
            return None

        return (reply[3] << 24) | (reply[4] << 16) | (reply[5] << 8) | reply[6]

else:
    def tmc_write(addr, reg, value):
        pass

    def tmc_read(addr, reg):
        return None

MRES = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}

GCONF_WANTED = 0x000001C0    # pdn_disable, mstep_reg_select, multistep_filt

def configure_driver(addr):
    """Take current and microstepping away from the module's pins and
    trim pot and set them over UART. Without this the pot sets the
    current (wound high enough to cook the driver) and the MS pins set
    the microstepping - and those differ between the two modules
    because MS1 also sets the UART address."""
    tmc_write(addr, 0x00, GCONF_WANTED)
    tmc_write(addr, 0x10, (8 << 16) | (TMC_RUN_CURRENT << 8) | TMC_HOLD_CURRENT)

    # CHOPCONF: the chip's own power-up values (toff 3, hstrt 5, hend 0,
    # blank time TBL=2 i.e. 32 clocks, interpolation on) plus our
    # microstep setting. An earlier version wrote TBL=0 (16 clocks),
    # which is only meant for low-current use and lets switching noise
    # trip the current comparator early - less current than set, and
    # more chopper noise.
    tmc_write(addr, 0x6C, 0x10010053 | (MRES[MICROSTEPS] << 24))

    # Above SPREAD_ABOVE_RPM the driver leaves StealthChop for
    # SpreadCycle. The driver measures TSTEP in clocks per 1/256
    # microstep whatever MRES is set to, so our 1/64 input steps have
    # to be scaled by 64/256 or the switch happens at a quarter of the
    # intended speed. A faster speed means a smaller TSTEP. A threshold
    # of 0 turns the switch off: StealthChop at every speed.
    if SPREAD_ABOVE_RPM is None:
        tmc_write(addr, 0x13, 0)
    else:
        spread_hz = SPREAD_ABOVE_RPM * GEAR_RATIO * STEPS_PER_REV / 60
        tmc_write(addr, 0x13, int(TMC_CLOCK_HZ * MICROSTEPS / (256 * spread_hz)))

def init_drivers(quiet=False):
    found = []

    for addr in TMC_ADDRESSES:
        configure_driver(addr)

        if tmc_read(addr, 0x00) is not None:
            found.append(addr)

    if not quiet:
        if found:
            print("TMC2209 drivers configured at", found)
        else:
            print("No TMC replies - check 12V and that the modules are seated")

    return found

def verify_drivers():
    """A driver forgets everything when its 12V goes away, and comes back
    running off its pins and pot instead. That makes one motor run many
    times too fast, so check and put the settings back."""
    global driver_resets, driver_reset_addr

    for addr in TMC_ADDRESSES:
        gconf = tmc_read(addr, 0x00)

        if gconf is None:
            continue

        if (gconf & GCONF_WANTED) != GCONF_WANTED:
            configure_driver(addr)
            driver_resets += 1
            driver_reset_addr = addr
            print("driver %d lost its settings (12V cycled?) - reconfigured" % addr)

def driver_status(addr):
    value = tmc_read(addr, 0x6F)

    if value is None:
        return "no reply"

    faults = []

    for bit, name in ((0, "OVERTEMP-WARN"), (1, "OVERTEMP"), (2, "SHORT-A"),
                      (3, "SHORT-B"), (6, "OPEN-A"), (7, "OPEN-B")):
        if value & (1 << bit):
            faults.append(name)

    return "current=%d/31 %s" % ((value >> 16) & 0x1F,
                                 " ".join(faults) if faults else "ok")

def temp_band(value):
    """The driver reports thresholds crossed, not a temperature."""
    if value & (1 << 11):
        return ">157C"
    if value & (1 << 10):
        return ">150C"
    if value & (1 << 9):
        return ">143C"
    if value & (1 << 8):
        return ">120C"
    return "<120C"

def temp_short(value):
    """The band as the screen shows it."""
    if value is None:
        return '--'
    if value & (1 << 11):
        return '>157'
    if value & (1 << 10):
        return '>150'
    if value & (1 << 9):
        return '>143'
    if value & (1 << 8):
        return '>120'
    return 'OK'

last_band = {}

def check_drivers():
    """Watch driver temperature while running. Over 143C the driver would
    shut its own output down, so stop the machine and say why."""
    global driver_warning, last_driver_check_ms, drivers_hot

    now = ticks_ms()

    if ticks_diff(now, last_driver_check_ms) < DRIVER_CHECK_MS:
        return False

    last_driver_check_ms = now
    warning = None
    too_hot = False
    hot = False

    verify_drivers()

    for addr in TMC_ADDRESSES:
        value = tmc_read(addr, 0x6F)
        driver_temp[addr] = temp_short(value)

        # StallGuard only means something with the motor turning in
        # StealthChop; it is the dashboard's torque-margin reading.
        if running and rpm_now > 0.5 and value is not None:
            driver_load[addr] = tmc_read(addr, 0x41)
        else:
            driver_load[addr] = None

        if value is None:
            continue

        band = temp_band(value)

        if last_band.get(addr) != band:
            last_band[addr] = band
            print("driver %d temperature %s at %d rpm" % (addr, band, rpm_target))

        if value & (1 << 8):          # over 120C, the fan's cue
            hot = True

        # Named as the screen names them, M1 and M2, not by address
        if value & (1 << 1):          # over 143C
            too_hot = True
            warning = ('over', addr + 1)
        elif value & (1 << 0) and not warning:
            warning = ('hot', addr + 1)

    # A supply that keeps dropping out puts the drivers back on their pot
    # current, which is what overheats them. Stop and say so.
    if running and driver_resets >= POWER_FAULT_RESETS:
        too_hot = True
        warning = ('power', driver_reset_addr + 1)

    drivers_hot = hot
    driver_warning = warning

    if warning:
        print("M%d %s" % (warning[1], {'over': "OVERHEATED", 'hot': "HOT",
                                      'power': "12V DROPOUT"}[warning[0]]))

    return too_hot

# ============================================================
# MOTORS
# ============================================================

m1_dir = Pin(M1_DIR_PIN, Pin.OUT, value=0 if M1_REVERSE else 1)
m2_dir = Pin(M2_DIR_PIN, Pin.OUT, value=0 if M2_REVERSE else 1)

m1_step = PWM(Pin(M1_STEP_PIN))
m2_step = PWM(Pin(M2_STEP_PIN))
m1_step.freq(1000)
m2_step.freq(1000)
m1_step.duty_u16(0)
m2_step.duty_u16(0)

def rpm_to_hz(cage_rpm):
    """Cage rpm -> step pulses per second, through the 4:1 gearing."""
    return int(cage_rpm * GEAR_RATIO * STEPS_PER_REV / 60)

def set_step_pwm(pwm, hz, applied):
    if hz == applied:
        return applied

    if hz <= 0:
        pwm.duty_u16(0)
        return 0

    pwm.freq(hz)
    pwm.duty_u16(32768)
    return hz

def update_motors(force=False):
    global rpm_now, m1_applied_hz, m2_applied_hz, last_ramp_ms

    now = ticks_ms()

    if not force and ticks_diff(now, last_ramp_ms) < RAMP_UPDATE_MS:
        return

    last_ramp_ms = now

    target = rpm_target if running else 0

    if rpm_now < target:
        rpm_now = min(target, rpm_now + RPM_RAMP_STEP)
    elif rpm_now > target:
        rpm_now = max(target, rpm_now - RPM_RAMP_STEP)

    m1_hz = rpm_to_hz(rpm_now)
    m2_hz = rpm_to_hz(rpm_now * ratio)

    # Each driver is only enabled while it is actually turning
    m1_en.value(0 if m1_hz > 0 else 1)
    m2_en.value(0 if m2_hz > 0 else 1)

    m1_applied_hz = set_step_pwm(m1_step, m1_hz, m1_applied_hz)
    m2_applied_hz = set_step_pwm(m2_step, m2_hz, m2_applied_hz)

def jog_motor(index, cage_rpm):
    """Drive one motor directly, no ramp. Only the self test uses this;
    update_motors() takes the outputs back afterwards."""
    pwm = (m1_step, m2_step)[index]
    en = (m1_en, m2_en)[index]
    hz = rpm_to_hz(cage_rpm)
    en.value(0 if hz > 0 else 1)
    set_step_pwm(pwm, hz, -1)

# ============================================================
# FAN
# ============================================================

def fan_wanted(now):
    """Run for heat, not for the sake of it."""
    if drivers_hot:
        return FAN_HOT_PCT

    if running:
        return FAN_RUN_PCT

    # carry the heat away for a while after the motors stop
    if run_stopped_ms and ticks_diff(now, run_stopped_ms) < FAN_COOLDOWN_MS:
        return FAN_RUN_PCT

    return 0

def update_fan(force=False):
    global fan_now, fan_applied, last_fan_ms, fan_kick_ms

    now = ticks_ms()

    if not force and ticks_diff(now, last_fan_ms) < FAN_RAMP_UPDATE_MS:
        return

    last_fan_ms = now

    target = fan_wanted(now)

    if fan_now < target:
        fan_now = min(target, fan_now + FAN_RAMP_STEP)
    elif fan_now > target:
        fan_now = max(target, fan_now - FAN_RAMP_STEP)

    # Finish a kick that is already under way
    if fan_kick_ms and ticks_diff(now, fan_kick_ms) >= FAN_KICK_MS:
        fan_kick_ms = 0
        fan_pwm.duty_u16(fan_duty(fan_applied))

    if fan_now == fan_applied:
        return

    was_stopped = fan_applied <= 0
    fan_applied = fan_now

    if fan_now <= 0:
        fan_kick_ms = 0
        fan_pwm.duty_u16(0)
        return

    if was_stopped:
        # Full power briefly to break it loose, without blocking the loop
        fan_kick_ms = now
        fan_pwm.duty_u16(65535)
    elif not fan_kick_ms:
        fan_pwm.duty_u16(fan_duty(fan_now))

def fan_duty(percent):
    """Map 1-100% onto the part of the range where this fan actually turns."""
    if percent <= 0:
        return 0
    if percent >= 100:
        return 65535

    span = 100 - FAN_MIN_DUTY_PCT
    return int(65535 * (FAN_MIN_DUTY_PCT + span * percent / 100.0) / 100)

# ============================================================
# INPUTS
# ============================================================

btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
enc_a = Pin(ENC_A_PIN, Pin.IN)
enc_b = Pin(ENC_B_PIN, Pin.IN)
enc_sw = Pin(ENC_SW_PIN, Pin.IN)

# If SW3 still has its two legs bridged, the button reads pressed for
# ever. Detect that at startup and let the knob stand in for it.
btn_faulty = False

for _ in range(20):
    if btn.value() == 1:
        break
    sleep_ms(10)
else:
    btn_faulty = True

# Quadrature decode. Index is (old_state << 2) | new_state with
# state = (A << 1) | B. This knob has a detent at both rest states, 00
# and 11, so one click is two transitions; counting only arrivals at
# 00 lost every other click.
QUAD = (0, 1, -1, 0, -1, 0, 0, 1, 1, 0, 0, -1, 0, -1, 1, 0)

enc_state = (enc_a.value() << 1) | enc_b.value()
enc_sub = 0
enc_delta = 0

def enc_irq(pin):
    global enc_state, enc_sub, enc_delta

    s = (enc_a.value() << 1) | enc_b.value()
    enc_sub += QUAD[(enc_state << 2) | s]
    enc_state = s

    if s == 0 or s == 3:
        if enc_sub >= 2:
            enc_delta += 1
        elif enc_sub <= -2:
            enc_delta -= 1

        enc_sub = 0

enc_a.irq(enc_irq, Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)
enc_b.irq(enc_irq, Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)

def take_encoder():
    """Read and clear the accumulated detents with interrupts off, so a
    turn that lands mid-read is not lost."""
    global enc_delta

    state = disable_irq()
    delta = enc_delta
    enc_delta = 0
    enable_irq(state)
    return delta

# ============================================================
# ACTIONS
# ============================================================

def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value

def next_option():
    global selected

    selected = (selected + 1) % OPT_COUNT

def start_stop():
    global running, run_started_ms, run_time_ms, driver_warning, run_stopped_ms
    global stop_reason, driver_resets

    running = not running

    if not running:
        run_stopped_ms = ticks_ms()

    if running:
        # The 12V may have been switched on after the controller, which
        # leaves the drivers on their own defaults, so set them up again.
        # That one does not count as a dropout.
        verify_drivers()
        driver_resets = 0
        run_started_ms = ticks_ms()
        run_time_ms = 0
        driver_warning = None
        stop_reason = None
    elif settings_dirty_ms:
        save_settings()

    print("RUN" if running else "STOP", "rpm", rpm_target, "ratio", ratio)

def apply_delta(delta):
    global rpm_target, ratio, settings_dirty_ms

    if delta == 0:
        return

    if KNOB_REVERSED:
        delta = -delta

    settings_dirty_ms = ticks_ms()

    if selected == OPT_SPEED:
        rpm_target = int(clamp(rpm_target + delta, MIN_RPM, MAX_RPM))
    else:
        ratio = round(clamp(ratio + delta * RATIO_STEP, MIN_RATIO, MAX_RATIO), 2)

# ============================================================
# SERIAL CONSOLE
# ============================================================
# Plain text commands on the USB serial port, for the bench and for the
# web dashboard. Machine-readable lines start with '@' and carry one
# JSON object; everything else is for people. 'help' lists commands.

poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
cmd_buf = ""
telemetry = False             # 'telemetry on' streams status once a second
last_telemetry_ms = 0
TELEMETRY_MS = 1000

def emit(obj):
    print("@" + json.dumps(obj))

def status_dict():
    now = ticks_ms()
    gc.collect()                  # so "mem" means something
    return {
        "fw": FW_VERSION, "up": now // 1000,
        "state": run_state(), "run_ms": run_time_ms,
        "rpm": rpm_target, "actual": round(rpm_now, 1), "ratio": ratio,
        "sel": 'rpm' if selected == OPT_SPEED else 'ratio',
        "m1": driver_temp.get(TMC_ADDRESSES[0], '--'),
        "m2": driver_temp.get(TMC_ADDRESSES[1], '--'),
        "load1": driver_load.get(TMC_ADDRESSES[0]),
        "load2": driver_load.get(TMC_ADDRESSES[1]),
        "fan": fan_state(now), "fan_pct": fan_now,
        "warn": driver_warning, "stop": stop_reason, "resets": driver_resets,
        "btn_ok": not btn_faulty, "mem": gc.mem_free(),
    }

def run_selftest():
    """Stop everything, hand the hardware to selftest.py, then come back."""
    global rpm_now, m1_applied_hz, m2_applied_hz, fan_applied

    if running:
        start_stop()

    rpm_now = 0
    update_motors(True)

    import selftest
    selftest.run({
        'fb': fb, 'blit': lambda: tft.blit_buffer(buf, 0, 0, WIDTH, HEIGHT), 'ui': ui,
        'emit': emit, 'version': FW_VERSION,
        'btn': btn, 'btn_faulty': btn_faulty, 'enc_sw': enc_sw,
        'take_encoder': take_encoder, 'knob_reversed': KNOB_REVERSED,
        'tmc_read': tmc_read, 'configure_driver': configure_driver, 'addrs': TMC_ADDRESSES,
        'jog_motor': jog_motor, 'fan': fan_pwm, 'led': np,
    })

    # Back to normal: drivers set up as the firmware wants them, and every
    # output re-applied because the test drove them directly.
    m1_applied_hz = m2_applied_hz = fan_applied = -1
    init_drivers(quiet=True)
    update_motors(True)
    update_fan(True)
    draw_screen()

def handle_command(line):
    """Returns True when the screen should be redrawn."""
    global telemetry, rpm_target, ratio, settings_dirty_ms

    parts = line.split()
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    try:
        if cmd == "status":
            emit(status_dict())
        elif cmd == "telemetry":
            telemetry = arg.lower() != "off"
            print("telemetry", "on" if telemetry else "off")
        elif cmd == "start":
            if not running:
                start_stop()
            return True
        elif cmd == "stop":
            if running:
                start_stop()
            return True
        elif cmd == "rpm" and arg:
            rpm_target = int(clamp(int(arg), MIN_RPM, MAX_RPM))
            settings_dirty_ms = ticks_ms()
            return True
        elif cmd == "ratio" and arg:
            ratio = round(clamp(float(arg), MIN_RATIO, MAX_RATIO), 2)
            settings_dirty_ms = ticks_ms()
            return True
        elif cmd == "selftest":
            run_selftest()
            return True
        elif cmd == "log":
            try:
                with open("sweep_log.txt") as f:
                    for l in f:
                        print(l, end="")
            except OSError:
                print("no sweep_log.txt on the board")
            print("--- end of log")
        elif cmd == "version":
            print("Rotocast Controller V4 firmware", FW_VERSION)
        elif cmd == "reboot":
            import machine
            machine.reset()
        elif cmd == "help":
            print("commands: status, telemetry on|off, start, stop, rpm N, ratio X,"
                  " selftest, log, version, reboot")
        else:
            print("? unknown command:", line)
    except ValueError:
        print("? bad value:", line)

    return False

def read_console():
    """Non-blocking: gather characters, run one command per line."""
    global cmd_buf

    redraw = False

    while poller.poll(0):
        ch = sys.stdin.read(1)

        if not ch:
            break

        if ch in ('\n', '\r'):
            if cmd_buf.strip():
                redraw = handle_command(cmd_buf.strip()) or redraw
            cmd_buf = ""
        else:
            cmd_buf += ch
            if len(cmd_buf) > 80:
                cmd_buf = ""

    return redraw

# ============================================================
# MAIN
# ============================================================

init_screen()
found = init_drivers()
load_settings()

ui.draw_splash(fb, bool(found), FW_VERSION)
tft.blit_buffer(buf, 0, 0, WIDTH, HEIGHT)
sleep_ms(SPLASH_MS)

# Read the drivers on the first pass so the screen never opens on "--"
last_driver_check_ms = ticks_add(ticks_ms(), -DRIVER_CHECK_MS)

# Knob held through power-up = self test
if enc_sw.value() == 0:
    print("knob held at power-up: running the self test")
    run_selftest()

update_motors(True)
update_fan(True)
update_led()
draw_screen()

gc.collect()
print("Rotocast Controller V4 firmware", FW_VERSION, "free memory", gc.mem_free())

if btn_faulty:
    print("Main button reads stuck ON, ignoring it (SW3 leg wiring)")
    print("Knob tap = start/stop, knob hold = next item")
else:
    print("Button = start/stop, knob tap = next item")

print("Knob turn = change the selected item")
print("Motor 2 is the inside motor, its speed is RPM x ratio")

last_btn = 1
btn_down_ms = 0
btn_long_done = False

last_sw = 1
sw_down_ms = 0
sw_long_done = False

while True:
    now = ticks_ms()
    changed = False

    update_motors()
    update_fan()

    if running:
        run_time_ms = ticks_diff(now, run_started_ms)

    # Checked while idle too, so the screen always shows real temperatures
    # The reason stays on screen until the next start, because the
    # warning itself clears as soon as the driver cools down.
    if check_drivers() and running:
        print("stopping:", "12V dropping out" if driver_warning[0] == 'power' else "driver over temperature")
        running = False
        run_stopped_ms = now
        stop_reason = driver_warning
        changed = True

    if settings_dirty_ms and ticks_diff(now, settings_dirty_ms) > SETTINGS_SAVE_DELAY_MS:
        save_settings()

    # ---------------- SERIAL ----------------

    if read_console():
        changed = True

    if telemetry and ticks_diff(now, last_telemetry_ms) > TELEMETRY_MS:
        last_telemetry_ms = now
        emit(status_dict())

    # ---------------- MAIN BUTTON ----------------

    if not btn_faulty:
        b = btn.value()

        if last_btn == 1 and b == 0:
            btn_down_ms = now
            btn_long_done = False

        if last_btn == 0 and b == 1:
            if ticks_diff(now, btn_down_ms) > DEBOUNCE_MS:
                start_stop()
                changed = True

        last_btn = b

    # ---------------- KNOB BUTTON ----------------

    s = enc_sw.value()

    if last_sw == 1 and s == 0:
        sw_down_ms = now
        sw_long_done = False

    if btn_faulty and s == 0 and not sw_long_done:
        if ticks_diff(now, sw_down_ms) > LONG_PRESS_MS:
            next_option()
            sw_long_done = True
            changed = True

    if last_sw == 0 and s == 1:
        if not sw_long_done and ticks_diff(now, sw_down_ms) > DEBOUNCE_MS:
            if btn_faulty:
                start_stop()
            else:
                next_option()

            changed = True

    last_sw = s

    # ---------------- KNOB ----------------

    delta = take_encoder()

    if delta:
        apply_delta(delta)
        changed = True

    # ---------------- SCREEN ----------------

    if changed or ticks_diff(now, last_ui_ms) > UI_UPDATE_MS:
        last_ui_ms = now
        update_led()
        draw_screen()

    sleep_ms(2)
