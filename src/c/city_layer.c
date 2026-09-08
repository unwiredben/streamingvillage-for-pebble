#include "city_layer.h"

void city_layer_init(CityLayer *layer, const uint32_t *ids, uint8_t count,
                     int16_t tile_w, int16_t height, int16_t y, int16_t speed) {
  memset(layer, 0, sizeof(*layer));
  layer->ids = ids;
  layer->count = count;
  layer->tile_w = tile_w;
  layer->height = height;
  layer->y = y;
  layer->speed = speed;
  layer->slot_tile[0] = -1;
  layer->slot_tile[1] = -1;
}

void city_layer_deinit(CityLayer *layer) {
  for (int i = 0; i < 2; i++) {
    if (layer->slot[i]) {
      gbitmap_destroy(layer->slot[i]);
      layer->slot[i] = NULL;
    }
    layer->slot_tile[i] = -1;
  }
}

void city_layer_set_pause(CityLayer *layer, int16_t pause_at_px,
                          uint16_t pause_ms, uint16_t frame_ms) {
  layer->pause_at = SUBPIX(pause_at_px);
  layer->pause_frames = pause_ms / frame_ms;
}

int32_t city_layer_distance_to(const CityLayer *layer, int32_t offset) {
  const int32_t period = SUBPIX(layer->tile_w) * layer->count;
  int32_t distance = offset - layer->offset;
  if (distance < 0) {
    distance += period;
  }
  return distance;
}

void city_layer_advance(CityLayer *layer) {
  if (layer->pause_left > 0) {
    layer->pause_left--;
    return;
  }

  const int32_t tile_span = SUBPIX(layer->tile_w);
  const int32_t period = tile_span * layer->count;
  const int32_t was = layer->offset % tile_span;

  layer->offset += layer->speed;
  if (layer->offset >= period) {
    layer->offset -= period;
  }

  // Trigger only on the frame that steps over pause_at.  Resuming leaves the
  // offset sitting exactly on it, and `was < pause_at` keeps that from
  // re-arming the stall.
  if (layer->pause_frames > 0) {
    const int32_t now = layer->offset % tile_span;
    if (was < layer->pause_at && now >= layer->pause_at) {
      layer->offset -= now - layer->pause_at;
      layer->pause_left = layer->pause_frames;
    }
  }
}

// Points the two slots at the requested tiles, reusing whatever is already
// loaded.  Scrolling one tile forward reuses the old right-hand tile, so a
// boundary crossing costs a single resource load.
static void bind_tiles(CityLayer *layer, int left, int right) {
  if (left == right) {
    // A single-tile panorama repeats inside one viewport, so both halves of
    // the draw share one bitmap and slot 1 stays unused.
    for (int8_t s = 0; s < 2; s++) {
      if (layer->slot_tile[s] == left) {
        layer->bind[0] = layer->bind[1] = s;
        return;
      }
    }
    if (layer->slot[0]) {
      gbitmap_destroy(layer->slot[0]);
    }
    layer->slot[0] = gbitmap_create_with_resource(layer->ids[left]);
    layer->slot_tile[0] = layer->slot[0] ? left : -1;
    layer->bind[0] = layer->bind[1] = 0;
    return;
  }

  const int wanted[2] = { left, right };
  bool taken[2] = { false, false };

  for (int w = 0; w < 2; w++) {
    layer->bind[w] = -1;
    for (int s = 0; s < 2; s++) {
      if (!taken[s] && layer->slot_tile[s] == wanted[w]) {
        layer->bind[w] = s;
        taken[s] = true;
        break;
      }
    }
  }

  for (int w = 0; w < 2; w++) {
    if (layer->bind[w] >= 0) {
      continue;
    }
    const int s = taken[0] ? 1 : 0;
    taken[s] = true;
    layer->bind[w] = s;

    if (layer->slot[s]) {
      gbitmap_destroy(layer->slot[s]);
    }
    layer->slot[s] = gbitmap_create_with_resource(layer->ids[wanted[w]]);
    layer->slot_tile[s] = layer->slot[s] ? wanted[w] : -1;
  }
}

int city_layer_draw(CityLayer *layer, GContext *ctx, int dy) {
  const int px = (layer->offset >> SUBPIX_SHIFT) % (layer->count * layer->tile_w);
  const int left_tile = px / layer->tile_w;
  const int origin = -(px - left_tile * layer->tile_w);
  const int right_tile = (left_tile + 1) % layer->count;

  bind_tiles(layer, left_tile, right_tile);

  GBitmap *left = layer->slot[layer->bind[0]];
  GBitmap *right = layer->slot[layer->bind[1]];
  const int y = layer->y + dy;
  if (left) {
    graphics_draw_bitmap_in_rect(
        ctx, left, GRect(origin, y, layer->tile_w, layer->height));
  }
  if (right) {
    graphics_draw_bitmap_in_rect(
        ctx, right, GRect(origin + layer->tile_w, y, layer->tile_w,
                          layer->height));
  }
  return origin;
}
