#!/bin/sh
# Put the firmware on a Rotocast Controller V4 board.
#
#   tools/flash.sh            finds the board on /dev/cu.usbmodem*
#   tools/flash.sh PORT       uses that serial port
#
# A blank board (held BOOTSEL while plugging in, shows up as the RPI-RP2
# drive) gets MicroPython first, then the firmware. A board that already
# runs MicroPython just gets the firmware. Needs mpremote:
#   pip3 install --user mpremote
set -e
cd "$(dirname "$0")/../firmware"

UF2=RPI_PICO-20260824-v1.29.0.uf2

# mpremote has to be installed for whichever python3 this shell uses
if ! python3 -m mpremote version >/dev/null 2>&1; then
    echo "mpremote is not installed for $(command -v python3) - installing it"
    python3 -m pip install --user --quiet mpremote
fi

if [ -d /Volumes/RPI-RP2 ]; then
    echo "Blank board in BOOTSEL mode - installing MicroPython from $UF2"
    # -X: no extended attributes; macOS fails the copy over them on this drive.
    # The board reboots as soon as the file lands, so an I/O error here is normal.
    cp -X "$UF2" /Volumes/RPI-RP2/ 2>/dev/null || true
    for i in $(seq 1 30); do
        sleep 1
        ls /dev/cu.usbmodem* >/dev/null 2>&1 && break
    done
fi

PORT=${1:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}

if [ -z "$PORT" ]; then
    echo "No board found on /dev/cu.usbmodem*. Is it plugged in?" >&2
    exit 1
fi

echo "Flashing $PORT"
# A release .uf2 ships the modules compiled (.mpy); the source copies
# below take precedence, but the stale .mpy files are removed so there
# is never any doubt which code runs.
python3 -m mpremote connect "$PORT" \
    exec "import os
for f in ('rotocast_ui.mpy', 'selftest.mpy', 'st7789py.mpy'):
    try:
        os.remove(f)
    except OSError:
        pass" + \
    cp rotocast_v4.py :main.py + \
    cp rotocast_ui.py :rotocast_ui.py + \
    cp selftest.py :selftest.py + \
    cp st7789py.py :st7789py.py + \
    exec "import os; print('on board:', os.listdir())" + \
    reset

echo "Done - the board has restarted into the new firmware."
