# selftest.py - hardware self test for the Rotocast Controller V4.
#
# Entered by holding the knob while the controller powers up, or with
# the serial command 'selftest'. Walks every subsystem, shows PASS /
# FAIL per line on the screen, and prints the same report on the serial
# port, plus one JSON line for the web dashboard.
#
# rotocast_v4.py hands over its hardware in a dict (ctx) so this module
# has no pin numbers or register values of its own.

from time import sleep_ms, ticks_ms, ticks_diff
import gc

PASS, FAIL, WARN, INFO = 'PASS', 'FAIL', 'WARN', 'INFO'
PROMPT_MS = 10000            # how long each "press / turn" prompt waits
RESULTS_MS = 60000           # how long the results stay up without a knob press
JOG_RPM = 3
JOG_MS = 3000

def run(ctx):
    fb, blit, ui = ctx['fb'], ctx['blit'], ctx['ui']
    emit = ctx['emit']
    results = []

    # ---- helpers ----

    def show(title, l1='', l2='', l3='', colour=None):
        fb.fill(ui.BG)
        ui.text(fb, 2, 2, title, colour or ui.CYAN, 2)
        ui.text(fb, 2, 24, l1, ui.INK)
        ui.text(fb, 2, 40, l2, ui.INK)
        ui.text(fb, 2, 56, l3, ui.DIM)
        blit()

    def prompt(title, l1, l2=''):
        show(title, l1, l2, 'WAITING...', ui.AMBER)
        emit({'prompt': title + ' - ' + l1})

    def record(name, status, detail=''):
        results.append((name, status, detail))
        print("  %-7s %-4s %s" % (name, status, detail))
        emit({'test': name, 'status': status, 'detail': detail})

    def knob():
        d = ctx['take_encoder']()
        return -d if ctx['knob_reversed'] else d

    def wait_for(cond, ms=PROMPT_MS):
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < ms:
            if cond():
                return True
            sleep_ms(10)
        return False

    print("\nSELF TEST, firmware", ctx['version'])
    emit({'selftest': 'start', 'fw': ctx['version']})

    # ---- 1. screen: colour bars, then the test itself proves the rest ----
    for colour in (ui.RED, ui.GREEN, ui.CYAN, ui.INK):
        fb.fill(colour)
        blit()
        sleep_ms(400)
    record('SCREEN', INFO, 'BARS SHOWN')

    # ---- 2. LED ----
    led = ctx['led']
    for c in ((60, 0, 0), (0, 60, 0), (0, 0, 60)):
        led[0] = c
        led.write()
        show('LED', 'red, green, blue', '', '')
        sleep_ms(350)
    led[0] = (0, 0, 0)
    led.write()
    record('LED', INFO, 'R G B SHOWN')

    # ---- 3. main button ----
    btn = ctx['btn']
    if ctx['btn_faulty']:
        record('BUTTON', FAIL, 'STUCK ON - SW3')
    else:
        prompt('BUTTON', 'PRESS THE BIG', 'BUTTON')
        if wait_for(lambda: btn.value() == 0) and wait_for(lambda: btn.value() == 1, 3000):
            record('BUTTON', PASS, 'PRESS SEEN')
        else:
            record('BUTTON', FAIL, 'NO PRESS')

    # ---- 4. knob: right, left, press ----
    knob()                                            # discard anything pending
    count = [0]

    def turned(expect):
        count[0] += knob()
        return count[0] * expect >= 3

    prompt('KNOB', 'TURN RIGHT', '3 CLICKS')
    if wait_for(lambda: turned(1)):
        right = PASS
    else:
        right = 'REV' if count[0] <= -3 else FAIL
    count[0] = 0
    prompt('KNOB', 'TURN LEFT', '3 CLICKS')
    if wait_for(lambda: turned(-1)):
        left = PASS
    else:
        left = 'REV' if count[0] >= 3 else FAIL
    if right == PASS and left == PASS:
        record('KNOB', PASS, 'BOTH WAYS')
    elif 'REV' in (right, left):
        record('KNOB', FAIL, 'REVERSED')
    else:
        record('KNOB', FAIL, 'R %s L %s' % (right, left))

    sw = ctx['enc_sw']
    prompt('KNOB', 'PRESS THE KNOB', '')
    if wait_for(lambda: sw.value() == 0) and wait_for(lambda: sw.value() == 1, 3000):
        record('KNOBSW', PASS, 'PRESS SEEN')
    else:
        record('KNOBSW', FAIL, 'NO PRESS')

    # ---- 5. driver UART ----
    tmc_read = ctx['tmc_read']
    alive = []
    for n, addr in enumerate(ctx['addrs']):
        show('DRIVERS', 'reading M%d' % (n + 1), '', '')
        ioin = tmc_read(addr, 0x06)
        if ioin is None:
            record('DRV M%d' % (n + 1), FAIL, 'NO REPLY')
        else:
            alive.append((n, addr))
            record('DRV M%d' % (n + 1), PASS, 'CHIP V%02X' % (ioin >> 24))
    if not alive:
        record('12V', FAIL, 'NO DRIVERS - 12V?')
    else:
        record('12V', PASS, 'PRESENT')

    # ---- 6. motors: a slow jog each, watching the coil flags ----
    jog = ctx['jog_motor']
    for n, addr in alive:
        ctx['configure_driver'](addr)
        show('MOTOR', 'M%d turning slowly' % (n + 1), 'watch it', '')
        jog(n, JOG_RPM)
        faults = set()
        t0 = ticks_ms()
        while ticks_diff(ticks_ms(), t0) < JOG_MS:
            sleep_ms(500)
            s = tmc_read(addr, 0x6F)
            if s is None:
                faults.add('NO REPLY')
                continue
            if s & 0x0C: faults.add('SHORT GND')
            if s & 0x30: faults.add('SHORT VS')
            if s & 0x40: faults.add('COIL A?')
            if s & 0x80: faults.add('COIL B?')
        jog(n, 0)
        if not faults:
            record('M%d' % (n + 1), PASS, 'TURNED 3S')
        elif faults <= {'COIL A?', 'COIL B?'}:
            record('M%d' % (n + 1), WARN, ' '.join(sorted(faults)))
        else:
            record('M%d' % (n + 1), FAIL, ' '.join(sorted(faults)))

    # ---- 7. fan ----
    show('FAN', 'running 3 s', 'listen for it', '')
    ctx['fan'].duty_u16(65535)
    sleep_ms(JOG_MS)
    ctx['fan'].duty_u16(0)
    record('FAN', INFO, 'RAN 3S')

    # ---- 8. memory ----
    gc.collect()
    free = gc.mem_free()
    record('MEMORY', PASS if free > 40000 else FAIL, '%dK FREE' % (free // 1024))
    record('FW', INFO, ctx['version'])

    # ---- results ----
    fails = sum(1 for r in results if r[1] == FAIL)
    emit({'selftest': 'done', 'fails': fails,
          'results': [{'name': r[0], 'status': r[1], 'detail': r[2]} for r in results]})
    print("SELF TEST: %d FAIL" % fails if fails else "SELF TEST: ALL PASS")

    colours = {PASS: ui.GREEN, FAIL: ui.RED, WARN: ui.AMBER, INFO: ui.DIM}
    top = 0
    rows = 6

    def draw():
        fb.fill(ui.BG)
        if fails:
            ui.text(fb, 2, 2, '%d FAIL' % fails, ui.RED, 2)
        else:
            ui.text(fb, 2, 2, 'ALL PASS', ui.GREEN, 2)
        ui.text(fb, 104, 6, 'KNOB:EXIT', ui.DIM)
        for i in range(rows):
            if top + i >= len(results):
                break
            name, status, detail = results[top + i]
            y = 20 + i * 9
            ui.text(fb, 2, y, name[:7], ui.INK)
            ui.text(fb, 50, y, detail[:13], ui.DIM)
            ui.text(fb, 134, y, status, colours.get(status, ui.INK))
        blit()

    draw()
    knob()
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) < RESULTS_MS:
        d = knob()
        if d:
            top = max(0, min(len(results) - rows, top + d))
            draw()
        if sw.value() == 0:
            while sw.value() == 0:
                sleep_ms(10)
            break
        sleep_ms(20)

    return results
