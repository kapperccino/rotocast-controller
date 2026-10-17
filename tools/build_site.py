#!/usr/bin/env python3
"""Assemble the GitHub Pages site into _site/.

    python3 tools/build_site.py

Copies web/ as the site, adds the firmware source files the web flasher
uploads to boards (firmware/manifest.json lists them with the version),
and the release .uf2 files for blank boards. The Pages workflow runs
this and publishes _site/; it also works locally:

    python3 -m http.server -d _site 8000
"""

import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SITE = os.path.join(PROJECT, "_site")

# name on the board -> source file
FIRMWARE_FILES = {
    "main.py": "rotocast_v4.py",
    "rotocast_ui.py": "rotocast_ui.py",
    "selftest.py": "selftest.py",
    "st7789py.py": "st7789py.py",
}
STALE_ON_BOARD = ["rotocast_ui.mpy", "selftest.mpy", "st7789py.mpy"]


def firmware_version():
    with open(os.path.join(PROJECT, "firmware", "rotocast_v4.py")) as f:
        return re.search(r'^FW_VERSION\s*=\s*"([^"]+)"', f.read(), re.M).group(1)


def main():
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    shutil.copytree(os.path.join(PROJECT, "web"), SITE)

    fw_dir = os.path.join(SITE, "firmware")
    os.makedirs(fw_dir)
    files = []
    for name, src in FIRMWARE_FILES.items():
        shutil.copy(os.path.join(PROJECT, "firmware", src), os.path.join(fw_dir, name))
        files.append({"name": name, "size": os.path.getsize(os.path.join(fw_dir, name))})

    version = firmware_version()
    with open(os.path.join(fw_dir, "manifest.json"), "w") as f:
        json.dump({"version": version, "files": files, "remove": STALE_ON_BOARD}, f, indent=2)

    rel_src = os.path.join(PROJECT, "releases")
    if os.path.isdir(rel_src):
        shutil.copytree(rel_src, os.path.join(SITE, "releases"))

    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print("site built in _site/ for firmware", version)


if __name__ == "__main__":
    main()
