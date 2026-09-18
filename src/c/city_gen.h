// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#pragma once

#include <pebble.h>

// ---------------------------------------------------------------------------
// The foreground cityscape, generated on the watch instead of shipped as art.
//
// The eight stored tiles were 80-85% of every platform's resource pack, which
// is what made a longer panorama impossible -- gabbro could not even hold the
// eighth tile.  Generating them costs one tile's worth of drawing every time
// the scroll crosses a tile boundary, which is roughly every ten seconds and
// replaces a flash read and decode of the same size, so the frame it lands in
// is no busier than it was before.
//
// What makes it work is that a tile can be drawn on its own.  Towers sit in
// FG_SLOTS evenly spaced cells and everything about the tower in cell n comes
// from n alone, by way of a PRNG seeded from it; nothing accumulates along
// the panorama.  A tower straddling a tile boundary is therefore drawn once
// as one tile's overhang and again as the next tile's, and comes out
// identical both times because neither drawing knows which tile it is in.
//
// tools/gen_art.py carries the same generator in Python -- it is where the
// artwork was authored and it still draws the appstore icons -- and
// tests/test_city_gen.py renders both and compares them pixel for pixel, so
// the two cannot drift apart silently.
// ---------------------------------------------------------------------------

// Lengths derived from the emery reference, as in main.c.
#define EMERY_W 200
#define EMERY_H 228
#define SCALE_X(v) ((v) * PBL_DISPLAY_WIDTH / EMERY_W)
#define SCALE_Y(v) ((v) * PBL_DISPLAY_HEIGHT / EMERY_H)
// Rounded up to even, so a centred inset stays symmetric.
#define EVEN(v) (((v) + 1) & ~1)

// Every platform gets the same long panorama now that the tiles cost nothing
// to store.  A run only scrolls the foreground about one tile, so a longer
// loop is what keeps successive activations from showing the same buildings.
// The cap is 127: city_layer.c holds a tile index in an int8_t.
#define FG_TILES 32

#define FG_H SCALE_Y(200)
#define FG_W ((int32_t)PBL_DISPLAY_WIDTH * FG_TILES)
#define FG_GROUND (158 * FG_H / 200)
#define FG_LANE_MARK (180 * FG_H / 200)
// Most towers top out below the mountain valleys so the ridge stays visible;
// a few landmarks cut up through it.
#define FG_TOP_LANDMARK_MIN (26 * FG_H / 200)
#define FG_TOP_LANDMARK_MAX (52 * FG_H / 200)
#define FG_TOP_COMMON_MIN (58 * FG_H / 200)
#define FG_TOP_COMMON_MAX (90 * FG_H / 200)

// Decorative detail is not scaled: at 0.72x a window grid turns to mush and a
// 1px rim light disappears, so each platform lists its own.  These mirror the
// DECO tables in tools/gen_art.py.
#if defined(PBL_PLATFORM_EMERY)
  #define TOWER_W_MIN 24
  #define TOWER_W_MAX 54
  #define TOWER_PITCH 34
  #define TOWER_JITTER 7
  #define WIN_TOP 5
  #define WIN_BOTTOM 8
  #define WIN_STEP 10
  #define WIN_LEFT 4
  #define WIN_RIGHT 6
  #define WIN_PITCH 8
  #define WIN_W 3
  #define WIN_H 5
  #define MAST_RISE_MIN 6
  #define MAST_RISE_MAX 18
  #define MAST_H 18
  #define MAST_TIP 19
  #define BOX_MIN 6
  #define BOX_H 6
  #define BOX_CAP 2
  #define NEON_MIN_W 30
  #define NEON_INSET 8
  #define NEON_DROP_MIN 8
  #define NEON_DROP_MAX 24
  #define NEON_W 4
  #define NEON_H 26
  #define KERB_H 7
  #define KERB_LINE 5
  #define KERB_LINE_H 2
  #define DASH_STEP 24
  #define DASH_W 12
  #define DASH_H 3
  #define LAMP_START 20
  #define LAMP_STEP 100
  #define LAMP_H 34
  #define ARM_DX 3
  #define ARM_W 8
  #define ARM_H 3
  #define GLOW_DX 2
  #define GLOW_W 6
  #define GLOW_H 2
#elif defined(PBL_PLATFORM_BASALT)
  #define TOWER_W_MIN 18
  #define TOWER_W_MAX 40
  #define TOWER_PITCH 24
  #define TOWER_JITTER 5
  #define WIN_TOP 4
  #define WIN_BOTTOM 6
  #define WIN_STEP 8
  #define WIN_LEFT 3
  #define WIN_RIGHT 5
  #define WIN_PITCH 6
  #define WIN_W 2
  #define WIN_H 4
  #define MAST_RISE_MIN 4
  #define MAST_RISE_MAX 13
  #define MAST_H 13
  #define MAST_TIP 14
  #define BOX_MIN 4
  #define BOX_H 4
  #define BOX_CAP 2
  #define NEON_MIN_W 22
  #define NEON_INSET 6
  #define NEON_DROP_MIN 6
  #define NEON_DROP_MAX 18
  #define NEON_W 3
  #define NEON_H 19
  #define KERB_H 5
  #define KERB_LINE 3
  #define KERB_LINE_H 2
  #define DASH_STEP 18
  #define DASH_W 9
  #define DASH_H 2
  #define LAMP_START 14
  #define LAMP_STEP 72
  #define LAMP_H 25
  #define ARM_DX 2
  #define ARM_W 6
  #define ARM_H 2
  #define GLOW_DX 1
  #define GLOW_W 4
  #define GLOW_H 2
#elif defined(PBL_PLATFORM_CHALK)
  #define TOWER_W_MIN 22
  #define TOWER_W_MAX 49
  #define TOWER_PITCH 30
  #define TOWER_JITTER 6
  #define WIN_TOP 4
  #define WIN_BOTTOM 6
  #define WIN_STEP 8
  #define WIN_LEFT 4
  #define WIN_RIGHT 5
  #define WIN_PITCH 7
  #define WIN_W 3
  #define WIN_H 4
  #define MAST_RISE_MIN 5
  #define MAST_RISE_MAX 14
  #define MAST_H 14
  #define MAST_TIP 15
  #define BOX_MIN 5
  #define BOX_H 5
  #define BOX_CAP 2
  #define NEON_MIN_W 27
  #define NEON_INSET 7
  #define NEON_DROP_MIN 6
  #define NEON_DROP_MAX 19
  #define NEON_W 4
  #define NEON_H 21
  #define KERB_H 6
  #define KERB_LINE 4
  #define KERB_LINE_H 2
  #define DASH_STEP 22
  #define DASH_W 11
  #define DASH_H 2
  #define LAMP_START 18
  #define LAMP_STEP 90
  #define LAMP_H 27
  #define ARM_DX 3
  #define ARM_W 7
  #define ARM_H 2
  #define GLOW_DX 2
  #define GLOW_W 5
  #define GLOW_H 2
#elif defined(PBL_PLATFORM_GABBRO)
  #define TOWER_W_MIN 31
  #define TOWER_W_MAX 70
  #define TOWER_PITCH 44
  #define TOWER_JITTER 9
  #define WIN_TOP 6
  #define WIN_BOTTOM 9
  #define WIN_STEP 11
  #define WIN_LEFT 5
  #define WIN_RIGHT 8
  #define WIN_PITCH 10
  #define WIN_W 4
  #define WIN_H 6
  #define MAST_RISE_MIN 7
  #define MAST_RISE_MAX 21
  #define MAST_H 21
  #define MAST_TIP 22
  #define BOX_MIN 8
  #define BOX_H 7
  #define BOX_CAP 2
  #define NEON_MIN_W 39
  #define NEON_INSET 10
  #define NEON_DROP_MIN 9
  #define NEON_DROP_MAX 27
  #define NEON_W 5
  #define NEON_H 30
  #define KERB_H 8
  #define KERB_LINE 6
  #define KERB_LINE_H 2
  #define DASH_STEP 31
  #define DASH_W 16
  #define DASH_H 3
  #define LAMP_START 26
  #define LAMP_STEP 130
  #define LAMP_H 39
  #define ARM_DX 4
  #define ARM_W 10
  #define ARM_H 3
  #define GLOW_DX 3
  #define GLOW_W 8
  #define GLOW_H 2
#else
  #error "Streaming Village supports emery, basalt, chalk and gabbro."
#endif

// Cell origins are n * FG_W / FG_SLOTS, which spreads the rounding a pixel at
// a time and lands exactly on FG_W -- the panorama wraps with no seam case.
// The street's periods are counted out the same way, because the authored
// spacing divides FG_W on basalt alone and a fixed pixel step would make the
// dashes jump at the wrap.
#define FG_SLOTS ((FG_W + TOWER_PITCH / 2) / TOWER_PITCH)
#define FG_DASHES ((FG_W + DASH_STEP / 2) / DASH_STEP)
#define FG_LAMPS ((FG_W + LAMP_STEP / 2) / LAMP_STEP)
// How far right of its cell origin a tower can reach, and so how far back a
// span has to start scanning to catch everything that overlaps it.
#define FG_SLOT_REACH (TOWER_JITTER + TOWER_W_MAX)

// Palette indices.  Nine colours, so a 4-bit palettised bitmap holds the
// scene with room to spare, and the tile costs the same heap the stored
// bitmap did.
enum {
  CITY_CLEAR = 0,
  CITY_BLACK,
  CITY_NAVY,
  CITY_DKGREY,
  CITY_GREY,
  CITY_AMBER,
  CITY_PALE,
  CITY_CYAN,
  CITY_MAGENTA,
  CITY_PALETTE_LEN = 16,     // GBitmapFormat4BitPalette wants all 16
};

// The palette a generated foreground tile is drawn against.  It has static
// storage, so it can be handed to gbitmap_create_blank_with_palette with
// free_on_destroy false.
GColor *city_gen_palette(void);

// Fills a 4-bit palettised tile with the panorama from absolute x in
// [x0, x0 + width).  `data` and `stride` come from gbitmap_get_data and
// gbitmap_get_bytes_per_row; the tile is FG_H rows tall.
void city_gen_foreground(uint8_t *data, uint16_t stride, int16_t width,
                         int32_t x0);
