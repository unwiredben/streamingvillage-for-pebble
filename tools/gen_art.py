#!/usr/bin/env python3
"""Generate the parallax cityscape artwork for the Streaming Villa watchface.

Each layer is authored as one seamless panorama, then sliced into 200px-wide
tiles.  200px is the width of the Pebble Time 2 display, which guarantees that
any 200px viewport lands on exactly two adjacent tiles -- the watchface only
ever has to hold two bitmaps per layer in memory.

Every colour below is on Pebble's 64-colour grid (channels drawn from
0/85/170/255) and each layer stays at or under 16 unique colours so the
resources can be built as 4-bit palettised bitmaps.
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

SCREEN_W = 200

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

    def slice_tiles(self, prefix, count, tile_w=SCREEN_W):
        for t in range(count):
            tile = Canvas(tile_w, self.h)
            for y in range(self.h):
                src = self.px[y]
                tile.px[y] = [src[(t * tile_w + x) % self.w]
                              for x in range(tile_w)]
            write_png(os.path.join(OUT_DIR, "%s_%d.png" % (prefix, t)), tile)


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
_DITHER_ROTATION = random.Random(4242)


def dither_gradient(canvas, stops):
    """Fills a canvas with a vertical fade through `stops`.

    `stops` is a list of (row, colour).  A row lands on its stop's colour
    exactly, and rows between two stops are an ordered mix of the pair -- so
    repeating a colour in consecutive stops yields a solid band.
    """
    for y in range(canvas.h):
        lo, hi = stops[0], stops[1]
        for i in range(len(stops) - 1):
            if stops[i][0] <= y < stops[i + 1][0]:
                lo, hi = stops[i], stops[i + 1]
                break
        t = (y - lo[0]) / float(hi[0] - lo[0])
        rotation = _DITHER_ROTATION.randrange(DITHER_LEVELS)
        for x in range(canvas.w):
            threshold = DITHER_SEQ[(x + rotation) % DITHER_LEVELS]
            canvas.set(x, y,
                       hi[1] if t > (threshold + 0.5) / DITHER_LEVELS else lo[1])


# ================================================================== sky ====
# The sunset does not scroll, so it lives in one static full-width bitmap
# covering everything above the ground haze.  Keeping it out of the scrolling
# background matters: a dithered gradient that slid sideways would make the
# dither pattern crawl.
SKY_H = 88

# The glow has to finish above the ridge line, since the mountains cover
# everything below their crest.
SKY_STOPS = (
    (0, NAVY), (12, NAVY),      # solid night at the top
    (22, IMPURPLE),
    (31, VIOLET),
    (40, PURPLE),
    (47, MAGENTA),
    (54, FOLLY),
    (59, MELON),
    (64, RAJAH),
    (70, AMBER), (SKY_H, AMBER),  # horizon glow, behind the mountains
)


def gen_sky():
    c = Canvas(SCREEN_W, SKY_H)
    dither_gradient(c, SKY_STOPS)
    write_png(os.path.join(OUT_DIR, "sky.png"), c)


# =========================================================== background ====
# 40px tall, drawn at screen y=48, transparent above the ridge line.  The
# gradient behind it comes from the static sky bitmap, so this layer is nothing
# but mountains: a silhouette that fills solid from its crest all the way to
# the bottom edge of the tile, where main.c's ground fill picks the same colour
# up and carries it to the bottom of the screen.
BG_H = 40
BG_W = 1200
BG_TILES = BG_W // SCREEN_W

BG_RIDGE_FLOOR = 8       # valley height above the bottom edge, in rows
BG_PEAK_MIN = 18         # peak height above the bottom edge
BG_PEAK_MAX = 32
BG_PEAK_COUNT = 22
BG_PEAK_HALF_MIN = 26    # half-width of a peak, in pixels
BG_PEAK_HALF_MAX = 62


def _ridge_profile(rnd):
    """A mountain skyline: the upper envelope of a set of triangular peaks.

    Peak positions are taken modulo the panorama width, so a peak may straddle
    the seam and the profile loops exactly -- no easing needed at the ends.
    """
    profile = [BG_RIDGE_FLOOR] * BG_W
    for _ in range(BG_PEAK_COUNT):
        cx = rnd.randrange(BG_W)
        half = rnd.randint(BG_PEAK_HALF_MIN, BG_PEAK_HALF_MAX)
        peak = rnd.randint(BG_PEAK_MIN, BG_PEAK_MAX)
        for d in range(-half, half + 1):
            # Triangular falloff, with a little jitter so the slopes are not
            # perfectly straight.
            h = peak - (peak - BG_RIDGE_FLOOR) * abs(d) // half
            h += rnd.choice((0, 0, 0, 1, -1))
            x = (cx + d) % BG_W
            if h > profile[x]:
                profile[x] = h
    return profile


def gen_background():
    c = Canvas(BG_W, BG_H)
    rnd = random.Random(20260908)
    ridge = _ridge_profile(rnd)

    for x, h in enumerate(ridge):
        top = BG_H - h
        c.rect(x, top, 1, h, HORIZON)
        # Rim light where the sunset catches the crest.  Step pixels get it
        # too, so the line stays unbroken up the steeper slopes.
        c.set(x, top, RIDGE_CREST)
        step = ridge[(x + 1) % BG_W] - h
        for j in range(1, max(0, step) + 1):
            c.set(x, top - j, RIDGE_CREST)

    c.slice_tiles("bg", BG_TILES)


# =========================================================== foreground ====
# 200px tall with transparency, drawn at screen y=28 so its street lands on
# the bottom edge of the display.  The towers are deliberately tall: they crowd
# the sky down to a thin band of sunset above the horizon.
FG_W, FG_H = 1600, 200
FG_TILES = FG_W // SCREEN_W

FG_GROUND = 158          # top of the sidewalk, in layer-local rows
FG_LANE_MARK = 180       # centre line of the road
WINDOW_COLOURS = (AMBER, AMBER, PALE, CYAN)


def _tower(c, x, w, top, body, rnd):
    # The outline is always the other body colour, so neighbouring towers stay
    # separated whichever way round they fall.
    edge = BLACK if body == NAVY else NAVY
    c.rect(x, top, w, FG_GROUND - top, body)
    c.frame(x, top, w, FG_GROUND - top, edge)

    # Window grid, inset so it never touches the outline.
    for wy in range(top + 5, FG_GROUND - 8, 10):
        for wx in range(x + 4, x + w - 6, 8):
            if rnd.random() < 0.55:
                c.rect(wx, wy, 3, 5, rnd.choice(WINDOW_COLOURS))

    # Roof furniture.
    roll = rnd.random()
    if roll < 0.35:
        mast = x + w // 2
        c.rect(mast, top - rnd.randint(6, 18), 1, 18, edge)
        c.set(mast, top - 19, MAGENTA)
    elif roll < 0.6:
        tw = max(6, w // 3)
        c.rect(x + (w - tw) // 2, top - 6, tw, 6, body)
        c.rect(x + (w - tw) // 2, top - 8, tw, 2, DKGREY)

    # A vertical neon sign on some facades.
    if w >= 30 and rnd.random() < 0.3:
        sx = x + w - 8
        sy = top + rnd.randint(8, 24)
        c.rect(sx, sy, 4, 26, MAGENTA)
        c.frame(sx, sy, 4, 26, edge)


def gen_foreground():
    c = Canvas(FG_W, FG_H)
    rnd = random.Random(776211)

    x = 0
    while x < FG_W:
        w = rnd.randint(24, 54)
        if x + w > FG_W:                      # last block closes the loop
            w = FG_W - x
            if w < 18:
                c.rect(x, 90, w, FG_GROUND - 90, NAVY)
                break
        # Most towers top out below the mountain valleys so the ridge stays
        # visible; a few landmarks cut up through it.
        top = (rnd.randint(26, 52) if rnd.random() < 0.2
               else rnd.randint(58, 90))
        # Near buildings are darker than the distant land, which keeps the
        # ridge line reading as depth rather than more city.
        _tower(c, x, w, top, NAVY if rnd.random() < 0.65 else BLACK, rnd)
        x += w + rnd.randint(0, 3)

    # Street: sidewalk, asphalt, dashed centre line.
    c.rect(0, FG_GROUND, FG_W, 7, DKGREY)
    c.rect(0, FG_GROUND + 5, FG_W, 2, BLACK)
    c.rect(0, FG_GROUND + 7, FG_W, FG_H - FG_GROUND - 7, BLACK)
    for dx in range(0, FG_W, 24):
        c.rect(dx, FG_LANE_MARK, 12, 3, GREY)

    # Street lamps, spaced along the sidewalk.
    for lx in range(20, FG_W, 100):
        c.rect(lx, FG_GROUND - 34, 2, 34, DKGREY)
        c.rect(lx - 3, FG_GROUND - 37, 8, 3, DKGREY)
        c.rect(lx - 2, FG_GROUND - 34, 6, 2, AMBER)

    c.slice_tiles("fg", FG_TILES)


# ============================================================ billboard ====
# 90px tall with transparency, drawn at screen y=100.  A single 320px tile is
# the whole panorama: it is wider than the display, so a 200px viewport still
# only ever spans two tiles -- here the same tile twice, sharing one bitmap.
# 320 is exactly the display width plus the billboard width, which means the
# billboard clears the left edge at the very moment its repeat reaches the
# right edge; the watchface inserts its own pause there to keep the billboard
# away for a couple of seconds.
BB_TILE_W = 320
BB_H = 122
BB_TILES = 1
BB_W = BB_TILE_W * BB_TILES

BB_FRAME_X = 100         # frame origin within a tile, centred
BB_FRAME_W = 120
BB_FRAME_H = 68
BB_PANEL_X = 108         # interior the watchface draws the time into
BB_PANEL_Y = 12
BB_PANEL_W = 104
BB_PANEL_H = 44
BB_POLE_W = 10

# The panel interior stays empty so nothing crowds the time.
BB_ACCENT = PURPLE


def _billboard(c, x, accent):
    c.rect(x, 0, BB_FRAME_W, BB_FRAME_H, GREY)
    c.rect(x + 2, 2, BB_FRAME_W - 4, BB_FRAME_H - 4, accent)
    c.rect(x + 5, 5, BB_FRAME_W - 10, BB_FRAME_H - 10, BLACK)

    # A single pole down the middle.  It runs off the bottom of the display, so
    # it gets no footing.
    px = x + (BB_FRAME_W - BB_POLE_W) // 2
    c.rect(px, BB_FRAME_H, BB_POLE_W, BB_H - BB_FRAME_H, DKGREY)
    c.rect(px, BB_FRAME_H, 2, BB_H - BB_FRAME_H, GREY)

    # Spotlights hanging off the bottom rail.
    for sx in (x + 14, x + BB_FRAME_W - 18):
        c.rect(sx, BB_FRAME_H, 4, 3, DKGREY)
        c.rect(sx, BB_FRAME_H + 3, 4, 1, AMBER)


def gen_billboard():
    c = Canvas(BB_W, BB_H)
    _billboard(c, BB_FRAME_X, BB_ACCENT)
    c.slice_tiles("bb", BB_TILES, BB_TILE_W)


# ============================================================ menu icon ====
# The launcher tints the icon, so it is drawn in greys only: the shades read
# as an alpha ramp rather than as colours.  At 25px the scene has to be pared
# back to the two things that identify the watchface -- the billboard on its
# pole, and a skyline behind it.

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
    stops, last = [], -1
    for row, colour in SKY_STOPS:
        row = row * horizon // SKY_H
        if row <= last:                 # two stops collapsing at small sizes
            row = last + 1
        stops.append((row, colour))
        last = row
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
def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    gen_sky()
    gen_background()
    gen_foreground()
    gen_billboard()
    gen_menu_icon()
    if not os.path.isdir(STORE_DIR):
        os.makedirs(STORE_DIR)
    for size in STORE_SIZES:
        gen_store_icon(size)

    print("sky: 1 image, %d unique colours" %
          len(_read_colours(os.path.join(OUT_DIR, "sky.png"))))
    for prefix, count in (("bg", BG_TILES), ("fg", FG_TILES), ("bb", BB_TILES)):
        colours = set()
        for t in range(count):
            path = os.path.join(OUT_DIR, "%s_%d.png" % (prefix, t))
            tile = _read_colours(path)
            colours |= tile
        print("%s: %d tiles, %d unique colours%s" %
              (prefix, count, len(colours),
               "  *** TOO MANY FOR A PALETTE ***" if len(colours) > 16 else ""))


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
