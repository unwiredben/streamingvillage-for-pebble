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
    def __init__(self, name, screen_w, screen_h, deco, fg_tiles=32):
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

        # -- the tower slot grid the procedural foreground walks --
        # Towers sit in FG_SLOTS evenly spaced cells rather than being packed
        # left to right, so slot n can be drawn without having drawn slot n-1.
        # Cell origins are n * FG_W // FG_SLOTS, which spreads the rounding
        # error a pixel at a time and lands exactly on FG_W -- the panorama
        # wraps with no special case at the seam.
        self.FG_SLOTS = (self.FG_W + deco["tower_pitch"] // 2) // \
            deco["tower_pitch"]
        # How far right of its cell origin a tower can reach, which is how far
        # back a span has to start scanning to catch everything overlapping it.
        self.FG_SLOT_REACH = deco["tower_jitter"] + deco["tower_w"][1]

        # Street furniture is periodic, and its period has to divide FG_W or
        # the pattern jumps at the wrap.  Both are counted out across the
        # panorama instead of stepping by a fixed pixel pitch: the authored
        # spacing is only a target, and dash_step divides FG_W on basalt alone.
        self.FG_DASHES = (self.FG_W + deco["dash_step"] // 2) // \
            deco["dash_step"]
        self.FG_LAMPS = (self.FG_W + deco["lamp_step"] // 2) // \
            deco["lamp_step"]

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
    "tower_w": (24, 54), "tower_pitch": 34, "tower_jitter": 7,
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
    "tower_w": (18, 40), "tower_pitch": 24, "tower_jitter": 5,
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
    "tower_w": (22, 49), "tower_pitch": 30, "tower_jitter": 6,
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
    "tower_w": (31, 70), "tower_pitch": 44, "tower_jitter": 9,
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
    # readme.md.  The foreground panorama is the same length everywhere now
    # that it is generated on the watch rather than stored: the old six-tile
    # gabbro limit was a 256KB resource pack, not a display.
    "chalk": Layout("chalk", 180, 180, CHALK_DECO),
    "gabbro": Layout("gabbro", 260, 260, GABBRO_DECO),
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


class SpanCanvas(object):
    """A window onto the panorama, covering absolute x in [x0, x0 + w).

    Coordinates handed to it are panorama-absolute and anything outside the
    window is *clipped*, not wrapped.  That is what lets one tower be drawn
    into two adjacent spans and come out identical in both: its pixels depend
    on the tower alone, never on which span is being rendered.
    """

    def __init__(self, x0, w, h, fill=CLEAR):
        self.x0 = x0
        self.w = w
        self.h = h
        self.px = [[fill] * w for _ in range(h)]

    def set(self, x, y, c):
        i = x - self.x0
        if 0 <= i < self.w and 0 <= y < self.h:
            self.px[y][i] = c

    def rect(self, x, y, w, h, c):
        i0 = max(0, x - self.x0)
        i1 = min(self.w, x - self.x0 + w)
        if i1 <= i0:
            return
        run = [c] * (i1 - i0)
        for j in range(max(0, y), min(self.h, y + h)):
            self.px[j][i0:i1] = run

    def frame(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)


# ------------------------------------------------------------------ prng ---
# The procedural foreground has to produce the same tower from the same slot
# index every time, on the watch and here, so it cannot use random.Random.
# Splitmix32 is four lines of integer C and is seeded per slot, which is what
# makes a slot renderable on its own.
#
# The generators below only ever ask an rng for these four things, so the
# legacy foreground can go on using random.Random through SysRng and the two
# paths keep sharing _tower().
class Splitmix32(object):
    MASK = 0xFFFFFFFF

    def __init__(self, seed, index=0):
        self.state = (seed ^ (index * 2654435761)) & self.MASK

    def next(self):
        self.state = (self.state + 0x9E3779B9) & self.MASK
        z = self.state
        z = ((z ^ (z >> 16)) * 0x21F0AAAD) & self.MASK
        z = ((z ^ (z >> 15)) * 0x735A2D97) & self.MASK
        return z ^ (z >> 15)

    def below(self, n):
        return self.next() % n

    def between(self, lo, hi):
        return lo + self.next() % (hi - lo + 1)

    def chance(self, percent):
        return self.next() % 100 < percent

    def pick(self, seq):
        return seq[self.next() % len(seq)]


class SysRng(object):
    """The same four operations on random.Random, for the legacy panorama.

    `below` and `chance` are spelled so they agree exactly with the
    `random() < 0.55` tests this replaced, which keeps the pre-existing
    artwork byte-identical.
    """

    def __init__(self, seed):
        self.r = random.Random(seed)

    def below(self, n):
        return int(self.r.random() * n)

    def between(self, lo, hi):
        return self.r.randint(lo, hi)

    def chance(self, percent):
        return self.r.random() < percent / 100.0

    def pick(self, seq):
        return self.r.choice(seq)


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


def background_canvas():
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

    return c


def gen_background():
    background_canvas().slice_tiles("bg", L.BG_TILES)


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
            if rnd.chance(55):
                c.rect(wx, wy, d["win_w"], d["win_h"],
                       rnd.pick(WINDOW_COLOURS))

    # Roof furniture.
    roll = rnd.below(100)
    if roll < 35:
        mast = x + w // 2
        c.rect(mast, top - rnd.between(*d["mast_rise"]), 1, d["mast_h"], edge)
        c.set(mast, top - d["mast_tip"], MAGENTA)
    elif roll < 60:
        tw = max(d["box_min"], w // 3)
        c.rect(x + (w - tw) // 2, top - d["box_h"], tw, d["box_h"], body)
        c.rect(x + (w - tw) // 2, top - d["box_h"] - d["box_cap"], tw,
               d["box_cap"], DKGREY)

    # A vertical neon sign on some facades.
    if w >= d["neon_min_w"] and rnd.chance(30):
        sx = x + w - d["neon_inset"]
        sy = top + rnd.between(*d["neon_drop"])
        c.rect(sx, sy, d["neon_w"], d["neon_h"], MAGENTA)
        c.frame(sx, sy, d["neon_w"], d["neon_h"], edge)


def _lamp(c, lx):
    d = L.deco
    c.rect(lx, L.FG_GROUND - d["lamp_h"], 2, d["lamp_h"], DKGREY)
    c.rect(lx - d["arm_dx"], L.FG_GROUND - d["lamp_h"] - d["arm_h"],
           d["arm_w"], d["arm_h"], DKGREY)
    c.rect(lx - d["glow_dx"], L.FG_GROUND - d["lamp_h"], d["glow_w"],
           d["glow_h"], AMBER)


def legacy_foreground():
    """The authored panorama: towers packed left to right in one pass.

    Kept for comparison against the procedural version -- it cannot be
    rendered a tile at a time, because `x` accumulates across the whole
    panorama and every tower depends on all the towers before it.
    """
    d = L.deco
    c = Canvas(L.FG_W, L.FG_H)
    rnd = SysRng(776211)

    x = 0
    while x < L.FG_W:
        w = rnd.between(*d["tower_w"])
        if x + w > L.FG_W:                    # last block closes the loop
            w = L.FG_W - x
            if w < 18:
                c.rect(x, L.FG_STUB_TOP, w, L.FG_GROUND - L.FG_STUB_TOP, NAVY)
                break
        top = (rnd.between(*L.FG_TOP_LANDMARK) if rnd.chance(20)
               else rnd.between(*L.FG_TOP_COMMON))
        # Near buildings are darker than the distant land, which keeps the
        # ridge line reading as depth rather than more city.
        _tower(c, x, w, top, NAVY if rnd.chance(65) else BLACK, rnd)
        x += w + rnd.between(0, 3)

    # Street: sidewalk, asphalt, dashed centre line.
    c.rect(0, L.FG_GROUND, L.FG_W, d["kerb_h"], DKGREY)
    c.rect(0, L.FG_GROUND + d["kerb_line"], L.FG_W, d["kerb_line_h"], BLACK)
    c.rect(0, L.FG_GROUND + d["kerb_h"], L.FG_W,
           L.FG_H - L.FG_GROUND - d["kerb_h"], BLACK)
    for dx in range(0, L.FG_W, d["dash_step"]):
        c.rect(dx, L.FG_LANE_MARK, d["dash_w"], d["dash_h"], GREY)

    for lx in range(d["lamp_start"], L.FG_W, d["lamp_step"]):
        _lamp(c, lx)

    return c


# ------------------------------------------------- procedural foreground ---
# The same scene, rebuilt so that any horizontal span of it can be drawn on
# its own.  That is the whole point: the watch can then generate a tile into a
# blank bitmap when the scroll reaches it, instead of loading one of eight
# stored 11-30KB images, and the panorama can be far longer than the resource
# pack could ever hold.
#
# Two properties make it work, and tests/test_billboard_art.py checks both:
#
#   * every feature is addressed by an *index*, and everything about it comes
#     from that index alone.  A tower straddling a tile boundary is drawn once
#     as the right-hand tile's overhang and again as the left-hand tile's, and
#     both come out identical because neither render knows which tile it is.
#
#   * indices run over all of Z.  Index i maps to cell i mod FG_SLOTS of turn
#     i // FG_SLOTS, so the panorama repeats exactly at FG_W with no seam case
#     -- tile 0 simply draws the negative-index towers hanging over from the
#     end of the previous turn.
#
# Note that C's / and % truncate toward zero where Python's floor, so the
# port has to spell the floor division out; _floor_div marks every place that
# matters.
FG_SEED = 776211


def _floor_div(a, b):
    """Floor division, called out because C's `/` is not this for a < 0."""
    return a // b


def _cell_x(index, count):
    """Absolute x of periodic feature `index`, for any index in Z."""
    k = index % count                      # floor-mod: 0 <= k < count
    return _floor_div(index - k, count) * L.FG_W + k * L.FG_W // count


def _cells_touching(count, x0, x1, reach):
    """Indices whose cell origin lands in [x0 - reach, x1), plus a margin.

    Cell origins are monotone in the index, so the bounds only have to be
    conservative; anything drawn outside the span is clipped away.
    """
    lo = _floor_div((x0 - reach) * count, L.FG_W) - 1
    hi = _floor_div(x1 * count, L.FG_W) + 1
    return range(lo, hi + 1)


def fg_slot(index):
    """Everything about tower slot `index`, from the index alone.

    The order the values are drawn in is part of the format: the C has to ask
    for them in exactly this order, including evaluating the landmark test
    before the height it selects.
    """
    d = L.deco
    k = index % L.FG_SLOTS
    rng = Splitmix32(FG_SEED, k)

    x = _cell_x(index, L.FG_SLOTS) + rng.below(d["tower_jitter"] + 1)
    w = rng.between(*d["tower_w"])
    top = (rng.between(*L.FG_TOP_LANDMARK) if rng.chance(20)
           else rng.between(*L.FG_TOP_COMMON))
    body = NAVY if rng.chance(65) else BLACK
    return x, w, top, body, rng


def foreground_span(x0, w):
    """Draws panorama x in [x0, x0 + w) into a standalone canvas.

    This is the function the C port becomes: give it a blank tile-sized bitmap
    and the tile's absolute x, and it fills it.
    """
    d = L.deco
    c = SpanCanvas(x0, w, L.FG_H)

    # Ascending index, so where two towers overlap the right-hand one wins --
    # and wins the same way in whichever span it is drawn.
    for i in _cells_touching(L.FG_SLOTS, x0, x0 + w, L.FG_SLOT_REACH):
        x, tw, top, body, rng = fg_slot(i)
        if x >= x0 + w or x + tw <= x0:
            continue          # no rng to skip past: the slot owns its stream
        _tower(c, x, tw, top, body, rng)

    # Street: sidewalk, asphalt, dashed centre line.
    c.rect(x0, L.FG_GROUND, w, d["kerb_h"], DKGREY)
    c.rect(x0, L.FG_GROUND + d["kerb_line"], w, d["kerb_line_h"], BLACK)
    c.rect(x0, L.FG_GROUND + d["kerb_h"], w,
           L.FG_H - L.FG_GROUND - d["kerb_h"], BLACK)
    for i in _cells_touching(L.FG_DASHES, x0, x0 + w, d["dash_w"]):
        c.rect(_cell_x(i, L.FG_DASHES), L.FG_LANE_MARK, d["dash_w"],
               d["dash_h"], GREY)

    # Street lamps, spaced along the sidewalk.
    reach = d["lamp_start"] + d["arm_w"] + d["arm_dx"]
    for i in _cells_touching(L.FG_LAMPS, x0, x0 + w, reach):
        _lamp(c, _cell_x(i, L.FG_LAMPS) + d["lamp_start"])

    return c


def write_foreground_tiles():
    """Writes the panorama out as tiles, the way it used to ship.

    Nothing builds against these any more -- src/c/city_gen.c draws the
    foreground on the watch -- but rendering them is still the quickest way
    to look at what a change here did.
    """
    for t in range(L.FG_TILES):
        write_png(art_path("fg_%d" % t),
                  foreground_span(t * L.SCREEN_W, L.SCREEN_W))


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
    for prefix, count in (("bg", L.BG_TILES), ("bb", L.BB_TILES)):
        colours = set()
        for t in range(count):
            colours |= _read_colours(art_path("%s_%d" % (prefix, t)))
        print("%s: %s, %d tiles, %d unique colours%s" %
              (L.name, prefix, count, len(colours),
               "  *** TOO MANY FOR A PALETTE ***" if len(colours) > 16 else ""))


def verify_spans(trials=24, seed=99):
    """Checks that a span depends only on where it is, not on how it was cut.

    The panorama assembled from the tiles the watchface would ship is the
    reference; spans rendered at arbitrary offsets -- negative, straddling
    every seam, past the wrap -- have to agree with it pixel for pixel.  A
    failure here is exactly the bug that would show as a tower changing shape
    as it crosses a tile boundary on the watch.
    """
    reference = [[] for _ in range(L.FG_H)]
    for t in range(L.FG_TILES):
        tile = foreground_span(t * L.SCREEN_W, L.SCREEN_W)
        for y in range(L.FG_H):
            reference[y].extend(tile.px[y])

    rnd = random.Random(seed)
    cases = [("wide", 0, L.FG_W)]
    for x0 in (-L.FG_W, -L.SCREEN_W, -1, 1, L.SCREEN_W - 1, L.FG_W - 1, L.FG_W,
               L.FG_W + 7, 2 * L.FG_W + 3):
        cases.append(("edge", x0, L.SCREEN_W))
    for _ in range(trials):
        cases.append(("random", rnd.randrange(-2 * L.FG_W, 3 * L.FG_W),
                      rnd.randint(1, L.SCREEN_W)))
    # Every tile seam, from both sides, at a width that straddles it.
    for t in range(L.FG_TILES):
        cases.append(("seam", t * L.SCREEN_W - L.SCREEN_W // 2, L.SCREEN_W))

    failures = 0
    for kind, x0, w in cases:
        span = foreground_span(x0, w)
        for y in range(L.FG_H):
            row = span.px[y]
            for i in range(w):
                if row[i] != reference[y][(x0 + i) % L.FG_W]:
                    print("  FAIL %s span x0=%d w=%d: pixel (%d,%d) "
                          "abs x=%d, %r != %r" %
                          (kind, x0, w, i, y, x0 + i, row[i],
                           reference[y][(x0 + i) % L.FG_W]))
                    failures += 1
                    break
            if failures:
                break
        if failures:
            break
    print("%s: %d spans checked, %s" %
          (L.name, len(cases), "OK" if not failures else "FAILED"))
    return failures


# ------------------------------------------------------------- previews ----
# Not artwork: a wide PNG of the whole scrolling scene, composited the way the
# watchface stacks it, so the skyline can be judged before any C is written.
PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "build", "preview")


def _compose(dst, src, x, y):
    for j in range(src.h):
        if not 0 <= y + j < dst.h:
            continue
        row = src.px[j]
        out = dst.px[y + j]
        for i in range(src.w):
            c = row[i]
            if c[3]:
                out[(x + i) % dst.w] = c


def write_preview(name, fg):
    c = Canvas(fg.w, L.SCREEN_H, HORIZON)

    sky = Canvas(fg.w, L.SKY_H)
    dither_gradient(sky, scale_stops(SKY_STOPS, L.SKY_H))
    _compose(c, sky, 0, 0)

    ridge = background_canvas()
    for x in range(0, fg.w, ridge.w):
        _compose(c, ridge, x, L.BG_Y)

    _compose(c, fg, 0, L.FG_Y)

    if not os.path.isdir(PREVIEW_DIR):
        os.makedirs(PREVIEW_DIR)
    path = os.path.join(PREVIEW_DIR, "%s~%s.png" % (name, L.name))
    write_png(path, c)
    print("%s: %dx%d" % (os.path.relpath(path), c.w, c.h))


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--platform", action="append", choices=sorted(PLATFORMS),
                    help="restrict to one platform; repeatable")
    ap.add_argument("--fg-tiles", type=int, metavar="N",
                    help="override the foreground panorama length, to see how "
                         "much variety a longer one buys")
    ap.add_argument("--tower-pitch", type=int, metavar="PX",
                    help="override the slot pitch, to trade gaps between "
                         "towers against overlap")
    ap.add_argument("--write-tiles", action="store_true",
                    help="write the cityscape out as tiles the way it used "
                         "to ship, for diffing against an earlier run")
    ap.add_argument("--verify", action="store_true",
                    help="check span independence; writes nothing")
    ap.add_argument("--preview", action="store_true",
                    help="write wide previews of the scene to build/preview, "
                         "procedural and legacy, instead of artwork")
    args = ap.parse_args()

    platforms = args.platform or sorted(PLATFORMS)
    if args.fg_tiles or args.tower_pitch:
        for name in platforms:
            layout = PLATFORMS[name]
            deco = dict(layout.deco)
            if args.tower_pitch:
                deco["tower_pitch"] = args.tower_pitch
            PLATFORMS[name] = Layout(layout.name, layout.SCREEN_W,
                                     layout.SCREEN_H, deco,
                                     fg_tiles=args.fg_tiles or layout.FG_TILES)

    if args.verify:
        failures = 0
        for platform in platforms:
            select(platform)
            failures += verify_spans()
        raise SystemExit(1 if failures else 0)

    if args.write_tiles:
        if not os.path.isdir(OUT_DIR):
            os.makedirs(OUT_DIR)
        for platform in platforms:
            select(platform)
            write_foreground_tiles()
        return

    if args.preview:
        # A non-default panorama length gets its own filename, so a long run
        # does not clobber the one the shipped tile count produced.
        tag = "" if not args.fg_tiles else "-%dtiles" % args.fg_tiles
        for platform in platforms:
            select(platform)
            write_preview("fg-procedural" + tag, foreground_span(0, L.FG_W))
            write_preview("fg-legacy" + tag, legacy_foreground())
        return

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    for platform in platforms:
        select(platform)
        gen_sky()
        gen_background()
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
