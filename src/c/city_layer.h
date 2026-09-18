// Copyright (c) 2026 Ben Combee
// SPDX-License-Identifier: MIT
#pragma once

#include <pebble.h>

// A layer's tiles are never narrower than the display, so the viewport always
// overlaps at most two adjacent logical tiles.  That lets a layer keep just
// two bitmaps resident no matter how long its panorama is.
#define MIN_TILE_W PBL_DISPLAY_WIDTH

// Scroll offsets are tracked in 1/16ths of a pixel so the slow layers can
// creep along at fractional speeds without drifting.
#define SUBPIX_SHIFT 4
#define SUBPIX(px) ((int32_t)(px) << SUBPIX_SHIFT)

// Fills a generated tile with the panorama starting at absolute x `x0`.
typedef void (*CityTileGen)(GBitmap *tile, int32_t x0);

typedef struct {
  const uint32_t *ids;   // one resource id per tile, left to right; NULL when
                         // the tiles are generated
  uint8_t count;         // number of tiles in the panorama
  int16_t tile_w;        // logical repeat width, >= MIN_TILE_W
  int16_t image_x;       // image inset within the logical tile (cropped margins)
  int16_t height;        // tile height in pixels
  int16_t y;             // where the layer sits on screen
  int16_t speed;         // scroll speed, in subpixels per frame

  // Optional stall: each time the layer scrolls past pause_at (a subpixel
  // offset within a tile) it snaps to that offset and holds for pause_frames
  // frames.  Set pause_frames to 0 to scroll without stopping.
  int32_t pause_at;
  uint16_t pause_frames;
  uint16_t pause_left;

  // A generated layer draws its tiles instead of loading them: the two slots
  // are created blank once and refilled in place, which is what lets the
  // panorama be longer than a resource pack could hold.
  CityTileGen generate;  // NULL when the tiles are stored bitmaps
  GColor *palette;       // palette the generated tiles are drawn against

  int32_t offset;        // scroll position, in subpixels
  GBitmap *slot[2];      // the only two tiles held in memory
  int8_t slot_tile[2];   // which tile each slot holds, -1 when empty
  int8_t bind[2];        // slot serving the left/right half of the viewport
} CityLayer;

void city_layer_init(CityLayer *layer, const uint32_t *ids, uint8_t count,
                     int16_t tile_w, int16_t height, int16_t y, int16_t speed);

// As above, but the tiles are generated on demand rather than loaded.  The
// palette has to outlive the layer; city_gen_palette() returns a static one.
void city_layer_init_generated(CityLayer *layer, CityTileGen generate,
                               GColor *palette, uint8_t count, int16_t tile_w,
                               int16_t height, int16_t y, int16_t speed);

void city_layer_deinit(CityLayer *layer);

// Sets the stall described above: the layer holds still for pause_ms every
// time it reaches pause_at_px pixels into a tile.
void city_layer_set_pause(CityLayer *layer, int16_t pause_at_px,
                          uint16_t pause_ms, uint16_t frame_ms);

// Subpixels the layer still has to scroll to land on `offset`.
int32_t city_layer_distance_to(const CityLayer *layer, int32_t offset);

// Advances the layer by one frame's worth of scrolling.
void city_layer_advance(CityLayer *layer);

// Draws visible images in the two tiles straddling the viewport, using each
// bitmap's actual size and image_x inset. `dy` shifts the layer vertically,
// which is how the scene slides up out from under an obstruction.  Returns the screen x of the left-hand tile's
// origin, which is what a caller needs to locate features drawn inside the
// tiles.
int city_layer_draw(CityLayer *layer, GContext *ctx, int dy);
