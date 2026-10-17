# rotocast_ui.py — MicroPython framebuf port of the Rotocast V4 screen design.
# Target: 160x80 RGB565 framebuf. Draws one full frame per call; caller blits to the ST7735.
# Only uses fill_rect / pixel, so it works on any framebuf. See README.md for coordinates.
import json

W, H = 160, 80

def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

# Palette (already 565-safe)
BG    = rgb565(0x00, 0x00, 0x00)
INK   = rgb565(0xFF, 0xFF, 0xFF)
DIM   = rgb565(0x84, 0x82, 0x84)
RED   = rgb565(0xF8, 0x00, 0x00)
AMBER = rgb565(0xF8, 0xA4, 0x00)
GREEN = rgb565(0x10, 0xE0, 0x10)
CYAN  = rgb565(0x20, 0xC0, 0xF8)   # selection only

# 5x7 font: rows of 5 chars, '#' = pixel, joined by '/'. Same data as font5x7.json.
with open('font5x7.json') as f:
    F5 = json.load(f)
with open('icons.json') as f:
    ICON = json.load(f)

def sprite(fb, x, y, rows, c, sc=1):
    for j, row in enumerate(rows.split('/')):
        for i, ch in enumerate(row):
            if ch == '#':
                fb.fill_rect(x + i * sc, y + j * sc, sc, sc, c)

def text(fb, x, y, s, c, sc=1):
    for ch in s:
        sprite(fb, x, y, F5.get(ch, F5['?']), c, sc)
        x += 6 * sc

def text_w(s, sc=1):
    return len(s) * 6 * sc - sc

# Segment numerals: W x H cell, stroke st, gap between glyphs = st.
_SEG = {'0': 'abcdef', '1': '', '2': 'abged', '3': 'abgcd', '4': 'fgbc',
        '5': 'afgcd', '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg'}

def seg(fb, x, y, s, c, w, h, st):
    mid = (h - st) // 2
    S = {'a': (0, 0, w, st), 'b': (w - st, 0, st, mid + st), 'c': (w - st, mid, st, h - mid),
         'd': (0, h - st, w, st), 'e': (0, mid, st, h - mid), 'f': (0, 0, st, mid + st), 'g': (0, mid, w, st)}
    for ch in s:
        if ch == '1':
            fb.fill_rect(x + (w - st) // 2, y, st, h, c); x += w + st
        elif ch in _SEG:
            for k in _SEG[ch]:
                r = S[k]; fb.fill_rect(x + r[0], y + r[1], r[2], r[3], c)
            x += w + st
        elif ch == ':':
            q = round(h / 4)
            fb.fill_rect(x, y + q, st, st, c); fb.fill_rect(x, y + h - q - st, st, st, c); x += st * 2
        elif ch == '.':
            fb.fill_rect(x, y + h - st, st, st, c); x += st * 2

def seg_w(s, w, st):
    return sum(st * 2 if ch in ':.' else w + st for ch in s) - st

def cross(fb, x, y, n, c):  # the "x" multiply sign, 2px strokes
    for i in range(n):
        fb.pixel(x + i, y + i, c); fb.pixel(x + i + 1, y + i, c)
        fb.pixel(x + n - 1 - i, y + i, c); fb.pixel(x + n - i, y + i, c)

def chip(fb, x, y, label, on, sel=CYAN):
    w = text_w(label) + 4
    if on:
        fb.fill_rect(x, y, w, 11, sel); text(fb, x + 2, y + 2, label, BG)
    else:
        text(fb, x + 2, y + 2, label, DIM)

def temp_color(v):
    if v == 'OK': return GREEN
    if v == '>120': return AMBER
    if v == '--': return DIM
    return RED

def fmt(n):
    return str(int(n)) if n == int(n) else '%.1f' % n

STATE_COLOR = {'stopped': RED, 'fault': RED, 'ramping': AMBER, 'running': GREEN}
STATE_LABEL = {'stopped': 'STOP', 'fault': 'STOP', 'ramping': 'RAMP', 'running': 'RUN'}

def draw(fb, st):
    """st: dict with keys
       state: 'stopped'|'ramping'|'running'|'fault'
       timer: 'HH:MM:SS'   rpm: int target   actual: int (ramping)   ratio: float
       sel: 'rpm'|'ratio'  m1, m2: 'OK'|'>120'|'>143'|'>150'|'>157'|'--'
       fan: 'off'|'run'|'max'|'cool'   warn: None|('hot'|'over', n)
       no_drivers: bool    saved: bool
    """
    fb.fill(BG)
    sc = STATE_COLOR[st['state']]
    # --- state column x110-159 ---
    fb.fill_rect(110, 0, 50, 80, sc)
    if st['state'] == 'fault':
        sprite(fb, 126, 5, ICON['warn'], BG, 2)
    else:
        ic = {'running': 'play', 'ramping': 'ramp'}.get(st['state'], 'stop')
        sprite(fb, 128, 6, ICON[ic], BG, 2)
    lbl = STATE_LABEL[st['state']]
    text(fb, 135 - text_w(lbl, 2) // 2, 24, lbl, BG, 2)
    for y, name, v in ((48, 'M1', st['m1']), (58, 'M2', st['m2'])):
        if v == 'OK':
            text(fb, 114, y, name + ' ' + v, BG)
        else:
            fb.fill_rect(112, y - 2, 44, 11, BG); text(fb, 114, y, name + ' ' + v, temp_color(v))
    if st.get('no_drivers'):
        text(fb, 114, 69, 'NO 12V?', BG)
    elif st.get('fan', 'off') != 'off':
        sprite(fb, 114, 69, ICON['fan'], BG)
        t = {'max': '100%', 'cool': 'COOL'}.get(st['fan'], '')
        if t: text(fb, 126, 69, t, BG)
    # --- instrument side x0-109 ---
    seg(fb, 2, 4, st['timer'], INK, 8, 16, 2)
    if st.get('saved'):
        text(fb, 80, 8, 'SAVED', DIM)
    rpm_c = GREEN if st['state'] == 'running' else AMBER if st['state'] == 'ramping' else INK
    shown = str(st['actual'] if st['state'] == 'ramping' else st['rpm'])
    seg(fb, 29 - seg_w(shown, 12, 3), 26, shown, rpm_c, 12, 24, 3)
    chip(fb, 32, 26, 'RPM', st['sel'] == 'rpm')
    if st['state'] == 'ramping':
        text(fb, 32, 41, '>' + str(st['rpm']), DIM)
    warn = st.get('warn')
    if warn:
        hot = warn[0] == 'hot'
        fb.fill_rect(0, 56, 110, 24, AMBER if hot else RED)
        sprite(fb, 3, 64, ICON['warn'], BG)
        text(fb, 16, 59, 'DRIVER %d' % warn[1], BG)
        text(fb, 16, 69, 'HOT - FAN MAX' if hot else 'OVERHEATED', BG)
    else:
        chip(fb, 2, 56, 'RATIO', st['sel'] == 'ratio')
        r = '%.2f' % st['ratio']
        cross(fb, 39, 58, 6, INK); seg(fb, 48, 57, r, INK, 6, 10, 2)
        inner = 'INNER OFF' if st['ratio'] == 0 else 'INNER ' + fmt(round(st['rpm'] * st['ratio'], 1)) + ' RPM'
        text(fb, 2, 71, inner, DIM)

def draw_splash(fb, drivers_ok=True):
    fb.fill(BG)
    # cage mark: 16x16 outline (2px) with 8x8 cyan outline inside
    for (x, y, w, h, c) in ((8, 20, 16, 16, INK), (12, 24, 8, 8, CYAN)):
        fb.fill_rect(x, y, w, 2, c); fb.fill_rect(x, y + h - 2, w, 2, c)
        fb.fill_rect(x, y, 2, h, c); fb.fill_rect(x + w - 2, y, 2, h, c)
    text(fb, 32, 20, 'ROTOCAST', INK, 2)
    text(fb, 32, 38, 'CONTROLLER V4', DIM)
    if drivers_ok:
        text(fb, 32, 62, 'DRIVERS OK', GREEN)
    else:
        text(fb, 32, 62, 'DRIVERS --', DIM)
