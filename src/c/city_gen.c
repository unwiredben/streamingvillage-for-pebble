// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#include "city_gen.h"

// ------------------------------------------------------------------ prng ---
// Splitmix32, seeded per slot.  Seeding from the slot index rather than
// running one stream along the panorama is the whole trick: it is what lets
// slot n be drawn without having drawn slot n-1.
#define FG_SEED 776211u

typedef struct {
  uint32_t state;
} CityRng;

static void rng_init(CityRng *rng, uint32_t index) {
  rng->state = FG_SEED ^ (index * 2654435761u);
}

static uint32_t rng_next(CityRng *rng) {
  uint32_t z = (rng->state += 0x9E3779B9u);
  z = (z ^ (z >> 16)) * 0x21F0AAADu;
  z = (z ^ (z >> 15)) * 0x735A2D97u;
  return z ^ (z >> 15);
}

static uint32_t rng_below(CityRng *rng, uint32_t n) {
  return rng_next(rng) % n;
}

static int rng_between(CityRng *rng, int lo, int hi) {
  return lo + (int)(rng_next(rng) % (uint32_t)(hi - lo + 1));
}

static bool rng_chance(CityRng *rng, uint32_t percent) {
  return rng_next(rng) % 100 < percent;
}

// ---------------------------------------------------------------- layout ---
// C's / and % truncate toward zero where Python's floor, and the span scan
// runs off the left end of the panorama on purpose, so both are spelled out.
static int32_t floor_div(int32_t a, int32_t b) {
  int32_t q = a / b;
  if (a % b != 0 && (a < 0) != (b < 0)) {
    q--;
  }
  return q;
}

static int32_t floor_mod(int32_t a, int32_t b) {
  int32_t m = a % b;
  if (m != 0 && (m < 0) != (b < 0)) {
    m += b;
  }
  return m;
}

// Absolute x of periodic feature `index`, for any index -- negative ones are
// the previous turn of the panorama hanging over the left edge.
static int32_t cell_x(int32_t index, int32_t count) {
  const int32_t k = floor_mod(index, count);
  return (index - k) / count * FG_W + k * FG_W / count;
}

// ------------------------------------------------------------------ span ---
// A window onto the panorama covering absolute x in [x0, x0 + w).  Anything
// outside is clipped, never wrapped: a tower's pixels depend on the tower
// alone, which is what makes the two renders of a straddling tower agree.
typedef struct {
  uint8_t *data;
  uint16_t stride;
  int32_t x0;
  int16_t w;
} CitySpan;

// Pixels are packed two to a byte, leftmost in the high nibble.
static void span_rect(CitySpan *s, int32_t x, int y, int w, int h,
                      uint8_t index) {
  int32_t i0 = x - s->x0;
  int32_t i1 = i0 + w;
  if (i0 < 0) {
    i0 = 0;
  }
  if (i1 > s->w) {
    i1 = s->w;
  }
  if (i1 <= i0) {
    return;
  }

  int y0 = y;
  int y1 = y + h;
  if (y0 < 0) {
    y0 = 0;
  }
  if (y1 > FG_H) {
    y1 = FG_H;
  }

  const uint8_t pair = (uint8_t)((index << 4) | index);
  for (int row = y0; row < y1; row++) {
    uint8_t *p = s->data + (size_t)row * s->stride;
    int32_t i = i0;
    if (i & 1) {                      // odd start: low nibble of its byte
      p[i >> 1] = (uint8_t)((p[i >> 1] & 0xF0) | index);
      i++;
    }
    const int32_t whole = i1 & ~1;
    if (whole > i) {
      memset(p + (i >> 1), pair, (size_t)((whole - i) >> 1));
      i = whole;
    }
    if (i < i1) {                     // odd end: high nibble of its byte
      p[i >> 1] = (uint8_t)((p[i >> 1] & 0x0F) | (uint8_t)(index << 4));
    }
  }
}

static void span_set(CitySpan *s, int32_t x, int y, uint8_t index) {
  span_rect(s, x, y, 1, 1, index);
}

static void span_frame(CitySpan *s, int32_t x, int y, int w, int h,
                       uint8_t index) {
  span_rect(s, x, y, w, 1, index);
  span_rect(s, x, y + h - 1, w, 1, index);
  span_rect(s, x, y, 1, h, index);
  span_rect(s, x + w - 1, y, 1, h, index);
}

// ---------------------------------------------------------------- towers ---
static const uint8_t WINDOW_COLOURS[4] = {
  CITY_AMBER, CITY_AMBER, CITY_PALE, CITY_CYAN,
};

// The order the values below are drawn in is part of the format: change it
// and tools/gen_art.py stops agreeing, which tests/test_city_gen.py catches.
static void tower(CitySpan *s, int32_t x, int w, int top, uint8_t body,
                  CityRng *rng) {
  // The outline is always the other body colour, so neighbouring towers stay
  // separated whichever way round they fall.
  const uint8_t edge = (body == CITY_NAVY) ? CITY_BLACK : CITY_NAVY;
  span_rect(s, x, top, w, FG_GROUND - top, body);
  span_frame(s, x, top, w, FG_GROUND - top, edge);

  // Window grid, inset so it never touches the outline.
  for (int wy = top + WIN_TOP; wy < FG_GROUND - WIN_BOTTOM; wy += WIN_STEP) {
    for (int32_t wx = x + WIN_LEFT; wx < x + w - WIN_RIGHT; wx += WIN_PITCH) {
      if (rng_chance(rng, 55)) {
        span_rect(s, wx, wy, WIN_W, WIN_H,
                  WINDOW_COLOURS[rng_next(rng) % 4]);
      }
    }
  }

  // Roof furniture.
  const uint32_t roll = rng_below(rng, 100);
  if (roll < 35) {
    const int32_t mast = x + w / 2;
    span_rect(s, mast, top - rng_between(rng, MAST_RISE_MIN, MAST_RISE_MAX), 1,
              MAST_H, edge);
    span_set(s, mast, top - MAST_TIP, CITY_MAGENTA);
  } else if (roll < 60) {
    const int tw = (w / 3 > BOX_MIN) ? w / 3 : BOX_MIN;
    span_rect(s, x + (w - tw) / 2, top - BOX_H, tw, BOX_H, body);
    span_rect(s, x + (w - tw) / 2, top - BOX_H - BOX_CAP, tw, BOX_CAP,
              CITY_DKGREY);
  }

  // A vertical neon sign on some facades.
  if (w >= NEON_MIN_W && rng_chance(rng, 30)) {
    const int32_t sx = x + w - NEON_INSET;
    const int sy = top + rng_between(rng, NEON_DROP_MIN, NEON_DROP_MAX);
    span_rect(s, sx, sy, NEON_W, NEON_H, CITY_MAGENTA);
    span_frame(s, sx, sy, NEON_W, NEON_H, edge);
  }
}

static void lamp(CitySpan *s, int32_t lx) {
  span_rect(s, lx, FG_GROUND - LAMP_H, 2, LAMP_H, CITY_DKGREY);
  span_rect(s, lx - ARM_DX, FG_GROUND - LAMP_H - ARM_H, ARM_W, ARM_H,
            CITY_DKGREY);
  span_rect(s, lx - GLOW_DX, FG_GROUND - LAMP_H, GLOW_W, GLOW_H, CITY_AMBER);
}

// ----------------------------------------------------------------- entry ---
static GColor s_palette[CITY_PALETTE_LEN] = {
  [CITY_CLEAR]   = { .argb = GColorClearARGB8 },
  [CITY_BLACK]   = { .argb = GColorBlackARGB8 },
  [CITY_NAVY]    = { .argb = GColorOxfordBlueARGB8 },
  [CITY_DKGREY]  = { .argb = GColorDarkGrayARGB8 },
  [CITY_GREY]    = { .argb = GColorLightGrayARGB8 },
  [CITY_AMBER]   = { .argb = GColorChromeYellowARGB8 },
  [CITY_PALE]    = { .argb = GColorPastelYellowARGB8 },
  [CITY_CYAN]    = { .argb = GColorBlueMoonARGB8 },
  [CITY_MAGENTA] = { .argb = GColorMagentaARGB8 },
};

GColor *city_gen_palette(void) {
  return s_palette;
}

void city_gen_foreground(uint8_t *data, uint16_t stride, int16_t width,
                         int32_t x0) {
  CitySpan span = {
    .data = data,
    .stride = stride,
    .x0 = x0,
    .w = width,
  };
  memset(data, (CITY_CLEAR << 4) | CITY_CLEAR, (size_t)stride * FG_H);

  // Ascending index, so where two towers overlap the right-hand one wins --
  // and wins the same way in whichever span it is drawn.
  const int32_t first =
      floor_div((x0 - FG_SLOT_REACH) * FG_SLOTS, FG_W) - 1;
  const int32_t last = floor_div((x0 + width) * FG_SLOTS, FG_W) + 1;
  for (int32_t i = first; i <= last; i++) {
    CityRng rng;
    rng_init(&rng, (uint32_t)floor_mod(i, FG_SLOTS));

    const int32_t x = cell_x(i, FG_SLOTS) + (int32_t)rng_below(&rng, TOWER_JITTER + 1);
    const int w = rng_between(&rng, TOWER_W_MIN, TOWER_W_MAX);
    const int top = rng_chance(&rng, 20)
        ? rng_between(&rng, FG_TOP_LANDMARK_MIN, FG_TOP_LANDMARK_MAX)
        : rng_between(&rng, FG_TOP_COMMON_MIN, FG_TOP_COMMON_MAX);
    // Near buildings are darker than the distant land, which keeps the ridge
    // line reading as depth rather than more city.
    const uint8_t body = rng_chance(&rng, 65) ? CITY_NAVY : CITY_BLACK;

    if (x >= x0 + width || x + w <= x0) {
      continue;          // nothing to skip past: the slot owns its stream
    }
    tower(&span, x, w, top, body, &rng);
  }

  // Street: sidewalk, asphalt, dashed centre line.
  span_rect(&span, x0, FG_GROUND, width, KERB_H, CITY_DKGREY);
  span_rect(&span, x0, FG_GROUND + KERB_LINE, width, KERB_LINE_H, CITY_BLACK);
  span_rect(&span, x0, FG_GROUND + KERB_H, width, FG_H - FG_GROUND - KERB_H,
            CITY_BLACK);
  for (int32_t i = floor_div((x0 - DASH_W) * FG_DASHES, FG_W) - 1;
       i <= floor_div((x0 + width) * FG_DASHES, FG_W) + 1; i++) {
    span_rect(&span, cell_x(i, FG_DASHES), FG_LANE_MARK, DASH_W, DASH_H,
              CITY_GREY);
  }

  // Street lamps, spaced along the sidewalk.
  const int32_t reach = LAMP_START + ARM_W + ARM_DX;
  for (int32_t i = floor_div((x0 - reach) * FG_LAMPS, FG_W) - 1;
       i <= floor_div((x0 + width) * FG_LAMPS, FG_W) + 1; i++) {
    lamp(&span, cell_x(i, FG_LAMPS) + LAMP_START);
  }
}
