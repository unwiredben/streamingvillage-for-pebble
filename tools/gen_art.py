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


# ================================================================= main ====
def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    gen_sky()
    gen_background()
    gen_foreground()
    gen_billboard()

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
