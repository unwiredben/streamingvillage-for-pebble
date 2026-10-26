// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#pragma once

#include "city_gen.h"

#define ROBOT_W SCALE_X(56)

typedef struct {
  int32_t x;              // sixteenths of a screen pixel; may be negative
  uint16_t frame;
  bool active;
} Robot;

void robot_start(Robot *robot, bool appear);
bool robot_advance(Robot *robot);
void robot_draw(const Robot *robot, GContext *ctx, int dy);
