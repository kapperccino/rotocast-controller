# rotocast_ui.py - the Rotocast V4 screen, from the designer's handoff.
#
# Colours, glyphs, icons and the state column are taken from
# docs/design_handoff_rotocast_ui/ (its README.md is the spec,
# png/*_1x.png are the reference frames). The instrument side departs from the handoff
# in one way, at the operator's request: the RPM and RATIO labels are
# drawn at 2x and sit to the LEFT of their numbers, so the rows below
# the timer are spaced a little differently than the PNGs show.
#
# The designer's own port drew each glyph pixel by pixel from Python;
# that is too slow on the RP2040 for a 200 ms redraw, so the font and
# icons are rendered once into 1-bit sprites and each character is then
# a single blit through a colour palette.
#
# Usage:
#   ui.init(swap_colour_bytes)      once, after the framebuffer exists
#   ui.draw(fb, state)              one full frame, then blit fb to the panel
#   ui.draw_splash(fb, drivers_ok)  the boot screen

import framebuf

W, H = 160, 80

# ============================================================
# BITMAP DATA (font5x7.json and icons.json from the handoff)
# ============================================================

# 5 x 7 glyphs, rows top to bottom, '#' = pixel. Advance is 6 px.
# '>' is drawn as a right arrow, '*' as a multiply sign, '~' as a degree
# sign. Upper case only.
FONT = {
    " ": "...../...../...../...../...../...../.....",
    "!": "..#../..#../..#../..#../..#../...../..#..",
    '"': ".#.#./.#.#./...../...../...../...../.....",
    "%": "##..#/##.#./...#./..#../.#.../#.##./#.##.",
    "'": "..#../..#../...../...../...../...../.....",
    "(": "..#../.#.../#..../#..../#..../.#.../..#..",
    ")": "..#../...#./....#/....#/....#/...#./..#..",
    "*": "...../#...#/.#.#./..#../.#.#./#...#/.....",
    "+": "...../..#../..#../#####/..#../..#../.....",
    ",": "...../...../...../...../.##../.##../.#...",
    "-": "...../...../...../.###./...../...../.....",
    ".": "...../...../...../...../...../.##../.##..",
    "/": "....#/...#./...#./..#../.#.../.#.../#....",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "#####/...#./..#../...#./....#/#...#/.###.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": "..##./.#.../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/...#./.##..",
    ":": "...../..#../..#../...../..#../..#../.....",
    "<": "...../..#../.#.../#####/.#.../..#../.....",
    "=": "...../...../#####/...../#####/...../.....",
    ">": "...../..#../...#./#####/...#./..#../.....",
    "?": ".###./#...#/....#/...#./..#../...../..#..",
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "###../#..#./#...#/#...#/#...#/#..#./###..",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.####",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    "N": "#...#/#...#/##..#/#.#.#/#..##/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",
    "~": ".##../#..#./.##../...../...../...../.....",
}

ICONS = {
    "stop": "#######/#######/#######/#######/#######/#######/#######",
    "play": "##...../####.../######./#######/######./####.../##.....",
    "ramp": "......#/.....##/....###/...####/..#####/.######/#######",
    "warn": "....#..../...###.../..##.##../..##.##../.###.###./.###.###./####.####/#########",
    "fan":  "...##.../...##.../#..##..#/###..###/###..###/#..##..#/...##.../...##...",
}

# ============================================================
# PALETTE AND SPRITES, built by init()
# ============================================================

# The panel wants its 16-bit colours big-endian while framebuf stores
# them little-endian, so the caller says whether to swap. Blits go
# through a two-entry palette, and pixels that map to KEY are skipped;
# KEY is a colour the design never uses.
_swap = False
KEY = 0x0001

BG = INK = DIM = RED = AMBER = GREEN = CYAN = 0
STATE_COLOR = {}
STATE_LABEL = {'stopped': 'STOP', 'fault': 'STOP', 'ramping': 'RAMP', 'running': 'RUN'}

_pal_buf = bytearray(4)
_pal = framebuf.FrameBuffer(_pal_buf, 2, 1, framebuf.RGB565)

_font = ({}, {})      # scale 1, scale 2: char -> 1-bit FrameBuffer
_icon = ({}, {})      # scale 1, scale 2: name -> 1-bit FrameBuffer

def rgb565(r, g, b):
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((v & 0xFF) << 8) | (v >> 8) if _swap else v

def _make_sprite(rows, sc):
    rows = rows.split('/')
    w = len(rows[0]) * sc
    h = len(rows) * sc
    buf = bytearray(((w + 7) // 8) * h)
    g = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_HLSB)

    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == '#':
                g.fill_rect(i * sc, j * sc, sc, sc, 1)

    return g

def init(swap_colour_bytes):
    global _swap, BG, INK, DIM, RED, AMBER, GREEN, CYAN

    _swap = swap_colour_bytes

    BG    = rgb565(0x00, 0x00, 0x00)
    INK   = rgb565(0xFF, 0xFF, 0xFF)
    DIM   = rgb565(0x84, 0x82, 0x84)
    RED   = rgb565(0xF8, 0x00, 0x00)
    AMBER = rgb565(0xF8, 0xA4, 0x00)
    GREEN = rgb565(0x10, 0xE0, 0x10)
    CYAN  = rgb565(0x20, 0xC0, 0xF8)          # selection only, never status

    STATE_COLOR.update(stopped=RED, fault=RED, ramping=AMBER, running=GREEN)

    _pal.pixel(0, 0, KEY)

    for sc in (1, 2):
        for ch, rows in FONT.items():
            _font[sc - 1][ch] = _make_sprite(rows, sc)
        for name, rows in ICONS.items():
            _icon[sc - 1][name] = _make_sprite(rows, sc)

# ============================================================
# DRAWING PRIMITIVES
# ============================================================

def _blit(fb, g, x, y, c):
    _pal.pixel(1, 0, c)
    fb.blit(g, x, y, KEY, _pal)

def sprite(fb, x, y, name, c, sc=1):
    _blit(fb, _icon[sc - 1][name], x, y, c)

def text(fb, x, y, s, c, sc=1):
    glyphs = _font[sc - 1]
    unknown = glyphs['?']

    for ch in s:
        _blit(fb, glyphs.get(ch, unknown), x, y, c)
        x += 6 * sc

def text_w(s, sc=1):
    return len(s) * 6 * sc - sc

# Segment numerals: w x h cell, stroke st, gap between glyphs = st.
# '1' is a centred bar, ':' two squares at 1/4 and 3/4 height, '.' one
# square on the baseline.
_SEG = {'0': 'abcdef', '1': '', '2': 'abged', '3': 'abgcd', '4': 'fgbc',
        '5': 'afgcd', '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg'}

def seg(fb, x, y, s, c, w, h, st):
    mid = (h - st) // 2
    S = {'a': (0, 0, w, st), 'b': (w - st, 0, st, mid + st), 'c': (w - st, mid, st, h - mid),
         'd': (0, h - st, w, st), 'e': (0, mid, st, h - mid), 'f': (0, 0, st, mid + st),
         'g': (0, mid, w, st)}

    for ch in s:
        if ch == '1':
            fb.fill_rect(x + (w - st) // 2, y, st, h, c)
            x += w + st
        elif ch in _SEG:
            for k in _SEG[ch]:
                r = S[k]
                fb.fill_rect(x + r[0], y + r[1], r[2], r[3], c)
            x += w + st
        elif ch == ':':
            q = round(h / 4)
            fb.fill_rect(x, y + q, st, st, c)
            fb.fill_rect(x, y + h - q - st, st, st, c)
            x += st * 2
        elif ch == '.':
            fb.fill_rect(x, y + h - st, st, st, c)
            x += st * 2

def seg_w(s, w, st):
    return sum(st * 2 if ch in ':.' else w + st for ch in s) - st

def cross(fb, x, y, n, c):
    """The multiply sign, 2 px strokes."""
    for i in range(n):
        fb.pixel(x + i, y + i, c)
        fb.pixel(x + i + 1, y + i, c)
        fb.pixel(x + n - 1 - i, y + i, c)
        fb.pixel(x + n - i, y + i, c)

def chip(fb, x, y, label, on, sc=1):
    """Selection highlight: cyan fill with black text when selected,
    grey text and no fill otherwise. 2 px of padding all round, so the
    chip is 11 tall at 1x and 18 tall at 2x."""
    if on:
        fb.fill_rect(x, y, text_w(label, sc) + 4, 7 * sc + 4, CYAN)
        text(fb, x + 2, y + 2, label, BG, sc)
    else:
        text(fb, x + 2, y + 2, label, DIM, sc)

def temp_color(v):
    if v == 'OK':
        return GREEN
    if v == '>120':
        return AMBER
    if v == '--':
        return DIM
    return RED

def fmt(n):
    return str(int(n)) if n == int(n) else '%.1f' % n

# ============================================================
# FRAMES
# ============================================================

def draw(fb, st):
    """st is a dict:
       state: 'stopped' | 'ramping' | 'running' | 'fault'
       timer: 'HH:MM:SS'   rpm: target   actual: rpm while ramping
       ratio: float        sel: 'rpm' | 'ratio'
       m1, m2: 'OK' | '>120' | '>143' | '>150' | '>157' | '--'
       fan: 'off' | 'run' | 'max' | 'cool'
       warn: None | ('hot' | 'over' | 'power', motor number)
       no_drivers: bool    saved: bool
    """
    fb.fill(BG)
    sc = STATE_COLOR[st['state']]

    # ---- state column, x 110-159, everything on it is black ----
    fb.fill_rect(110, 0, 50, 80, sc)

    if st['state'] == 'fault':
        sprite(fb, 126, 5, 'warn', BG, 2)
    else:
        sprite(fb, 128, 6, {'running': 'play', 'ramping': 'ramp'}.get(st['state'], 'stop'), BG, 2)

    lbl = STATE_LABEL[st['state']]
    text(fb, 135 - text_w(lbl, 2) // 2, 24, lbl, BG, 2)

    for y, name, v in ((48, 'M1', st['m1']), (58, 'M2', st['m2'])):
        if v == 'OK':
            text(fb, 114, y, name + ' ' + v, BG)
        else:
            # anything not OK sits in a black box so it pops out
            fb.fill_rect(112, y - 2, 44, 11, BG)
            text(fb, 114, y, name + ' ' + v, temp_color(v))

    if st.get('no_drivers'):
        text(fb, 114, 69, 'NO 12V?', BG)
    elif st.get('fan', 'off') != 'off':
        sprite(fb, 114, 69, 'fan', BG)
        t = {'max': '100%', 'cool': 'COOL'}.get(st['fan'], '')
        if t:
            text(fb, 126, 69, t, BG)

    # ---- instrument side, x 0-109 ----
    # timer y 4-19, speed row y 23-46, ratio row y 50-67, inner y 71-77
    seg(fb, 2, 4, st['timer'], INK, 8, 16, 2)

    if st.get('saved'):
        text(fb, 80, 8, 'SAVED', DIM)

    # speed row: 2x chip (38 x 18) on the left, digits after it, both
    # centred on y 34
    chip(fb, 2, 26, 'RPM', st['sel'] == 'rpm', 2)
    rpm_c = GREEN if st['state'] == 'running' else AMBER if st['state'] == 'ramping' else INK
    shown = str(st['actual'] if st['state'] == 'ramping' else st['rpm'])
    seg(fb, 44, 23, shown, rpm_c, 12, 24, 3)

    if st['state'] == 'ramping':
        # target, sitting on the digits' baseline
        text(fb, 44 + seg_w(shown, 12, 3) + 4, 40, '>' + str(st['rpm']), DIM)

    warn = st.get('warn')

    if warn:
        # the strip takes the ratio row and the inner line
        kind, n = warn
        fb.fill_rect(0, 50, 110, 30, AMBER if kind == 'hot' else RED)
        sprite(fb, 3, 61, 'warn', BG)
        text(fb, 16, 56, 'DRIVER %d' % n, BG)
        text(fb, 16, 67, {'hot': 'HOT - FAN MAX', 'over': 'OVERHEATED',
                          'power': '12V DROPOUT'}[kind], BG)
    else:
        # ratio row: 2x chip (62 x 18), multiply sign and value centred
        # on y 59
        chip(fb, 2, 50, 'RATIO', st['sel'] == 'ratio', 2)
        cross(fb, 68, 56, 6, INK)
        seg(fb, 77, 54, '%.2f' % st['ratio'], INK, 6, 10, 2)

        if st['ratio'] == 0:
            inner = 'INNER OFF'
        else:
            inner = 'INNER ' + fmt(round(st['rpm'] * st['ratio'], 1)) + ' RPM'

        text(fb, 2, 71, inner, DIM)

def draw_splash(fb, drivers_ok=True, version=''):
    fb.fill(BG)

    # cage mark: 16 x 16 white outline with an 8 x 8 cyan outline inside
    for x, y, w, h, c in ((8, 20, 16, 16, INK), (12, 24, 8, 8, CYAN)):
        fb.fill_rect(x, y, w, 2, c)
        fb.fill_rect(x, y + h - 2, w, 2, c)
        fb.fill_rect(x, y, 2, h, c)
        fb.fill_rect(x + w - 2, y, 2, h, c)

    text(fb, 32, 20, 'ROTOCAST', INK, 2)
    text(fb, 32, 38, 'CONTROLLER V4', DIM)

    if version:
        text(fb, 32, 48, 'FW ' + version, DIM)

    text(fb, 32, 62, 'DRIVERS OK' if drivers_ok else 'DRIVERS --', GREEN if drivers_ok else DIM)
