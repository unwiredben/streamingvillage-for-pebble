// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#include "robot.h"

void robot_start(Robot *robot, bool appear) {
  *robot = (Robot) {.x = -ROBOT_W * 16, .active = appear};
}

bool robot_advance(Robot *robot) {
  if (!robot->active) return false;
  robot->x += SCALE_X(16);
  robot->frame++;
  if (robot->x >= PBL_DISPLAY_WIDTH * 16) robot->active = false;
  return true; // Include the frame that erases the departing visitor.
}

// Rectangles share scaled edges so even the smallest display has no cracks.
static void panel(GContext *ctx, int x, int y, int dx, int dy, int w, int h,
                  GColor color) {
  graphics_context_set_fill_color(ctx, color);
  graphics_fill_rect(ctx, GRect(x + SCALE_X(dx), y + SCALE_Y(dy),
                              SCALE_X(dx + w) - SCALE_X(dx),
                              SCALE_Y(dy + h) - SCALE_Y(dy)),
                     0, GCornerNone);
}

void robot_draw(const Robot *robot, GContext *ctx, int dy) {
  if (!robot->active) return;
  static const int8_t swing[] = {0, 2, 4, 2, 0, -2, -4, -2};
  const unsigned pose = (robot->frame / 4) % ARRAY_LENGTH(swing);
  const int step = swing[pose];
  const int x = robot->x >= 0 ? robot->x / 16 : -((-robot->x + 15) / 16);
  const int y = SCALE_Y(48) + dy + SCALE_Y((pose % 4 == 2) ? 2 : 0);
  const GColor outline = GColorFromRGB(0, 0, 85);
  const GColor purple = GColorFromRGB(85, 0, 170);
  const GColor light = GColorFromRGB(170, 85, 255);
  const GColor blue = GColorFromRGB(0, 85, 170);
  const GColor cyan = GColorFromRGB(85, 255, 255);

  // Far arm and legs, then the chest: all of this is behind the city tiles.
  panel(ctx, x, y, 42 - step, 49, 10, 42, outline);
  panel(ctx, x, y, 44 - step, 51, 6, 34, blue);
  panel(ctx, x, y, 17 + step, 93, 10, 38, outline);
  panel(ctx, x, y, 19 + step, 95, 6, 32, blue);
  panel(ctx, x, y, 31 - step, 93, 10, 38, outline);
  panel(ctx, x, y, 33 - step, 95, 6, 32, purple);
  panel(ctx, x, y, 12 + step, 129, 15, 7, blue);
  panel(ctx, x, y, 26 - step, 129, 15, 7, purple);
  panel(ctx, x, y, 11, 46, 34, 51, outline);
  panel(ctx, x, y, 13, 48, 30, 46, purple);
  panel(ctx, x, y, 13, 48, 4, 38, light);
  panel(ctx, x, y, 21, 56, 18, 22, blue);
  panel(ctx, x, y, 25, 61, 10, 3, cyan);
  panel(ctx, x, y, 21, 86, 18, 5, outline);
  // Neck, square head, antenna and luminous face.
  panel(ctx, x, y, 23, 36, 12, 10, blue);
  panel(ctx, x, y, 27, 2, 3, 9, light);
  panel(ctx, x, y, 26, 0, 5, 4, cyan);
  panel(ctx, x, y, 10, 10, 36, 28, outline);
  panel(ctx, x, y, 12, 12, 32, 24, purple);
  panel(ctx, x, y, 12, 12, 4, 20, light);
  panel(ctx, x, y, 17, 18, 23, 11, outline);
  panel(ctx, x, y, 19, 20, 6, 5, cyan);
  panel(ctx, x, y, 31, 20, 6, 5, cyan);
  panel(ctx, x, y, 23, 32, 11, 2, blue);
  // Near shoulder and swinging hand.
  panel(ctx, x, y, 4 + step, 48, 11, 41, outline);
  panel(ctx, x, y, 6 + step, 50, 7, 32, purple);
  panel(ctx, x, y, 6 + step, 50, 3, 13, light);
  panel(ctx, x, y, 5 + step, 81, 9, 10, blue);
}
