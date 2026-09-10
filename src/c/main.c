#include <pebble.h>

#include "city_layer.h"

#if !defined(PBL_PLATFORM_EMERY)
#error "Streaming Village targets the Pebble Time 2 (emery) only."
#endif

// ---------------------------------------------------------------------------
// Scene layout.  These values mirror the ones in tools/gen_art.py -- change
// them there and here together, or the layers will stop lining up.
// ---------------------------------------------------------------------------
#define SKY_H 88                 // static dithered sunset, 200x88, opaque

#define BG_Y 48                  // mountain ridge: 200x40, alpha
#define BG_H 40
#define BG_TILES 6

#define FG_Y 28                  // near buildings and street: 200x200, alpha
#define FG_H 200
#define FG_TILES 8

#define BB_Y 134                 // billboard: 120x122, repeating every 320px.
                                 // The board sits just over the top of the road, on a pole
                                 // that runs off the bottom of the display.
#define BB_H 122
#define BB_TILE_W 320
#define BB_TILES 1
#define BB_FRAME_X 100           // billboard frame, relative to its tile
#define BB_FRAME_W 120

// The blank interior of the billboard panel, relative to its tile.
#define BB_PANEL_X 108
#define BB_PANEL_Y 12
#define BB_PANEL_W 104
#define BB_PANEL_H 44

// A 320px tile is the display width plus the billboard width, so the instant
// the board clears the left edge its repeat is exactly at the right edge.  We
// stall there to hold the empty skyline for a beat.
#define BB_CLEAR_AT (BB_FRAME_X + BB_FRAME_W)
#define BB_PAUSE_MS 2000

// Scroll offset that leaves the billboard centred on the display.  The
// animation starts and comes to rest here, so a run is a whole number of
// billboard passes.
#define BB_REST_PX (BB_FRAME_X - (PBL_DISPLAY_WIDTH - BB_FRAME_W) / 2)

// How many times the billboard crosses the display per run.  A pass is 320px
// at 1.5px per frame plus the two-second stall, so two of them is a little
// over 25 seconds.
#define BB_PASSES 2

// Parallax speeds in subpixels per frame.  At FRAME_MS these work out to
// roughly 3.75, 15 and 30 pixels per second: the billboards sweep past eight
// times faster than the horizon.
#define FRAME_MS 50
#define BG_SPEED 3
#define FG_SPEED 12
#define BB_SPEED 24

// The scene animates in bursts rather than continuously: it runs for BB_PASSES
// billboard passes after the watchface is activated or tapped, then holds
// still with the billboard centred.

static Window *s_window;
static Layer *s_scene_layer;
static AppTimer *s_timer;
static bool s_in_focus;
static int s_obstruction_dy;

static GBitmap *s_sky;

static uint8_t s_passes_left;   // billboard passes left in this run

static CityLayer s_background;
static CityLayer s_foreground;
static CityLayer s_billboard;

static char s_time_text[8] = "--:--";

static const uint32_t s_bg_ids[BG_TILES] = {
  RESOURCE_ID_IMG_BG_0, RESOURCE_ID_IMG_BG_1, RESOURCE_ID_IMG_BG_2,
  RESOURCE_ID_IMG_BG_3, RESOURCE_ID_IMG_BG_4, RESOURCE_ID_IMG_BG_5,
};

static const uint32_t s_fg_ids[FG_TILES] = {
  RESOURCE_ID_IMG_FG_0, RESOURCE_ID_IMG_FG_1, RESOURCE_ID_IMG_FG_2,
  RESOURCE_ID_IMG_FG_3, RESOURCE_ID_IMG_FG_4, RESOURCE_ID_IMG_FG_5,
  RESOURCE_ID_IMG_FG_6, RESOURCE_ID_IMG_FG_7,
};

static const uint32_t s_bb_ids[BB_TILES] = {
  RESOURCE_ID_IMG_BB_0,
};

// ---------------------------------------------------------------------------

static void update_time_text(void) {
  const time_t now = time(NULL);
  struct tm *tick = localtime(&now);
  strftime(s_time_text, sizeof(s_time_text),
           clock_is_24h_style() ? "%H:%M" : "%I:%M", tick);
}

// Puts the time inside the panel of each billboard the scroll position has
// brought on screen.  Both drawn tiles get the text; the graphics context
// clips whichever panel is off the edge, and during the stall both are.
static void draw_billboard_time(GContext *ctx, int tile_origin, int dy) {
  GFont font = fonts_get_system_font(FONT_KEY_LECO_32_BOLD_NUMBERS);

  graphics_context_set_text_color(ctx, GColorWhite);
  for (int i = 0; i < 2; i++) {
    const int panel_x = tile_origin + i * BB_TILE_W + BB_PANEL_X;
    if (panel_x + BB_PANEL_W <= 0 || panel_x >= PBL_DISPLAY_WIDTH) {
      continue;
    }
    graphics_draw_text(ctx, s_time_text, font,
                       GRect(panel_x, BB_Y + BB_PANEL_Y + dy, BB_PANEL_W,
                             BB_PANEL_H),
                       GTextOverflowModeTrailingEllipsis,
                       GTextAlignmentCenter, NULL);
  }
}

static void scene_update_proc(Layer *layer, GContext *ctx) {
  const GRect bounds = layer_get_bounds(layer);

  // A notification shrinks the window from the bottom.  The interesting end of
  // the scene is down there -- the street, and the feet of the billboard -- so
  // slide everything up by however much is covered and let the sunset run off
  // the top instead.
  const GRect visible = layer_get_unobstructed_bounds(layer);
  const int dy = -(bounds.size.h - visible.size.h);

  // The land below the ridge line.  This has to be the colour the background
  // tiles end on (HORIZON in tools/gen_art.py) or the seam at y=SKY_H shows.
  // The foreground covers most of it, but it fills the gaps between buildings.
  graphics_context_set_fill_color(ctx, GColorFromRGB(85, 0, 85));
  graphics_fill_rect(ctx, GRect(0, SKY_H + dy, bounds.size.w,
                                bounds.size.h - SKY_H - dy), 0, GCornerNone);

  graphics_context_set_compositing_mode(ctx, GCompOpSet);
  if (s_sky) {
    graphics_draw_bitmap_in_rect(ctx, s_sky,
                                 GRect(0, dy, bounds.size.w, SKY_H));
  }
  city_layer_draw(&s_background, ctx, dy);
  city_layer_draw(&s_foreground, ctx, dy);
  const int billboard_origin = city_layer_draw(&s_billboard, ctx, dy);
  graphics_context_set_compositing_mode(ctx, GCompOpAssign);

  draw_billboard_time(ctx, billboard_origin, dy);
}

static void frame_timer(void *context) {
  s_timer = NULL;

  const int32_t bg_px = s_background.offset >> SUBPIX_SHIFT;
  const int32_t fg_px = s_foreground.offset >> SUBPIX_SHIFT;
  const int32_t bb_px = s_billboard.offset >> SUBPIX_SHIFT;

  city_layer_advance(&s_background);
  city_layer_advance(&s_foreground);
  city_layer_advance(&s_billboard);

  // A pass ends when the next step would carry the billboard back to, or past,
  // the centred rest position.  Land exactly on it -- which also keeps every
  // pass the same length -- and stop once the last one is done.
  if (city_layer_distance_to(&s_billboard, SUBPIX(BB_REST_PX)) <= BB_SPEED) {
    s_billboard.offset = SUBPIX(BB_REST_PX);
    if (--s_passes_left == 0) {
      layer_mark_dirty(s_scene_layer);
      return;                    // no new timer: the scene holds still
    }
  }

  // Fractional movement is invisible until it crosses a pixel boundary.
  // Keep advancing every frame, including during the billboard's pause.
  if (bg_px != (s_background.offset >> SUBPIX_SHIFT) ||
      fg_px != (s_foreground.offset >> SUBPIX_SHIFT) ||
      bb_px != (s_billboard.offset >> SUBPIX_SHIFT)) {
    layer_mark_dirty(s_scene_layer);
  }
  s_timer = app_timer_register(FRAME_MS, frame_timer, NULL);
}

// Starts a run, or resets the count on one already going.  Activation fires
// both .appear and did_focus, so this has to be idempotent: it sets the count
// rather than adding to it, and a run in progress keeps its existing timer.
static void start_animation(void) {
  if (!s_in_focus) {
    return;
  }
  s_passes_left = BB_PASSES;
  if (!s_timer) {
    s_timer = app_timer_register(FRAME_MS, frame_timer, NULL);
  }
}

static void tap_handler(AccelAxisType axis, int32_t direction) {
  start_animation();
}

// Losing focus means a notification or the timeline quick view is on top.
// The scene is covered, or nearly so, so there is no point burning frames on
// it: drop the run and let the next did_focus start a fresh one.
static void focus_handler(bool in_focus) {
  s_in_focus = in_focus;
  if (in_focus) {
    start_animation();
  } else if (s_timer) {
    app_timer_cancel(s_timer);
    s_timer = NULL;
    s_passes_left = 0;
    // Stopping mid-pass would strand the billboard wherever it happened to
    // be, with the clock half off the edge -- which is the one thing the
    // quick view needs to be able to read.  Come to rest the same way the
    // end of a run does.
    s_billboard.offset = SUBPIX(BB_REST_PX);
    s_billboard.pause_left = 0;
    layer_mark_dirty(s_scene_layer);
  }
}

// While the scene is animating it redraws anyway, but once it has come to rest
// this is what repositions it as a notification slides in or out.
static void unobstructed_change_handler(AnimationProgress progress,
                                        void *context) {
  const GRect bounds = layer_get_bounds(s_scene_layer);
  const GRect visible = layer_get_unobstructed_bounds(s_scene_layer);
  const int dy = -(bounds.size.h - visible.size.h);
  if (dy != s_obstruction_dy) {
    s_obstruction_dy = dy;
    layer_mark_dirty(s_scene_layer);
  }
}

static void tick_handler(struct tm *tick_time, TimeUnits units_changed) {
  update_time_text();
  // Needed while the scene is at rest; harmless while it is animating.
  layer_mark_dirty(s_scene_layer);
}

static void window_load(Window *window) {
  const GRect bounds = layer_get_bounds(window_get_root_layer(window));

  s_sky = gbitmap_create_with_resource(RESOURCE_ID_IMG_SKY);

  city_layer_init(&s_background, s_bg_ids, BG_TILES, MIN_TILE_W, BG_H, BG_Y,
                  BG_SPEED);
  city_layer_init(&s_foreground, s_fg_ids, FG_TILES, MIN_TILE_W, FG_H, FG_Y,
                  FG_SPEED);
  city_layer_init(&s_billboard, s_bb_ids, BB_TILES, BB_TILE_W, BB_H, BB_Y,
                  BB_SPEED);
  s_billboard.image_x = BB_FRAME_X;
  city_layer_set_pause(&s_billboard, BB_CLEAR_AT, BB_PAUSE_MS, FRAME_MS);

  s_billboard.offset = SUBPIX(BB_REST_PX);

  s_scene_layer = layer_create(bounds);
  layer_set_update_proc(s_scene_layer, scene_update_proc);
  layer_add_child(window_get_root_layer(window), s_scene_layer);
  const GRect visible = layer_get_unobstructed_bounds(s_scene_layer);
  s_obstruction_dy = -(bounds.size.h - visible.size.h);
}

static void window_appear(Window *window) {
  s_in_focus = true;
  start_animation();
}

static void window_unload(Window *window) {
  layer_destroy(s_scene_layer);
  s_scene_layer = NULL;

  if (s_sky) {
    gbitmap_destroy(s_sky);
    s_sky = NULL;
  }

  city_layer_deinit(&s_background);
  city_layer_deinit(&s_foreground);
  city_layer_deinit(&s_billboard);
}

static void init(void) {
  update_time_text();

  s_window = window_create();
  window_set_background_color(s_window, GColorBlack);
  window_set_window_handlers(s_window, (WindowHandlers) {
    .load = window_load,
    .appear = window_appear,
    .unload = window_unload,
  });
  window_stack_push(s_window, false);

  tick_timer_service_subscribe(MINUTE_UNIT, tick_handler);
  accel_tap_service_subscribe(tap_handler);
  app_focus_service_subscribe_handlers((AppFocusHandlers) {
    .did_focus = focus_handler,
  });
  unobstructed_area_service_subscribe((UnobstructedAreaHandlers) {
    .change = unobstructed_change_handler,
  }, NULL);

  APP_LOG(APP_LOG_LEVEL_INFO, "streaming village: %u bytes heap free",
          (unsigned)heap_bytes_free());
}

static void deinit(void) {
  if (s_timer) {
    app_timer_cancel(s_timer);
    s_timer = NULL;
  }
  unobstructed_area_service_unsubscribe();
  app_focus_service_unsubscribe();
  accel_tap_service_unsubscribe();
  tick_timer_service_unsubscribe();
  window_destroy(s_window);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
  return 0;
}
