# Render every screen state with rotocast_ui on the desktop, without the
# hardware. Writes 8x PNGs to tools/renders/ for a look, and with
# --diff-handoff compares them pixel for pixel against the designer's
# 1x PNGs (the instrument side has since moved on from those, so expect
# differences there; the state column should still match).
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
PNG = os.path.join(PROJECT, "docs", "design_handoff_rotocast_ui", "png")
OUT = os.path.join(HERE, "renders")

sys.path.insert(0, HERE)      # our framebuf shim
sys.path.insert(1, os.path.join(PROJECT, "firmware"))

import framebuf
import rotocast_ui as ui
from PIL import Image

ui.init(False)                # unswapped so the values compare to the PNG

STATES = {
    "01_stopped-speed": dict(state='stopped', timer='00:00:00', rpm=10, ratio=1.25, sel='rpm', m1='OK', m2='OK', fan='off'),
    "02_stopped-ratio": dict(state='stopped', timer='00:00:00', rpm=10, ratio=1.25, sel='ratio', m1='OK', m2='OK', saved=True),
    "03_ramping": dict(state='ramping', timer='00:00:02', rpm=10, actual=6, ratio=1.25, sel='rpm', m1='OK', m2='OK', fan='run'),
    "04_running": dict(state='running', timer='00:14:37', rpm=10, ratio=1.25, sel='rpm', m1='OK', m2='OK', fan='run'),
    "05_hot": dict(state='running', timer='01:02:15', rpm=10, ratio=1.25, sel='rpm', m1='OK', m2='>120', fan='max', warn=('hot', 2)),
    "06_fault": dict(state='fault', timer='01:09:48', rpm=10, ratio=1.25, sel='rpm', m1='OK', m2='>143', fan='max', warn=('over', 2)),
    "07_no-drivers": dict(state='stopped', timer='00:00:00', rpm=10, ratio=1.25, sel='rpm', m1='--', m2='--', no_drivers=True),
    "08_cooldown": dict(state='stopped', timer='00:31:10', rpm=10, ratio=1.25, sel='rpm', m1='OK', m2='OK', fan='cool'),
    "10_max-values": dict(state='ramping', timer='12:34:56', rpm=25, actual=25, ratio=2.0, sel='ratio', m1='>157', m2='>150', fan='max'),
    "11_power-fault": dict(state='fault', timer='00:00:04', rpm=16, ratio=2.0, sel='rpm', m1='>120', m2='>120', fan='max', warn=('power', 1)),
}


def render(fn):
    buf = bytearray(ui.W * ui.H * 2)
    fb = framebuf.FrameBuffer(buf, ui.W, ui.H, framebuf.RGB565)
    fn(fb)
    im = Image.new("RGB", (ui.W, ui.H))
    px = im.load()
    for y in range(ui.H):
        for x in range(ui.W):
            v = fb.pixel(x, y)
            px[x, y] = (((v >> 11) & 0x1F) << 3, ((v >> 5) & 0x3F) << 2, (v & 0x1F) << 3)
    return im


def diff(name, im):
    path = os.path.join(PNG, name + "_1x.png")
    if not os.path.exists(path):
        return True
    ref = Image.open(path).convert("RGB")
    a, b = im.load(), ref.load()
    q = lambda p: (p[0] >> 3, p[1] >> 2, p[2] >> 3)      # compare in 565 space
    diffs = [(x, y) for y in range(ui.H) for x in range(ui.W) if q(a[x, y]) != q(b[x, y])]
    if diffs:
        xs = [d[0] for d in diffs]; ys = [d[1] for d in diffs]
        print("%-18s %4d px differ, x %d-%d y %d-%d" % (name, len(diffs), min(xs), max(xs), min(ys), max(ys)))
    else:
        print("%-18s identical to handoff" % name)
    return not diffs


os.makedirs(OUT, exist_ok=True)
compare = "--diff-handoff" in sys.argv
frames = [(n, lambda fb, st=st: ui.draw(fb, st)) for n, st in STATES.items()]
frames.append(("09_splash", lambda fb: ui.draw_splash(fb, True)))

ok = True
for name, fn in frames:
    im = render(fn)
    im.resize((ui.W * 8, ui.H * 8), Image.NEAREST).save(os.path.join(OUT, name + "_8x.png"))
    if compare:
        ok &= diff(name, im)

print("rendered %d frames to %s" % (len(frames), OUT))
if compare:
    print("ALL IDENTICAL" if ok else "DIFFERENCES FOUND (see above)")
