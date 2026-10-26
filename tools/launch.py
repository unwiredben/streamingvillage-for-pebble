#!/usr/bin/env python3
# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Install and launch the current build, optionally forcing robot appearances."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

try:
    import pebble_tool  # noqa: F401
except ImportError:
    launcher = shutil.which("pebble")
    if not launcher:
        sys.exit("pebble-tool is required.")
    interpreter = Path(launcher).read_text().splitlines()[0].removeprefix("#!")
    if os.path.realpath(interpreter) == os.path.realpath(sys.executable):
        sys.exit("Cannot import pebble-tool under " + interpreter)
    os.execv(interpreter, [interpreter, os.path.abspath(__file__)] + sys.argv[1:])

from capture_loop import GifCapture, set_force_robot, setup_environment


def main():
    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "package.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", choices=package["pebble"]["targetPlatforms"],
                        default="emery")
    parser.add_argument("--force-robot", action="store_true",
                        help="Show the robot on every run for this app session.")
    args = parser.parse_args()
    bundle = root / "build" / (root.name + ".pbw")
    if not bundle.is_file():
        parser.error("No build bundle; run pebble build first.")
    subprocess.run(["pebble", "install", "--emulator", args.emulator, str(bundle)],
                   cwd=root, check=True)
    setup_environment()
    command = GifCapture(argparse.Namespace(v=0, sdk=None))
    pebble = command._connect_emulator(args.emulator, None)
    try:
        set_force_robot(pebble, package["pebble"]["uuid"], args.force_robot)
        print("Robot forced for this session." if args.force_robot else
              "Random visitor selection restored.")
    finally:
        command._close_pebble_connection(pebble)


if __name__ == "__main__":
    main()
