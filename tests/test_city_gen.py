#!/usr/bin/env python3
# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Holds src/c/city_gen.c against the Python it was ported from.

The foreground is no longer stored artwork, so there is no PNG left to catch
a mistake in it -- the watch draws the panorama itself, and the only surviving
description of what it is supposed to look like is tools/gen_art.py, which
still draws the appstore icons from the same colours and shapes.  These tests
render both and compare every pixel, which is what keeps the two from drifting
apart.

Needs the SDK headers, the same way tests/run_host_tests.sh does: set
PEBBLE_SDK_PEBBLE to the sdk-core/pebble directory.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gen_art  # noqa: E402

PLATFORMS = {
    "emery": (200, 228),
    "basalt": (144, 168),
    "chalk": (180, 180),
    "gabbro": (260, 260),
}

# city_gen.c writes palette indices; gen_art.py writes colours.  The order is
# the CITY_* enum in city_gen.h.
PALETTE = (
    gen_art.CLEAR, gen_art.BLACK, gen_art.NAVY, gen_art.DKGREY, gen_art.GREY,
    gen_art.AMBER, gen_art.PALE, gen_art.CYAN, gen_art.MAGENTA,
)


def sdk_include():
    pebble = os.environ.get("PEBBLE_SDK_PEBBLE")
    if not pebble and os.environ.get("PEBBLE_SDK_INCLUDE"):
        pebble = os.path.dirname(os.path.dirname(
            os.environ["PEBBLE_SDK_INCLUDE"]))
    return pebble


class CityGenTest(unittest.TestCase):
    """Every check renders the C once and the Python once, and diffs them."""

    @classmethod
    def setUpClass(cls):
        cls.pebble = sdk_include()
        if not cls.pebble:
            raise unittest.SkipTest(
                "set PEBBLE_SDK_PEBBLE to the SDK's sdk-core/pebble directory")
        cls.tmp = tempfile.mkdtemp(prefix="city-gen-")
        cls.binaries = {}
        for platform, (w, h) in PLATFORMS.items():
            out = os.path.join(cls.tmp, platform)
            subprocess.check_call([
                "gcc", "-std=gnu11", "-O2", "-Wall", "-Werror", "-DPBL_COLOR",
                "-DPBL_PLATFORM_%s" % platform.upper(),
                "-DPBL_DISPLAY_WIDTH=%d" % w, "-DPBL_DISPLAY_HEIGHT=%d" % h,
                "-I", os.path.join(ROOT, "tests", "include"),
                "-I", os.path.join(cls.pebble, platform, "include"),
                # message_keys.auto.h and src/resource_ids.auto.h, which
                # pebble.h includes; a `pebble build` generates both, the
                # same dependency tests/run_host_tests.sh has.
                "-I", os.path.join(ROOT, "build", "include"),
                "-I", os.path.join(ROOT, "build", platform),
                os.path.join(ROOT, "tests", "city_gen_ref.c"), "-o", out,
            ])
            cls.binaries[platform] = out

    def render_c(self, platform, args=()):
        return subprocess.check_output([self.binaries[platform]] + list(args))

    def assert_matches(self, platform, produced, x0, width, label):
        """Compares one C-rendered span against the Python reference."""
        layout = gen_art.select(platform)
        expected = gen_art.foreground_span(x0, width)
        self.assertEqual(len(produced), width * layout.FG_H,
                         "%s %s: wrong byte count" % (platform, label))
        for y in range(layout.FG_H):
            row = produced[y * width:(y + 1) * width]
            for x in range(width):
                index = row[x]
                self.assertLess(index, len(PALETTE),
                                "%s %s: palette index %d at (%d,%d)"
                                % (platform, label, index, x, y))
                self.assertEqual(
                    PALETTE[index], expected.px[y][x],
                    "%s %s: pixel (%d,%d), absolute x %d"
                    % (platform, label, x, y, x0 + x))

    def test_tiles_match_the_reference(self):
        """The tiles the watchface generates are the authored panorama."""
        for platform, (w, _) in PLATFORMS.items():
            layout = gen_art.select(platform)
            blob = self.render_c(platform)
            tile_bytes = w * layout.FG_H
            self.assertEqual(len(blob), tile_bytes * layout.FG_TILES)
            for t in range(layout.FG_TILES):
                self.assert_matches(
                    platform, blob[t * tile_bytes:(t + 1) * tile_bytes],
                    t * w, w, "tile %d" % t)

    def test_spans_are_independent_of_where_they_are_cut(self):
        """A tower must not change shape as it crosses a tile boundary.

        Rendering at offsets that are not tile-aligned is the case the watch
        never asks for but the correctness of the whole scheme rests on: if a
        span depended on how it was cut, the two drawings of a straddling
        tower would disagree and the seam would flicker as it scrolled.
        """
        for platform, (w, _) in PLATFORMS.items():
            layout = gen_art.select(platform)
            offsets = (-layout.FG_W, -w, -1, 1, w // 2, w - 1,
                       layout.FG_W - w // 2, layout.FG_W, layout.FG_W + 7,
                       2 * layout.FG_W + 3)
            for x0 in offsets:
                self.assert_matches(platform, self.render_c(
                    platform, (str(x0), str(w))), x0, w, "span at %d" % x0)

    def test_the_panorama_wraps(self):
        """Tile 0 has to continue tile FG_TILES-1, or the loop shows a seam."""
        for platform, (w, _) in PLATFORMS.items():
            layout = gen_art.select(platform)
            # A window centred on the wrap, compared against the reference
            # modulo the panorama width.
            x0 = layout.FG_W - w // 2
            produced = self.render_c(platform, (str(x0), str(w)))
            expected = gen_art.foreground_span(x0 - layout.FG_W, w)
            for y in range(layout.FG_H):
                for x in range(w):
                    self.assertEqual(
                        PALETTE[produced[y * w + x]], expected.px[y][x],
                        "%s: wrap pixel (%d,%d)" % (platform, x, y))


if __name__ == "__main__":
    unittest.main()
