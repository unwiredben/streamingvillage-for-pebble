# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Check the generated artwork against the geometry the watchface assumes."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("art", ROOT / "tools/gen_art.py")
art = importlib.util.module_from_spec(spec)
spec.loader.exec_module(art)


def read_png(path):
    data = path.read_bytes()
    offset, compressed = 8, b""
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        tag = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if tag == b"IHDR":
            width, height = struct.unpack_from(">II", body)
        elif tag == b"IDAT":
            compressed += body
        offset += length + 12
    raw = zlib.decompress(compressed)
    stride = width * 4 + 1
    rows = []
    for y in range(height):
        assert raw[y * stride] == 0  # generator uses unfiltered RGBA rows
        row = raw[y * stride + 1:(y + 1) * stride]
        rows.append([tuple(row[x:x + 4]) for x in range(0, width * 4, 4)])
    return width, height, rows


class LayoutInvariantTest(unittest.TestCase):
    """The relationships src/c/main.c derives its own #defines from.

    A mismatch here means the artwork and the watchface have drifted apart,
    which otherwise only shows up as a seam on the watch.
    """

    def test_invariants_hold_on_every_platform(self):
        for name, L in art.PLATFORMS.items():
            with self.subTest(platform=name):
                # The sky's bottom edge is where the ridge sits.
                self.assertEqual(L.BG_Y + L.BG_H, L.SKY_H)
                # The foreground's street lands on the bottom of the display.
                self.assertEqual(L.FG_Y + L.FG_H, L.SCREEN_H)
                # A tile is the display plus one board, so the board clears the
                # left edge exactly as its repeat reaches the right one.
                self.assertEqual(L.BB_TILE_W, L.SCREEN_W + L.BB_FRAME_W)
                # Which leaves the artwork centred in its tile.
                self.assertEqual(L.BB_FRAME_X, L.SCREEN_W // 2)
                # The pole runs off the bottom rather than getting a footing.
                self.assertGreater(L.BB_Y + L.BB_H, L.SCREEN_H)
                # Panoramas are a whole number of tiles.
                self.assertEqual(L.BG_W, L.SCREEN_W * L.BG_TILES)
                self.assertEqual(L.FG_W, L.SCREEN_W * L.FG_TILES)
                # No tile is narrower than the display, or the viewport could
                # straddle three of them and city_layer's two slots would not
                # be enough.
                for tile_w in (L.SCREEN_W, L.BB_TILE_W):
                    self.assertGreaterEqual(tile_w, L.SCREEN_W)

    def test_emery_matches_the_authored_reference(self):
        """The scaling has to be the identity at the size it was authored at."""
        L = art.PLATFORMS["emery"]
        self.assertEqual((L.SCREEN_W, L.SCREEN_H), (art.EMERY_W, art.EMERY_H))
        self.assertEqual(L.SKY_H, 88)
        self.assertEqual((L.BG_Y, L.BG_H), (48, 40))
        self.assertEqual((L.FG_Y, L.FG_H), (28, 200))
        self.assertEqual((L.BB_Y, L.BB_H), (134, 122))
        self.assertEqual((L.BB_FRAME_X, L.BB_FRAME_W), (100, 120))
        self.assertEqual(L.BB_TILE_W, 320)


# Every platform the watchface targets has the same 256KB appstore ceiling on
# its resource pack (MAX_RESOURCES_SIZE_APPSTORE in the SDK's
# pebble_sdk_platform.py).  Exceeding it still builds and sideloads -- the hard
# limit is 1024KB -- so nothing else catches it until the store rejects the pbw.
APPSTORE_RESOURCE_LIMIT = 256 * 1024


def palettised_size(path):
    """Bytes the SDK's `SmallestPalette` pbi costs for one image.

    The narrowest bit depth the colour count allows, with byte-aligned rows --
    the same arithmetic readme.md's memory table uses.
    """
    width, height, rows = read_png(path)
    colours = len({px for row in rows for px in row})
    assert colours <= 16, "%s has %d colours, too many to palettise" % (
        path.name, colours)
    bits = 1 if colours <= 2 else 2 if colours <= 4 else 4
    return (width * bits + 7) // 8 * height


class ResourceBudgetTest(unittest.TestCase):
    def test_pack_fits_the_appstore_limit(self):
        """The stored artwork, which is everything but the cityscape."""
        for name, L in art.PLATFORMS.items():
            with self.subTest(platform=name):
                images = ROOT / "resources/images"
                total = palettised_size(images / ("sky~%s.png" % name))
                total += palettised_size(images / ("bb_0~%s.png" % name))
                for i in range(L.BG_TILES):
                    total += palettised_size(
                        images / ("bg_%d~%s.png" % (i, name)))
                # Pbi headers and palettes add a couple of percent on top of
                # the pixel data, so leave the tail of the budget alone.
                self.assertLess(total, APPSTORE_RESOURCE_LIMIT * 95 // 100)

    def test_the_foreground_is_not_a_resource(self):
        """src/c/city_gen.c draws it, so nothing should be shipping it.

        Putting the tiles back would quietly cost four fifths of the pack
        again, and on gabbro it is what the six-tile limit used to be about.
        """
        package = json.loads((ROOT / "package.json").read_text())
        names = [entry["name"]
                 for entry in package["pebble"]["resources"]["media"]]
        self.assertEqual([n for n in names if n.startswith("IMG_FG")], [])
        self.assertEqual(
            sorted((ROOT / "resources/images").glob("fg_*.png")), [])


class BillboardArtTest(unittest.TestCase):
    def test_cropped_resource_preserves_original_pixels(self):
        for platform in art.PLATFORMS:
            with self.subTest(platform=platform):
                L = art.select(platform)
                # Reconstruct the original full-tile artwork independently of
                # gen_billboard, then check the crop threw away only margin.
                original = art.Canvas(L.BB_TILE_W, L.BB_H)
                art._billboard(original, L.BB_FRAME_X, art.BB_ACCENT)

                with tempfile.TemporaryDirectory() as directory:
                    old_output = art.OUT_DIR
                    try:
                        art.OUT_DIR = directory
                        art.gen_billboard()
                    finally:
                        art.OUT_DIR = old_output
                    name = "bb_0~%s.png" % platform
                    width, height, rows = read_png(Path(directory) / name)

                self.assertEqual((width, height), (L.BB_FRAME_W, L.BB_H))
                margin = [art.CLEAR] * L.BB_FRAME_X
                for y, row in enumerate(rows):
                    self.assertEqual(margin + row + margin, original.px[y])
                # The checked-in bitmap must match the generator too.
                self.assertEqual(
                    read_png(ROOT / "resources/images" / name),
                    (width, height, rows))


if __name__ == "__main__":
    unittest.main()
