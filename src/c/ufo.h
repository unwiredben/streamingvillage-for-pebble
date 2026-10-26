// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#pragma once

#include "city_gen.h"

#define UFO_W SCALE_X(56)

typedef struct {
  int32_t x;              // sixteenths of a screen pixel
  uint16_t frame;
  uint8_t hover_left;
  bool hovered;
  bool active;
} Ufo;

void ufo_start(Ufo *ufo, bool appear);
bool ufo_advance(Ufo *ufo);
void ufo_draw(const Ufo *ufo, GContext *ctx, int dy);
