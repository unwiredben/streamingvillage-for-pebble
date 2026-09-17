#!/usr/bin/env python3
# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Assemble slides/index.html from deck.html, inlining every asset.

The deck is one self-contained file: it has to open from the repo with no
server, and be publishable as a single artifact, so the screenshots and the
animated loop go in as data URIs rather than as relative paths.  Stdlib only --
the figures under figs/ are prepared separately.
"""

import base64
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MEDIA_TYPES = {".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg"}

# The chart of the seam measurement, drawn to this box in user units.
CHART = {"w": 680, "h": 250, "left": 52, "right": 14, "top": 18, "bottom": 34}


def data_uri(relative_path):
    path = os.path.join(ROOT, relative_path)
    media_type = MEDIA_TYPES[os.path.splitext(path)[1].lower()]
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return "data:{};base64,{}".format(media_type, encoded)


def chart_polylines():
    """Point strings for the clock-panel centre, split at the billboard's stall."""
    with open(os.path.join(HERE, "figs", "panel-centre.json")) as handle:
        measured = json.load(handle)
    centres = measured["centres"]
    frames = measured["frames"]
    display_width = measured["width"]

    plot_w = CHART["w"] - CHART["left"] - CHART["right"]
    plot_h = CHART["h"] - CHART["top"] - CHART["bottom"]

    def project(frame_index, centre):
        x = CHART["left"] + plot_w * frame_index / float(frames - 1)
        y = CHART["top"] + plot_h * (1 - centre / float(display_width))
        return "{:.1f},{:.1f}".format(x, y)

    runs = []
    current = []
    for index, centre in enumerate(centres):
        if centre is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(project(index, centre))
    if current:
        runs.append(current)
    if len(runs) != 2:
        raise SystemExit("expected two runs either side of the stall, got {}".format(len(runs)))

    first_centre = next(c for c in centres if c is not None)
    last_centre = next(c for c in reversed(centres) if c is not None)
    start_x, start_y = project(0, first_centre).split(",")
    end_x, end_y = project(frames - 1, last_centre).split(",")
    stall_from = float(runs[0][-1].split(",")[0])
    stall_to = float(runs[1][0].split(",")[0])
    return {
        "CHART_APPROACH": " ".join(runs[0]),
        "CHART_RETURN": " ".join(runs[1]),
        "CHART_START_X": start_x,
        "CHART_START_PY": start_y,
        "CHART_END_X": end_x,
        "CHART_END_PY": end_y,
        # The reference line sits at the height frame 0's panel centre had.
        "CHART_START_Y": start_y,
        "CHART_FRAMES": str(frames),
        "CHART_STALL_X": "{:.1f}".format(stall_from),
        "CHART_STALL_W": "{:.1f}".format(stall_to - stall_from),
    }


def main():
    with open(os.path.join(HERE, "deck.html")) as handle:
        page = handle.read()

    for key, value in chart_polylines().items():
        page = page.replace("{{" + key + "}}", value)

    missing = []

    def inline(match):
        relative_path = match.group(1)
        try:
            return data_uri(relative_path)
        except FileNotFoundError:
            missing.append(relative_path)
            return ""

    page = re.sub(r"\{\{ASSET:([^}]+)\}\}", inline, page)
    if missing:
        raise SystemExit("missing assets: {}".format(", ".join(missing)))
    left_over = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if left_over:
        raise SystemExit("unfilled placeholders: {}".format(", ".join(sorted(set(left_over)))))

    out_path = os.path.join(HERE, "index.html")
    with open(out_path, "w") as handle:
        handle.write(page)
    print("wrote {} ({:.0f} KiB)".format(out_path, os.path.getsize(out_path) / 1024.0))


if __name__ == "__main__":
    main()
