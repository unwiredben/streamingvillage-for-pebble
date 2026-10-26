// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#include "ufo.h"

// Keep the entire flight, including the hover, inside the shortest city run.
#define UFO_HOVER_FRAMES 40  // two seconds at the scene's 50ms frame interval

void ufo_start(Ufo *ufo, bool appear) {
  *ufo = (Ufo) {.x = -UFO_W * 16, .active = appear};
}

bool ufo_advance(Ufo *ufo) {
  if (!ufo->active) return false;
  ufo->frame++;
  if (ufo->hover_left) {
    ufo->hover_left--;
  } else {
    ufo->x += SCALE_X(16);
    const int32_t center = (PBL_DISPLAY_WIDTH - UFO_W) * 8;
    if (!ufo->hovered && ufo->x >= center) {
      ufo->x = center;
      ufo->hovered = true;
      ufo->hover_left = UFO_HOVER_FRAMES;
    }
    if (ufo->x >= PBL_DISPLAY_WIDTH * 16) ufo->active = false;
  }
  return true; // Bobbing and rim lights keep moving during the hover.
}

static void ufo_panel(GContext *ctx, int x, int y, int dx, int dy,
                      int w, int h, GColor color) {
  graphics_context_set_fill_color(ctx, color);
  graphics_fill_rect(ctx, GRect(x + SCALE_X(dx), y + SCALE_Y(dy),
                              SCALE_X(dx + w) - SCALE_X(dx),
                              SCALE_Y(dy + h) - SCALE_Y(dy)),
                     0, GCornerNone);
}

void ufo_draw(const Ufo *ufo, GContext *ctx, int dy) {
  if (!ufo->active) return;
  static const int8_t bob[] = {0, 1, 2, 1, 0, -1, -2, -1};
  const int pose = (ufo->frame / 5) % ARRAY_LENGTH(bob);
  const int x = ufo->x >= 0 ? ufo->x / 16 : -((-ufo->x + 15) / 16);
  const int y = SCALE_Y(28 + bob[pose]) + dy;
  const GColor outline = GColorFromRGB(0, 0, 85);
  const GColor blue = GColorFromRGB(0, 85, 170);
  const GColor silver = GColorFromRGB(170, 170, 255);
  const GColor cyan = GColorFromRGB(85, 255, 255);

  // Stepped curves keep the saucer crisp on the smallest display.
  ufo_panel(ctx, x, y, 21, 0, 14, 2, outline);
  ufo_panel(ctx, x, y, 17, 2, 22, 3, outline);
  ufo_panel(ctx, x, y, 14, 5, 28, 8, outline);
  ufo_panel(ctx, x, y, 21, 2, 14, 3, cyan);
  ufo_panel(ctx, x, y, 18, 5, 20, 7, blue);
  ufo_panel(ctx, x, y, 18, 5, 5, 5, cyan);
  ufo_panel(ctx, x, y, 10, 11, 36, 3, outline);
  ufo_panel(ctx, x, y, 4, 14, 48, 3, outline);
  ufo_panel(ctx, x, y, 0, 17, 56, 4, outline);
  ufo_panel(ctx, x, y, 5, 21, 46, 3, outline);
  ufo_panel(ctx, x, y, 14, 24, 28, 2, outline);
  ufo_panel(ctx, x, y, 11, 13, 34, 3, silver);
  ufo_panel(ctx, x, y, 5, 16, 46, 2, silver);
  ufo_panel(ctx, x, y, 2, 18, 52, 2, silver);
  ufo_panel(ctx, x, y, 7, 21, 42, 2, blue);
  for (int light = 0; light < 3; light++) {
    const bool lit = ((ufo->frame / 6) % 3) == (unsigned)light;
    ufo_panel(ctx, x, y, 11 + light * 15, 20, 4, 3,
              lit ? cyan : blue);
  }
}
