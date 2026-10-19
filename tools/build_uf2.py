#!/usr/bin/env python3
"""Build one drag-and-drop .uf2 that carries MicroPython AND the firmware.

    python3 tools/build_uf2.py            -> releases/rotocast-v4-<version>.uf2

Flashing a board then needs no software at all: hold BOOTSEL, plug in,
drag the file onto the RPI-RP2 drive. Works for blank boards and for
updating boards that already run the firmware (saved speed/ratio are
reset to defaults).

How it works: the firmware files are packed into a LittleFS filesystem
image with the same geometry MicroPython formats on this board (4 KB
blocks, 352 of them, at flash offset FS_OFFSET). The output is ONE
LINEAR image of the whole 2 MB flash - MicroPython's blocks, 0xFF
padding, then the filesystem - cut into UF2 blocks in address order.
The RP2040 bootrom expects a UF2 to be linear (block N at base + 256*N)
and silently loses blocks that are not; a sparse first attempt left the
filesystem half-written. Linear costs a 4 MB file and a few more
seconds in the bootloader, and is deterministic: every byte of flash is
defined, so a reused board ends up identical to a blank one.

Modules other than main.py are pre-compiled with mpy-cross so the board
boots faster and keeps more RAM. Needs:  pip3 install littlefs-python mpy-cross
"""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
FIRMWARE = os.path.join(PROJECT, "firmware")
RELEASES = os.path.join(PROJECT, "releases")

MICROPYTHON_UF2 = os.path.join(FIRMWARE, "RPI_PICO-20260824-v1.29.0.uf2")

# Filesystem geometry of the RPI_PICO MicroPython build (2 MB flash):
# the last 1408 KB hold the filesystem. Verified on the board by finding
# LittleFS block 0 in the XIP address space.
FLASH_BASE = 0x10000000
FLASH_SIZE = 2 * 1024 * 1024
FS_OFFSET = 0x0A0000
BLOCK_SIZE = 4096
BLOCK_COUNT = 352
PROG_SIZE = 256               # MicroPython mounts with progsize=256
LFS_DISK_VERSION = 0x00020000 # oldest lfs2 format: every lfs2 reader mounts it

# What goes on the board. main.py stays as source so it is readable on
# the board; the rest is compiled.
MAIN = "rotocast_v4.py"
MODULES = ("rotocast_ui.py", "selftest.py", "st7789py.py")

# UF2 format
UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY = 0x00002000
RP2040_FAMILY = 0xE48BFF56
PAYLOAD = 256


def firmware_version():
    with open(os.path.join(FIRMWARE, MAIN)) as f:
        m = re.search(r'^FW_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit("FW_VERSION not found in " + MAIN)
    return m.group(1)


def compile_mpy(src, out_dir):
    """Compile a module for the RP2040; fall back to the .py if mpy-cross is missing."""
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(out_dir, name + ".mpy")
    r = subprocess.run([sys.executable, "-m", "mpy_cross", "-march=armv6m", "-o", out, src],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  mpy-cross failed for %s, shipping source instead:\n%s" % (src, r.stderr.strip()))
        return src, name + ".py"
    return out, name + ".mpy"


def build_filesystem(files):
    """files: list of (local path, name on board). Returns the raw image."""
    from littlefs import LittleFS

    fs = LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT,
                  prog_size=PROG_SIZE, disk_version=LFS_DISK_VERSION)
    for path, name in files:
        with open(path, "rb") as src, fs.open(name, "wb") as dst:
            dst.write(src.read())
    return bytes(fs.context.buffer)


def read_uf2(path):
    """Yield (address, data) for every block of an existing UF2."""
    with open(path, "rb") as f:
        raw = f.read()
    for i in range(0, len(raw), 512):
        blk = raw[i:i + 512]
        m0, m1, flags, addr, size, _, _, family = struct.unpack_from("<8I", blk)
        if m0 != UF2_MAGIC0 or m1 != UF2_MAGIC1:
            sys.exit("not a UF2 file: " + path)
        if flags & UF2_FLAG_FAMILY and family != RP2040_FAMILY:
            sys.exit("UF2 is not for the RP2040: " + path)
        yield addr, blk[32:32 + size]


def linear_blocks(mp_blocks, image):
    """One block for every 256-byte page of the 2 MB flash, in order:
    MicroPython where it has data, the filesystem image at FS_OFFSET,
    0xFF everywhere else."""
    flash = bytearray(b"\xff" * FLASH_SIZE)
    for addr, data in mp_blocks:
        off = addr - FLASH_BASE
        if off < 0 or off + len(data) > FS_OFFSET:
            sys.exit("MicroPython block at 0x%08X overlaps the filesystem" % addr)
        flash[off:off + len(data)] = data
    flash[FS_OFFSET:FS_OFFSET + len(image)] = image
    return [(FLASH_BASE + off, bytes(flash[off:off + PAYLOAD])) for off in range(0, FLASH_SIZE, PAYLOAD)]


def write_uf2(path, blocks):
    total = len(blocks)
    with open(path, "wb") as f:
        for n, (addr, data) in enumerate(blocks):
            head = struct.pack("<8I", UF2_MAGIC0, UF2_MAGIC1, UF2_FLAG_FAMILY, addr,
                               len(data), n, total, RP2040_FAMILY)
            f.write(head + data.ljust(476, b"\x00") + struct.pack("<I", UF2_MAGIC_END))


def main():
    version = firmware_version()
    print("Rotocast Controller V4 firmware", version)

    with tempfile.TemporaryDirectory() as tmp:
        files = [(os.path.join(FIRMWARE, MAIN), "main.py")]
        for mod in MODULES:
            path, name = compile_mpy(os.path.join(FIRMWARE, mod), tmp)
            files.append((path, name))
        for path, name in files:
            print("  %-16s %6d bytes" % (name, os.path.getsize(path)))

        image = build_filesystem(files)

    mp_blocks = list(read_uf2(MICROPYTHON_UF2))
    used = sum(1 for s in range(0, len(image), BLOCK_SIZE) if image[s:s + BLOCK_SIZE] != b"\xff" * BLOCK_SIZE)
    print("  MicroPython: %d KB, filesystem: %d of %d sectors used"
          % (len(mp_blocks) * PAYLOAD // 1024, used, BLOCK_COUNT))

    blocks = linear_blocks(mp_blocks, image)
    os.makedirs(RELEASES, exist_ok=True)
    out = os.path.join(RELEASES, "rotocast-v4-%s.uf2" % version)
    write_uf2(out, blocks)

    with open(os.path.join(RELEASES, "latest.json"), "w") as f:
        json.dump({"version": version, "file": os.path.basename(out),
                   "micropython": os.path.basename(MICROPYTHON_UF2)}, f, indent=2)

    print("wrote", os.path.relpath(out, PROJECT), "(%d KB)" % (os.path.getsize(out) // 1024))
    print("Flash: hold BOOTSEL, plug in, drag the file onto RPI-RP2.")


if __name__ == "__main__":
    main()
