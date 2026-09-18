// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
// Renders the generated foreground on the host and writes it out one byte
// per pixel, so tests/test_city_gen.py can hold it up against the Python
// reference in tools/gen_art.py.  With no arguments it renders the whole
// panorama a tile at a time, which is exactly what the watchface does; with
// `x0 width` it renders one arbitrary span, which is how the span-
// independence checks are driven.
#include "../src/c/city_gen.c"

// pebble.h poisons the host functions a watchface has no business calling,
// so they are put back after it, the way tests/power_savings.c does.
#undef fwrite
#undef fprintf
#undef malloc
#undef free

#include <stdio.h>
#include <stdlib.h>

static void emit(int32_t x0, int width) {
  const uint16_t stride = (uint16_t)((width + 1) / 2);
  uint8_t *data = malloc((size_t)stride * FG_H);
  if (!data) {
    exit(2);
  }
  city_gen_foreground(data, stride, (int16_t)width, x0);

  uint8_t *row = malloc((size_t)width);
  if (!row) {
    exit(2);
  }
  for (int y = 0; y < FG_H; y++) {
    const uint8_t *p = data + (size_t)y * stride;
    for (int x = 0; x < width; x++) {
      // Two pixels to a byte, leftmost in the high nibble.
      row[x] = (x & 1) ? (p[x >> 1] & 0x0F) : (uint8_t)(p[x >> 1] >> 4);
    }
    fwrite(row, 1, (size_t)width, stdout);
  }
  free(row);
  free(data);
}

int main(int argc, char **argv) {
  if (argc == 3) {
    emit((int32_t)strtol(argv[1], NULL, 10), (int)strtol(argv[2], NULL, 10));
  } else if (argc == 1) {
    for (int t = 0; t < FG_TILES; t++) {
      emit((int32_t)t * PBL_DISPLAY_WIDTH, PBL_DISPLAY_WIDTH);
    }
  } else {
    fprintf(stderr, "usage: %s [x0 width]\n", argv[0]);
    return 2;
  }
  return 0;
}
