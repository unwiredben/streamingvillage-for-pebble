#!/usr/bin/env python3
# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Generate the parallax cityscape artwork for the Streaming Village watchface.

The background and foreground are authored as seamless panoramas, then sliced
into display-width tiles.  The billboard is cropped to its artwork width, with
a logical repeat of one display width plus one board on the watch.  A viewport
overlaps at most two logical tiles, so only two bitmaps per layer need to be
held in memory.

Every colour below is on Pebble's 64-colour grid (channels drawn from
0/85/170/255) and each layer stays at or under 16 unique colours so the
resources can be built as 4-bit palettised bitmaps.

The scene is generated once per target platform.  Files are written with a
`~platform` tag -- `fg_0~emery.png`, `fg_0~basalt.png` -- which is how the SDK
picks the right set: package.json declares the bare `images/fg_0.png` and
`find_most_specific_filename` resolves it against the platform's tags.
"""

import os
import random
import struct
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "resources", "images")

# Appstore artwork is not packed into the watch, so it lives outside the
# resource tree.
STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "store")

# ---------------------------------------------------------------- palette ---
CLEAR    = (0, 0, 0, 0)
BLACK    = (0, 0, 0, 255)
WHITE    = (255, 255, 255, 255)
GREY     = (170, 170, 170, 255)
DKGREY   = (85, 85, 85, 255)
NAVY     = (0, 0, 85, 255)
IMPURPLE = (85, 0, 85, 255)
VIOLET   = (85, 0, 170, 255)
PURPLE   = (170, 0, 170, 255)
FOLLY    = (255, 0, 85, 255)
MELON    = (255, 85, 85, 255)
AMBER    = (255, 170, 0, 255)
PALE     = (255, 255, 170, 255)
RAJAH    = (255, 170, 85, 255)
CYAN     = (0, 170, 255, 255)
NEON     = (0, 255, 255, 255)
MAGENTA  = (255, 0, 170, 255)
STEEL    = (85, 85, 170, 255)

# The land below the ridge line.  main.c fills the screen under the background
# layer with this same colour, so the bottom edge of the background tiles has
# to be exactly it or the seam shows.
HORIZON = IMPURPLE
RIDGE_CREST = RAJAH


# =============================================================== geometry ====
# Every constant that depends on the display size lives in a Layout.  emery is
# the reference the artwork was authored against; a smaller platform derives
# from it by integer scaling arranged to be the identity at 200x228, so
# regenerating after a change here has to leave the emery PNGs byte-identical.
#
# Decorative detail is *not* scaled.  At 0.72x a window grid turns to mush and
# a 1px rim light disappears, so each platform lists its own -- see DECO.
#
# main.c carries the same layout in its own #defines.  Change them together or
# the layers stop lining up; tests/test_billboard_art.py checks the invariants
# both files derive from.
EMERY_W, EMERY_H = 200, 228

# Authored reference for the sky gradient stops, below.
SKY_REF_H = 88


def _even(value):
    """Rounds up to an even number, so a centred inset stays symmetric."""
    return (value + 1) & ~1


class Layout(object):
    def __init__(self, name, screen_w, screen_h, deco, fg_tiles=8):
        self.name = name
        self.SCREEN_W = screen_w
        self.SCREEN_H = screen_h
        self.deco = deco

        def x(value):                   # a horizontal length
            return value * screen_w // EMERY_W

        def y(value):                   # a vertical length
            return value * screen_h // EMERY_H

        # -- sky: static, from the top of the screen down to the ridge --
        self.SKY_H = y(SKY_REF_H)

        # -- background: the ridge, bottom-aligned on the sky --
        self.BG_TILES = 6
        self.BG_W = screen_w * self.BG_TILES
        self.BG_H = y(40)
        self.BG_Y = self.SKY_H - self.BG_H
        self.BG_RIDGE_FLOOR = 8 * self.BG_H // 40
        self.BG_PEAK_MIN = 18 * self.BG_H // 40
        self.BG_PEAK_MAX = 32 * self.BG_H // 40
        self.BG_PEAK_COUNT = 22 * self.BG_W // 1200
        self.BG_PEAK_HALF_MIN = x(26)
        self.BG_PEAK_HALF_MAX = x(62)

        # -- foreground: towers and street, bottom-aligned on the screen --
        self.FG_TILES = fg_tiles
        self.FG_W = screen_w * self.FG_TILES
        self.FG_H = y(200)
        self.FG_Y = screen_h - self.FG_H
        self.FG_GROUND = 158 * self.FG_H // 200
        self.FG_LANE_MARK = 180 * self.FG_H // 200
        # Most towers top out below the mountain valleys so the ridge stays
        # visible; a few landmarks cut up through it.
        self.FG_TOP_LANDMARK = (26 * self.FG_H // 200, 52 * self.FG_H // 200)
        self.FG_TOP_COMMON = (58 * self.FG_H // 200, 90 * self.FG_H // 200)
        self.FG_STUB_TOP = 90 * self.FG_H // 200

        # -- billboard: a tile one display wider than the board, so the board
        #    clears the left edge exactly as its repeat reaches the right one --
        self.BB_TILES = 1
        self.BB_FRAME_W = _even(x(120))
        self.BB_FRAME_H = y(68)
        self.BB_H = y(122)
        self.BB_Y = y(134)
        self.BB_TILE_W = screen_w + self.BB_FRAME_W
        self.BB_FRAME_X = (self.BB_TILE_W - self.BB_FRAME_W) // 2
        self.BB_POLE_W = _even(x(10))

        # The blank interior the watchface draws the time into.  It is inset
        # further than the artwork's own black panel, so nothing crowds the
        # digits.
        self.BB_PANEL_X = self.BB_FRAME_X + deco["panel_inset"]
        self.BB_PANEL_W = self.BB_FRAME_W - 2 * deco["panel_inset"]
        self.BB_PANEL_Y = 12 * self.BB_FRAME_H // 68
        self.BB_PANEL_H = 44 * self.BB_FRAME_H // 68


EMERY_DECO = {
    # billboard
    "panel_inset": 8,
    "ring": 2, "art_inset": 5, "pole_lit": 2,
    "spot_left": 14, "spot_right": 18,
    "spot_w": 4, "spot_h": 3, "spot_glow": 1,
    # towers
    "tower_w": (24, 54),
    "win_top": 5, "win_bottom": 8, "win_step": 10,
    "win_left": 4, "win_right": 6, "win_pitch": 8,
    "win_w": 3, "win_h": 5,
    "mast_rise": (6, 18), "mast_h": 18, "mast_tip": 19,
    "box_min": 6, "box_h": 6, "box_cap": 2,
    "neon_min_w": 30, "neon_inset": 8, "neon_drop": (8, 24),
    "neon_w": 4, "neon_h": 26,
    # street
    "kerb_h": 7, "kerb_line": 5, "kerb_line_h": 2,
    "dash_step": 24, "dash_w": 12, "dash_h": 3,
    "lamp_start": 20, "lamp_step": 100, "lamp_h": 34,
    "arm_dx": 3, "arm_w": 8, "arm_h": 3,
    "glow_dx": 2, "glow_w": 6, "glow_h": 2,
}

BASALT_DECO = {
    "panel_inset": 6,
    "ring": 2, "art_inset": 5, "pole_lit": 2,
    "spot_left": 10, "spot_right": 13,
    "spot_w": 3, "spot_h": 2, "spot_glow": 1,
    "tower_w": (18, 40),
    "win_top": 4, "win_bottom": 6, "win_step": 8,
    "win_left": 3, "win_right": 5, "win_pitch": 6,
    "win_w": 2, "win_h": 4,
    "mast_rise": (4, 13), "mast_h": 13, "mast_tip": 14,
    "box_min": 4, "box_h": 4, "box_cap": 2,
    "neon_min_w": 22, "neon_inset": 6, "neon_drop": (6, 18),
    "neon_w": 3, "neon_h": 19,
    "kerb_h": 5, "kerb_line": 3, "kerb_line_h": 2,
    "dash_step": 18, "dash_w": 9, "dash_h": 2,
    "lamp_start": 14, "lamp_step": 72, "lamp_h": 25,
    "arm_dx": 2, "arm_w": 6, "arm_h": 2,
    "glow_dx": 1, "glow_w": 4, "glow_h": 2,
}

CHALK_DECO = {
    "panel_inset": 7,
    "ring": 2, "art_inset": 5, "pole_lit": 2,
    "spot_left": 13, "spot_right": 16,
    "spot_w": 4, "spot_h": 2, "spot_glow": 1,
    "tower_w": (22, 49),
    "win_top": 4, "win_bottom": 6, "win_step": 8,
    "win_left": 4, "win_right": 5, "win_pitch": 7,
    "win_w": 3, "win_h": 4,
    "mast_rise": (5, 14), "mast_h": 14, "mast_tip": 15,
    "box_min": 5, "box_h": 5, "box_cap": 2,
    "neon_min_w": 27, "neon_inset": 7, "neon_drop": (6, 19),
    "neon_w": 4, "neon_h": 21,
    "kerb_h": 6, "kerb_line": 4, "kerb_line_h": 2,
    "dash_step": 22, "dash_w": 11, "dash_h": 2,
    "lamp_start": 18, "lamp_step": 90, "lamp_h": 27,
    "arm_dx": 3, "arm_w": 7, "arm_h": 2,
    "glow_dx": 2, "glow_w": 5, "glow_h": 2,
}

GABBRO_DECO = {
    "panel_inset": 10,
    "ring": 3, "art_inset": 6, "pole_lit": 3,
    "spot_left": 18, "spot_right": 23,
    "spot_w": 5, "spot_h": 3, "spot_glow": 1,
    "tower_w": (31, 70),
    "win_top": 6, "win_bottom": 9, "win_step": 11,
    "win_left": 5, "win_right": 8, "win_pitch": 10,
    "win_w": 4, "win_h": 6,
    "mast_rise": (7, 21), "mast_h": 21, "mast_tip": 22,
    "box_min": 8, "box_h": 7, "box_cap": 2,
    "neon_min_w": 39, "neon_inset": 10, "neon_drop": (9, 27),
    "neon_w": 5, "neon_h": 30,
    "kerb_h": 8, "kerb_line": 6, "kerb_line_h": 2,
    "dash_step": 31, "dash_w": 16, "dash_h": 3,
    "lamp_start": 26, "lamp_step": 130, "lamp_h": 39,
    "arm_dx": 4, "arm_w": 10, "arm_h": 3,
    "glow_dx": 3, "glow_w": 8, "glow_h": 2,
}

PLATFORMS = {
    "emery": Layout("emery", 200, 228, EMERY_DECO),
    "basalt": Layout("basalt", 144, 168, BASALT_DECO),
    # gabbro is round, and the scene is simply clipped by the circle -- see
    # readme.md.  Six foreground tiles rather than eight: at 260px wide the
    # eight-tile panorama alone would be 237KB of a 256KB resource pack.
    "chalk": Layout("chalk", 180, 180, CHALK_DECO),
    "gabbro": Layout("gabbro", 260, 260, GABBRO_DECO, fg_tiles=6),
}

# The layout every generator below reads.  select() points it at a platform.
L = PLATFORMS["emery"]


def select(platform):
    global L
    L = PLATFORMS[platform]
    return L


def art_path(stem):
    return os.path.join(OUT_DIR, "%s~%s.png" % (stem, L.name))


# ------------------------------------------------------------- png writer ---
def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, canvas):
    raw = bytearray()
    for row in canvas.px:
        raw.append(0)                       # filter type 0
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))
    header = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 6, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) +
            _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)


# ------------------------------------------------------------- tiny canvas ---
class Canvas(object):
    """A panorama that wraps horizontally, so shapes may straddle the seam."""

    def __init__(self, w, h, fill=CLEAR):
        self.w = w
        self.h = h
        self.px = [[fill] * w for _ in range(h)]

    def set(self, x, y, c):
        if 0 <= y < self.h:
            self.px[y][x % self.w] = c

    def rect(self, x, y, w, h, c):
        for j in range(y, y + h):
            if 0 <= j < self.h:
                row = self.px[j]
                for i in range(x, x + w):
                    row[i % self.w] = c

    def frame(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def bands(self, spec):
        """spec: list of (y0, y1, colour) filled across the full width."""
        for y0, y1, c in spec:
            self.rect(0, y0, self.w, y1 - y0, c)

    def slice_tiles(self, prefix, count, tile_w=None):
        tile_w = L.SCREEN_W if tile_w is None else tile_w
        for t in range(count):
            tile = Canvas(tile_w, self.h)
            for y in range(self.h):
                src = self.px[y]
                tile.px[y] = [src[(t * tile_w + x) % self.w]
                              for x in range(tile_w)]
            write_png(art_path("%s_%d" % (prefix, t)), tile)


# ------------------------------------------------------------- dithering ---
# The sky is a purely vertical fade, so every pixel in a row shares the same
# blend fraction and all that matters is how evenly a row's dots are spread.
# A 2-D Bayer matrix is a poor fit here: each of its rows spans only part of
# the threshold range, so neighbouring rows come out at noticeably different
# densities and the fade picks up horizontal streaks.
#
# Instead each row uses the full 0..63 threshold range in van der Corput
# (bit-reversed) order, which spreads any prefix of it evenly across the row,
# and the sequence is rotated by a different random amount per row so the dots
# do not line up into columns or diagonals.
DITHER_LEVELS = 64


def _bit_reverse_6(value):
    out = 0
    for bit in range(6):
        out = (out << 1) | ((value >> bit) & 1)
    return out


DITHER_SEQ = tuple(_bit_reverse_6(i) for i in range(DITHER_LEVELS))
DITHER_SEED = 4242


def dither_gradient(canvas, stops):
    """Fills a canvas with a vertical fade through `stops`.

    `stops` is a list of (row, colour).  A row lands on its stop's colour
    exactly, and rows between two stops are an ordered mix of the pair -- so
    repeating a colour in consecutive stops yields a solid band.

    The per-row rotation stream restarts for every gradient, so an image's
    dither depends only on that image and not on what was generated before it.
    """
    rotations = random.Random(DITHER_SEED)
    for y in range(canvas.h):
        lo, hi = stops[0], stops[1]
        for i in range(len(stops) - 1):
            if stops[i][0] <= y < stops[i + 1][0]:
                lo, hi = stops[i], stops[i + 1]
                break
        t = (y - lo[0]) / float(hi[0] - lo[0])
        rotation = rotations.randrange(DITHER_LEVELS)
        for x in range(canvas.w):
            threshold = DITHER_SEQ[(x + rotation) % DITHER_LEVELS]
            canvas.set(x, y,
                       hi[1] if t > (threshold + 0.5) / DITHER_LEVELS else lo[1])


# ================================================================== sky ====
# The sunset does not scroll, so it lives in one static full-width bitmap
# covering everything above the ground haze.  Keeping it out of the scrolling
# background matters: a dithered gradient that slid sideways would make the
# dither pattern crawl.
#
# The glow has to finish above the ridge line, since the mountains cover
# everything below their crest.  Rows are authored against SKY_REF_H and
# requantised to whatever the platform's sky height is.
SKY_STOPS = (
    (0, NAVY), (12, NAVY),      # solid night at the top
    (22, IMPURPLE),
    (31, VIOLET),
    (40, PURPLE),
    (47, MAGENTA),
    (54, FOLLY),
    (59, MELON),
    (64, RAJAH),
    (70, AMBER), (SKY_REF_H, AMBER),  # horizon glow, behind the mountains
)


def scale_stops(stops, height):
    """Requantises gradient stops from SKY_REF_H rows to `height` rows."""
    out, last = [], -1
    for row, colour in stops:
        row = row * height // SKY_REF_H
        if row <= last:                 # two stops collapsing at small sizes
            row = last + 1
        out.append((row, colour))
        last = row
    return out


def gen_sky():
    c = Canvas(L.SCREEN_W, L.SKY_H)
    dither_gradient(c, scale_stops(SKY_STOPS, L.SKY_H))
    write_png(art_path("sky"), c)


# =========================================================== background ====
# Drawn just above the sky's bottom edge, transparent above the ridge line.
# The gradient behind it comes from the static sky bitmap, so this layer is
# nothing but mountains: a silhouette that fills solid from its crest all the
# way to the bottom edge of the tile, where main.c's ground fill picks the same
# colour up and carries it to the bottom of the screen.
def _ridge_profile(rnd):
    """A mountain skyline: the upper envelope of a set of triangular peaks.

    Peak positions are taken modulo the panorama width, so a peak may straddle
    the seam and the profile loops exactly -- no easing needed at the ends.
    """
    profile = [L.BG_RIDGE_FLOOR] * L.BG_W
    for _ in range(L.BG_PEAK_COUNT):
        cx = rnd.randrange(L.BG_W)
        half = rnd.randint(L.BG_PEAK_HALF_MIN, L.BG_PEAK_HALF_MAX)
        peak = rnd.randint(L.BG_PEAK_MIN, L.BG_PEAK_MAX)
        for d in range(-half, half + 1):
            # Triangular falloff, with a little jitter so the slopes are not
            # perfectly straight.
            h = peak - (peak - L.BG_RIDGE_FLOOR) * abs(d) // half
            h += rnd.choice((0, 0, 0, 1, -1))
            x = (cx + d) % L.BG_W
            if h > profile[x]:
                profile[x] = h
    return profile


def gen_background():
    c = Canvas(L.BG_W, L.BG_H)
    rnd = random.Random(20260908)
    ridge = _ridge_profile(rnd)

    for x, h in enumerate(ridge):
        top = L.BG_H - h
        c.rect(x, top, 1, h, HORIZON)
        # Rim light where the sunset catches the crest.  Step pixels get it
        # too, so the line stays unbroken up the steeper slopes.
        c.set(x, top, RIDGE_CREST)
        step = ridge[(x + 1) % L.BG_W] - h
        for j in range(1, max(0, step) + 1):
            c.set(x, top - j, RIDGE_CREST)

    c.slice_tiles("bg", L.BG_TILES)


# =========================================================== foreground ====
# Bottom-aligned on the display so its street lands on the bottom edge.  The
# towers are deliberately tall: they crowd the sky down to a thin band of
# sunset above the horizon.
WINDOW_COLOURS = (AMBER, AMBER, PALE, CYAN)


def _tower(c, x, w, top, body, rnd):
    d = L.deco
    # The outline is always the other body colour, so neighbouring towers stay
    # separated whichever way round they fall.
    edge = BLACK if body == NAVY else NAVY
    c.rect(x, top, w, L.FG_GROUND - top, body)
    c.frame(x, top, w, L.FG_GROUND - top, edge)

    # Window grid, inset so it never touches the outline.
    for wy in range(top + d["win_top"], L.FG_GROUND - d["win_bottom"],
                    d["win_step"]):
        for wx in range(x + d["win_left"], x + w - d["win_right"],
                        d["win_pitch"]):
            if rnd.random() < 0.55:
                c.rect(wx, wy, d["win_w"], d["win_h"],
                       rnd.choice(WINDOW_COLOURS))

    # Roof furniture.
    roll = rnd.random()
    if roll < 0.35:
        mast = x + w // 2
        c.rect(mast, top - rnd.randint(*d["mast_rise"]), 1, d["mast_h"], edge)
        c.set(mast, top - d["mast_tip"], MAGENTA)
    elif roll < 0.6:
        tw = max(d["box_min"], w // 3)
        c.rect(x + (w - tw) // 2, top - d["box_h"], tw, d["box_h"], body)
        c.rect(x + (w - tw) // 2, top - d["box_h"] - d["box_cap"], tw,
               d["box_cap"], DKGREY)

    # A vertical neon sign on some facades.
    if w >= d["neon_min_w"] and rnd.random() < 0.3:
        sx = x + w - d["neon_inset"]
        sy = top + rnd.randint(*d["neon_drop"])
        c.rect(sx, sy, d["neon_w"], d["neon_h"], MAGENTA)
        c.frame(sx, sy, d["neon_w"], d["neon_h"], edge)


def gen_foreground():
    d = L.deco
    c = Canvas(L.FG_W, L.FG_H)
    rnd = random.Random(776211)

    x = 0
    while x < L.FG_W:
        w = rnd.randint(*d["tower_w"])
        if x + w > L.FG_W:                    # last block closes the loop
            w = L.FG_W - x
            if w < 18:
                c.rect(x, L.FG_STUB_TOP, w, L.FG_GROUND - L.FG_STUB_TOP, NAVY)
                break
        top = (rnd.randint(*L.FG_TOP_LANDMARK) if rnd.random() < 0.2
               else rnd.randint(*L.FG_TOP_COMMON))
        # Near buildings are darker than the distant land, which keeps the
        # ridge line reading as depth rather than more city.
        _tower(c, x, w, top, NAVY if rnd.random() < 0.65 else BLACK, rnd)
        x += w + rnd.randint(0, 3)

    # Street: sidewalk, asphalt, dashed centre line.
    c.rect(0, L.FG_GROUND, L.FG_W, d["kerb_h"], DKGREY)
    c.rect(0, L.FG_GROUND + d["kerb_line"], L.FG_W, d["kerb_line_h"], BLACK)
    c.rect(0, L.FG_GROUND + d["kerb_h"], L.FG_W,
           L.FG_H - L.FG_GROUND - d["kerb_h"], BLACK)
    for dx in range(0, L.FG_W, d["dash_step"]):
        c.rect(dx, L.FG_LANE_MARK, d["dash_w"], d["dash_h"], GREY)

    # Street lamps, spaced along the sidewalk.
    for lx in range(d["lamp_start"], L.FG_W, d["lamp_step"]):
        c.rect(lx, L.FG_GROUND - d["lamp_h"], 2, d["lamp_h"], DKGREY)
        c.rect(lx - d["arm_dx"], L.FG_GROUND - d["lamp_h"] - d["arm_h"],
               d["arm_w"], d["arm_h"], DKGREY)
        c.rect(lx - d["glow_dx"], L.FG_GROUND - d["lamp_h"], d["glow_w"],
               d["glow_h"], AMBER)

    c.slice_tiles("fg", L.FG_TILES)


# ============================================================ billboard ====
# A single tile is the whole panorama: it is wider than the display, so the
# viewport still only ever spans two tiles -- here the same tile twice, sharing
# one bitmap.  The tile is exactly the display width plus the billboard width,
# which means the billboard clears the left edge at the very moment its repeat
# reaches the right edge; the watchface inserts its own pause there to keep the
# billboard away for a couple of seconds.
#
# The panel interior stays empty so nothing crowds the time.
BB_ACCENT = PURPLE


def _billboard(c, x, accent):
    d = L.deco
    ring, inset = d["ring"], d["art_inset"]
    c.rect(x, 0, L.BB_FRAME_W, L.BB_FRAME_H, GREY)
    c.rect(x + ring, ring, L.BB_FRAME_W - 2 * ring, L.BB_FRAME_H - 2 * ring,
           accent)
    c.rect(x + inset, inset, L.BB_FRAME_W - 2 * inset,
           L.BB_FRAME_H - 2 * inset, BLACK)

    # A single pole down the middle.  It runs off the bottom of the display, so
    # it gets no footing.
    px = x + (L.BB_FRAME_W - L.BB_POLE_W) // 2
    c.rect(px, L.BB_FRAME_H, L.BB_POLE_W, L.BB_H - L.BB_FRAME_H, DKGREY)
    c.rect(px, L.BB_FRAME_H, d["pole_lit"], L.BB_H - L.BB_FRAME_H, GREY)

    # Spotlights hanging off the bottom rail.
    for sx in (x + d["spot_left"], x + L.BB_FRAME_W - d["spot_right"]):
        c.rect(sx, L.BB_FRAME_H, d["spot_w"], d["spot_h"], DKGREY)
        c.rect(sx, L.BB_FRAME_H + d["spot_h"], d["spot_w"], d["spot_glow"],
               AMBER)


def gen_billboard():
    # Keep the logical repeat in the watchface, but do not store the
    # transparent margins on either side of the artwork.
    c = Canvas(L.BB_FRAME_W, L.BB_H)
    _billboard(c, 0, BB_ACCENT)
    write_png(art_path("bb_0"), c)


# ============================================================ menu icon ====
# The launcher tints the icon, so it is drawn in greys only: the shades read
# as an alpha ramp rather than as colours.  At 25px the scene has to be pared
# back to the two things that identify the watchface -- the billboard on its
# pole, and a skyline behind it.  It is the same on every platform, so it is
# written untagged and shared.

MENU_W = 25
MENU_H = 25

MENU_PANEL_Y = 2
MENU_PANEL_H = 12
MENU_POLE_X = 11
MENU_POLE_W = 3

# (x, width, top row).  The far row is the darker of the two greys, which at
# this size is all the depth cueing there is room for.
MENU_SKYLINE_FAR = ((1, 4, 18), (6, 3, 20), (10, 5, 17), (16, 4, 19),
                    (21, 3, 18))
MENU_SKYLINE_NEAR = ((0, 5, 21), (5, 4, 22), (9, 7, 21), (16, 5, 22),
                     (21, 4, 21))

# Four digit blocks and a colon, standing in for the clock on the panel.  Any
# real glyphs would be illegible here, but the silhouette still reads as a
# time.
MENU_DIGITS = (4, 8, 14, 18)


def gen_menu_icon():
    c = Canvas(MENU_W, MENU_H)

    for row, shade in ((MENU_SKYLINE_FAR, DKGREY), (MENU_SKYLINE_NEAR, GREY)):
        for x, w, top in row:
            c.rect(x, top, w, MENU_H - top, shade)

    # The pole, with the same lit left edge the full-size billboard has.
    c.rect(MENU_POLE_X, MENU_PANEL_Y + MENU_PANEL_H, MENU_POLE_W,
           MENU_SKYLINE_NEAR[2][2] - (MENU_PANEL_Y + MENU_PANEL_H), GREY)
    c.rect(MENU_POLE_X, MENU_PANEL_Y + MENU_PANEL_H, 1,
           MENU_SKYLINE_NEAR[2][2] - (MENU_PANEL_Y + MENU_PANEL_H), WHITE)

    # Frame, then the panel it surrounds, then the time on it.
    c.rect(1, MENU_PANEL_Y, MENU_W - 2, MENU_PANEL_H, WHITE)
    c.rect(2, MENU_PANEL_Y + 1, MENU_W - 4, MENU_PANEL_H - 2, DKGREY)
    for x in MENU_DIGITS:
        c.rect(x, MENU_PANEL_Y + 3, 3, 6, WHITE)
    c.rect(12, MENU_PANEL_Y + 4, 1, 2, WHITE)
    c.rect(12, MENU_PANEL_Y + 7, 1, 2, WHITE)

    write_png(os.path.join(OUT_DIR, "menu_icon.png"), c)


# =========================================================== store icon ====
# The appstore listing wants square artwork at a couple of sizes.  These are
# not watch resources -- nothing here is packed into the app -- so the palette
# limit does not apply, but the icons are still drawn from the same colours and
# the same dither as the watchface so the listing and the watch match.
#
# Both sizes are composed natively rather than scaled from one master: at 80px
# a downscale would turn the towers into mush, so the layout is expressed as
# fractions of the icon and the detail thins out on its own as it shrinks.

STORE_SIZES = (80, 144)

# A 3x5 pixel font, enough for the time on the billboard.  Anything smaller
# stops being readable at 80px and anything larger crowds the panel.
FONT_3X5 = {
    "0": ("###", "# #", "# #", "# #", "###"),
    "1": (" # ", "## ", " # ", " # ", "###"),
    "2": ("###", "  #", "###", "#  ", "###"),
    "3": ("###", "  #", "###", "  #", "###"),
    "4": ("# #", "# #", "###", "  #", "  #"),
    "5": ("###", "#  ", "###", "  #", "###"),
    "6": ("###", "#  ", "###", "# #", "###"),
    "7": ("###", "  #", "  #", "  #", "  #"),
    "8": ("###", "# #", "###", "# #", "###"),
    "9": ("###", "# #", "###", "  #", "###"),
    ":": (" ", "#", " ", "#", " "),
}

# The hour every watch in every catalogue photo shows.
STORE_TIME = "10:09"


def _text_width(text):
    return sum(len(FONT_3X5[ch][0]) for ch in text) + len(text) - 1


def _draw_text(c, text, x, y, scale, colour):
    for ch in text:
        glyph = FONT_3X5[ch]
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "#":
                    c.rect(x + gx * scale, y + gy * scale, scale, scale, colour)
        x += (len(glyph[0]) + 1) * scale


def _blit(dst, src, y):
    for j in range(src.h):
        dst.px[y + j][:src.w] = list(src.px[j])


def _store_sky(c, size, horizon):
    """The same sunset as the watchface, requantised to the icon's height."""
    stops = scale_stops(SKY_STOPS, horizon)
    sky = Canvas(size, stops[-1][0] + 1)
    dither_gradient(sky, stops)
    _blit(c, sky, 0)


def _store_ridge(c, size, rnd):
    base = size * 47 // 100
    profile = [base] * size
    for _ in range(max(3, size // 22)):
        cx = rnd.randrange(size)
        half = rnd.randint(size * 8 // 100, size * 26 // 100)
        peak = base - rnd.randint(size * 4 // 100, size * 12 // 100)
        for d in range(-half, half + 1):
            h = peak + (base - peak) * abs(d) // half
            x = cx + d
            if 0 <= x < size and h < profile[x]:
                profile[x] = h

    for x, top in enumerate(profile):
        c.rect(x, top, 1, size - top, HORIZON)
        c.set(x, top, RIDGE_CREST)
        # Carry the rim light up the risers so the crest stays unbroken.
        if x + 1 < size:
            for j in range(1, max(0, top - profile[x + 1]) + 1):
                c.set(x, top - j, RIDGE_CREST)


def _store_towers(c, size, ground, rnd):
    win = max(1, size // 60)            # window block, 1px at 80 and 2px at 144
    pitch = win * 3
    x = 0
    while x < size:
        w = rnd.randint(size * 9 // 100, size * 19 // 100)
        top = rnd.randint(size * 40 // 100, size * 62 // 100)
        body = NAVY if rnd.random() < 0.65 else BLACK
        edge = BLACK if body == NAVY else NAVY

        c.rect(x, top, w, ground - top, body)
        c.frame(x, top, w, ground - top, edge)

        for wy in range(top + pitch, ground - pitch, pitch + win):
            for wx in range(x + pitch, x + w - pitch, pitch + win):
                if rnd.random() < 0.5:
                    c.rect(wx, wy, win, win * 2, rnd.choice(WINDOW_COLOURS))

        # A mast on the taller blocks, the one bit of roof furniture that still
        # registers at this scale.
        if rnd.random() < 0.3:
            mast = x + w // 2
            h = rnd.randint(size * 3 // 100, size * 8 // 100)
            c.rect(mast, top - h, max(1, size // 90), h, edge)
            c.set(mast, top - h - 1, MAGENTA)

        x += w + rnd.randint(0, max(1, size // 60))


def _store_street(c, size, ground):
    kerb = max(2, size * 4 // 100)
    c.rect(0, ground, size, kerb, DKGREY)
    c.rect(0, ground + kerb, size, size - ground - kerb, BLACK)

    dash = max(2, size * 6 // 100)
    lane = ground + kerb + (size - ground - kerb) // 2
    for dx in range(dash // 2, size, dash * 2):
        c.rect(dx, lane, dash, max(1, size // 80), GREY)


def _store_billboard(c, size, ground):
    fw = size * 72 // 100
    fh = size * 30 // 100
    fx = (size - fw) // 2
    fy = size * 20 // 100

    # The frame's two rings, in the same proportions as the full-size art.
    ring = max(1, round(2 * fw / 120.0))
    inset = max(ring + 1, round(5 * fw / 120.0))

    pole_w = max(3, fw * 10 // 120)
    pole_x = fx + (fw - pole_w) // 2
    c.rect(pole_x, fy + fh, pole_w, ground - fy - fh + 2, DKGREY)
    c.rect(pole_x, fy + fh, max(1, pole_w // 4), ground - fy - fh + 2, GREY)

    c.rect(fx, fy, fw, fh, GREY)
    c.rect(fx + ring, fy + ring, fw - 2 * ring, fh - 2 * ring, BB_ACCENT)
    c.rect(fx + inset, fy + inset, fw - 2 * inset, fh - 2 * inset, BLACK)

    # Spotlights on the bottom rail, throwing a sliver of light upward.
    lamp = max(2, fw // 20)
    for sx in (fx + fw // 6, fx + fw - fw // 6 - lamp):
        c.rect(sx, fy + fh, lamp, max(1, lamp // 2), DKGREY)
        c.rect(sx, fy + fh + max(1, lamp // 2), lamp, max(1, lamp // 3), AMBER)

    panel_w = fw - 2 * inset
    panel_h = fh - 2 * inset
    scale = min((panel_w - 2) // _text_width(STORE_TIME), (panel_h - 2) // 5)
    scale = max(1, scale)
    tw = _text_width(STORE_TIME) * scale
    _draw_text(c, STORE_TIME, fx + inset + (panel_w - tw) // 2,
               fy + inset + (panel_h - 5 * scale) // 2, scale, WHITE)


def gen_store_icon(size):
    rnd = random.Random(31415 + size)
    c = Canvas(size, size, BLACK)
    ground = size * 80 // 100

    _store_sky(c, size, size * 52 // 100)
    _store_ridge(c, size, rnd)
    _store_towers(c, size, ground, rnd)
    _store_street(c, size, ground)
    _store_billboard(c, size, ground)

    write_png(os.path.join(STORE_DIR, "icon-%d.png" % size), c)


# ================================================================= main ====
def report():
    """Prints each layer's colour count; over 16 breaks SmallestPalette."""
    print("%s: sky, %d unique colours" %
          (L.name, len(_read_colours(art_path("sky")))))
    for prefix, count in (("bg", L.BG_TILES), ("fg", L.FG_TILES),
                          ("bb", L.BB_TILES)):
        colours = set()
        for t in range(count):
            colours |= _read_colours(art_path("%s_%d" % (prefix, t)))
        print("%s: %s, %d tiles, %d unique colours%s" %
              (L.name, prefix, count, len(colours),
               "  *** TOO MANY FOR A PALETTE ***" if len(colours) > 16 else ""))


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    for platform in PLATFORMS:
        select(platform)
        gen_sky()
        gen_background()
        gen_foreground()
        gen_billboard()
        report()

    gen_menu_icon()
    if not os.path.isdir(STORE_DIR):
        os.makedirs(STORE_DIR)
    for size in STORE_SIZES:
        gen_store_icon(size)


def _read_colours(path):
    """Re-read a written PNG and collect its unique RGBA values."""
    with open(path, "rb") as fh:
        blob = fh.read()
    pos, w, h, idat = 8, 0, 0, b""
    while pos < len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        data = blob[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", data[:8])
        elif tag == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = w * 4 + 1
    colours = set()
    for y in range(h):
        row = raw[y * stride + 1:(y + 1) * stride]
        for x in range(w):
            colours.add(tuple(row[x * 4:x * 4 + 4]))
    return colours


if __name__ == "__main__":
    main()
