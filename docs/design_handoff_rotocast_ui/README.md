# Handoff: Rotocast Controller V4 — 160 × 80 status screen

## Overview
Replacement UI for the Rotocast V4 rotational-casting controller's 0.96" ST7735 panel (160 × 80, RGB565, MicroPython `framebuf`). One glance answers *is it running, how fast, how long*. The screen and the RGB status LED speak the same colour language: red = stopped, amber = ramping, green = running. Cyan is reserved for the knob selection; red/amber below the state column are reserved for thermal warnings.

## About the design files
`Rotocast V4 UI.dc.html` is a **design reference built in HTML** — a pixel renderer that draws every screen with framebuf-equivalent primitives (fill_rect, pixel, sprite blit) so what you see is exactly what the panel can draw. It is not firmware. The job is to reproduce these frames in the controller's MicroPython code.

`rotocast_ui.py` is a **direct port of that renderer to MicroPython framebuf** — same coordinates, same palette, same fonts. It should be treated as a strong starting point: wire `draw(fb, state)` into the existing 200 ms redraw / input-triggered redraw loop and blit. It uses only `fill_rect`, `pixel`, `fill`. Verify glyph output against the 1× PNGs.

## Fidelity
**High-fidelity, pixel-exact.** Every coordinate below is final. Compare firmware output against `png/*_1x.png` pixel for pixel.

## Hard constraints honoured
- 160 × 80, black ground, 7 colours (all RGB565-safe), no anti-aliasing, no gradients, no alpha.
- All essential content ≥ 2 px from every edge.
- Structural fills are ≥ 2 px; only the ratio-row `×` uses 2-px diagonals.
- Fonts: hand-drawn 5 × 7 bitmap (6 × 8 cell) + procedurally drawn segment numerals (no sheet needed, but a sheet is supplied).

## Palette (hex → role)
| Hex | 565 | Role |
|---|---|---|
| `#000000` | `0x0000` | ground |
| `#FFFFFF` | `0xFFFF` | ink — timer, stopped speed digits, ratio value |
| `#848284` | `0x8410` | dim — unselected chip labels, notes, `--` temps |
| `#F80000` | `0xF800` | stopped / fault column, overheated strip, ≥143 °C |
| `#F8A400` | `0xFD20` | ramping column, hot strip, >120 °C |
| `#10E010` | `0x1702` | running column, running speed digits, OK |
| `#20C0F8` | `0x261F` | selection chip only (never used for status) |

## Layout (all coordinates px, origin top-left)

### State column — x 110–159, full height, filled in state colour; everything drawn on it is black
- Icon, 7 × 7 sprite drawn at 2× (14 × 14) at (128, 6): stop square / play wedge / ramp wedge. Fault state: warning triangle (9 × 8) at 2× at (126, 5).
- State word, 5 × 7 at 2×, centred on x = 135, y = 24: `STOP`, `RAMP`, `RUN`. Fault also reads `STOP` — the red strip on the left explains why.
- `M1 OK` at (114, 48), `M2 OK` at (114, 58), black. Any non-OK value (`>120`, `>143`, `--`) is drawn in its thermal colour inside a **black 44 × 11 box at (112, y−2)** so it pops out of the column.
- Fan slot y = 69: fan icon 8 × 8 at (114, 69) + optional text at (126, 69): `100%` when fan is at full, `COOL` during the 90 s cooldown, nothing when running at 60 %. Hidden when fan is off.
- Drivers not responding: `NO 12V?` at (114, 69) replaces the fan slot.

### Instrument side — x 0–109, black
- **Timer** `HH:MM:SS`, segment numerals 8 × 16 / stroke 2, at (2, 4), white. Width 66.
- `SAVED` (dim, 5 × 7) at (80, 8) for ~1 s after settings persist.
- **Speed** segment numerals 12 × 24 / stroke 3, **right-aligned to x = 28**, y = 26. Colour: white stopped, green running, amber ramping (shows *actual* speed while ramping).
- `RPM` chip at (32, 26), 21 × 11.
- Ramp target `>10` (dim, arrow glyph is `>`) at (32, 41), ramping only.
- **Ratio row** y 56–67: `RATIO` chip at (2, 56), 33 × 11; `×` at (39, 58) (6 px, 2-px strokes); ratio `1.25` in 6 × 10 / stroke 2 numerals at (48, 57), white.
- Inner-cage line at (2, 71), dim: `INNER 12.5 RPM` (rpm × ratio, one decimal, integer if whole) or `INNER OFF` when ratio = 0.00.
- **Warning strip** replaces the ratio row + inner line: fill (0, 56, 110, 24) amber (hot) or red (overheated); warning icon at (3, 64); line 1 `DRIVER n` at (16, 59); line 2 `HOT - FAN MAX` or `OVERHEATED` at (16, 69). Black text.

### Chip (selection highlight)
Width = text width + 4, height 11, text at (+2, +2). **Selected:** cyan fill, black text. **Unselected:** grey text, no fill. Only one chip is selected at a time; knob press toggles.

### Splash (optional, ~1 s)
Cage mark: 16 × 16 white 2-px outline at (8, 20) with 8 × 8 cyan 2-px outline at (12, 24). `ROTOCAST` 5 × 7 at 2× at (32, 20) white; `CONTROLLER V4` at (32, 38) dim; `DRIVERS OK` green / `DRIVERS --` dim at (32, 62).

## Fonts
- **5 × 7 bitmap** — `font5x7.json` (glyph → 7 rows of 5 chars, `#` = pixel) and `png/font_5x7_cell6x8_ascii32-95_1x.png` (6 × 8 cells, ASCII 32–95, 16 per row, 4 rows; uppercase only). Advance 6 px. `>` is drawn as a right arrow, `*` as ×, `~` as °. Draw at 2× for the state word and splash title.
- **Segment numerals** — drawn at runtime from seven rectangles per digit (see `seg()` in `rotocast_ui.py`). Three sizes: 12 × 24 / 3 (speed), 8 × 16 / 2 (timer), 6 × 10 / 2 (ratio). Gap between glyphs = stroke. `1` is a centred bar; `:` two squares at ¼ and ¾ height; `.` one square on the baseline. Reference sheet: `png/numerals_segment_*_1x.png`.

## Icons (1-bit, white on black in the sheet; drawn black on the column)
`icons.json` and `png/icons_16x16_stop_play_ramp_warn_fan_1x.png` — 16 × 16 cells, sprite at (4, 4) in each: `stop` 7 × 7, `play` 7 × 7, `ramp` 7 × 7, `warn` 9 × 8, `fan` 8 × 8.

## States → what changes
| # | State | Column | Speed digits | Left lower rows |
|---|---|---|---|---|
| 01 | Stopped, speed selected | red, STOP, stop icon | white target | RPM chip cyan |
| 02 | Stopped, ratio selected | red | white | RATIO chip cyan, `SAVED` beside timer |
| 03 | Ramping | amber, RAMP, wedge | amber **actual**, `>target` under chip | fan icon |
| 04 | Running | green, RUN, play | green target | fan icon |
| 05 | Driver hot, running | green; `M2 >120` boxed amber; fan `100%` | green | amber strip `DRIVER 2 / HOT - FAN MAX` |
| 06 | Stopped by overheat | red, warning icon, STOP; `M2 >143` boxed red | white | red strip `DRIVER 2 / OVERHEATED`; timer holds |
| 07 | Drivers not responding | red; `M1 --` `M2 --` boxed grey; `NO 12V?` | white | normal |
| 08 | Cooldown after stop | red; fan icon + `COOL` | white | normal; timer holds |
| 09 | Boot splash | — | — | — |

## Behaviour notes for firmware
- Redraw the whole frame every 200 ms and immediately on any input; no continuous animation. A 1 Hz blink of the warning icon in states 05/06 is acceptable but optional.
- Timer resets to `00:00:00` on start, counts while ramping/running, holds after stop or fault.
- `SAVED` appears once RPM/ratio are persisted (3 s after last knob change), for about 1 s.
- Knob turn changes the value under the selected chip instantly, including while running.

## Files
- `Rotocast V4 UI.dc.html` + `support.js` — interactive review board (open in a browser; downloads 1× / 8× PNGs; tweaks for selection colour and ratio style).
- `rotocast_ui.py` — MicroPython framebuf port.
- `font5x7.json`, `icons.json` — bitmap data.
- `png/` — every screen and sheet at 1× (export) and 8× (review), nearest-neighbour.
