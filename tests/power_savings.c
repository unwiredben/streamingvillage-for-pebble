// Host regression checks using real watchface code and SDK declarations.
// Unused UI setup/render functions are discarded by the host linker.
#define main watchface_main
#include "../src/c/main.c"
#undef main
#include "../src/c/city_layer.c"
#undef fprintf

#define CHECK(condition) do { \
  if (!(condition)) { \
    fprintf(stderr, "line %d: %s\n", __LINE__, #condition); \
    exit(1); \
  } \
} while (0)

// Like CHECK, but reports the numbers: the frame counts below move whenever
// the geometry does, and the new value is what you need to see.
#define CHECK_EQ(actual, expected) do { \
  if ((actual) != (expected)) { \
    fprintf(stderr, "line %d: %s == %d, expected %d\n", __LINE__, #actual, \
            (int)(actual), (int)(expected)); \
    exit(1); \
  } \
} while (0)

// A run is BB_PASSES billboard passes of BB_TILE_W at BB_SPEED, plus a stall
// of BB_PAUSE_MS on each.  Redraws are fewer than frames because the slow
// layers move in fractions of a pixel, and because nothing is redrawn during
// the stall.
#if defined(PBL_PLATFORM_EMERY)
  #define EXPECT_FRAMES 506
  #define EXPECT_DIRTY 486
#elif defined(PBL_PLATFORM_BASALT)
  #define EXPECT_FRAMES 386
  #define EXPECT_DIRTY 366
#elif defined(PBL_PLATFORM_CHALK)
  #define EXPECT_FRAMES 462
  #define EXPECT_DIRTY 442
#elif defined(PBL_PLATFORM_GABBRO)
  #define EXPECT_FRAMES 634
  #define EXPECT_DIRTY 614
#else
  #error "No expected frame counts for this platform."
#endif

static int dirty_count;
static int timer_count;
static int visible_height = PBL_DISPLAY_HEIGHT;
static int bitmap_token;
static int bitmap_draws;
static GRect bitmap_rect;

GBitmap *gbitmap_create_with_resource(uint32_t id) {
  CHECK(id == RESOURCE_ID_IMG_BB_0);
  return (GBitmap *)&bitmap_token;
}
void gbitmap_destroy(GBitmap *bitmap) { CHECK(bitmap == (GBitmap *)&bitmap_token); }
GRect gbitmap_get_bounds(const GBitmap *bitmap) {
  return GRect(0, 0, BB_FRAME_W, BB_H);
}
void graphics_draw_bitmap_in_rect(GContext *ctx, const GBitmap *bitmap, GRect rect) {
  bitmap_draws++;
  bitmap_rect = rect;
}

AppTimer *app_timer_register(uint32_t ms, AppTimerCallback callback, void *data) {
  CHECK(ms == 50);
  CHECK(callback == frame_timer);
  timer_count++;
  return (AppTimer *)&timer_count;
}

void app_timer_cancel(AppTimer *timer) { CHECK(timer != NULL); }
void layer_mark_dirty(Layer *layer) { dirty_count++; }
GRect layer_get_bounds(const Layer *layer) {
  return GRect(0, 0, PBL_DISPLAY_WIDTH, PBL_DISPLAY_HEIGHT);
}
GRect layer_get_unobstructed_bounds(const Layer *layer) {
  return GRect(0, 0, PBL_DISPLAY_WIDTH, visible_height);
}
bool clock_is_24h_style(void) { return true; }
time_t time(time_t *result) { return 0; }
struct tm *localtime(const time_t *value) {
  static struct tm tick;
  return &tick;
}
size_t strftime(char *text, size_t size, const char *format, const struct tm *tick) {
  CHECK(size >= 6);
  memcpy(text, "12:34", 6);
  return 5;
}

int main(int argc, char **argv) {
  CHECK(argc == 2);
  city_layer_init(&s_background, s_bg_ids, BG_TILES, MIN_TILE_W, BG_H, BG_Y, BG_SPEED);
  city_layer_init(&s_foreground, s_fg_ids, FG_TILES, MIN_TILE_W, FG_H, FG_Y, FG_SPEED);
  city_layer_init(&s_billboard, s_bb_ids, BB_TILES, BB_TILE_W, BB_H, BB_Y, BB_SPEED);
  city_layer_set_pause(&s_billboard, BB_CLEAR_AT, BB_PAUSE_MS, FRAME_MS);
  s_billboard.offset = SUBPIX(BB_REST_PX);

  if (strcmp(argv[1], "focus") == 0) {
    window_appear(NULL);
    CHECK(s_timer != NULL);
    focus_handler(false);
    CHECK(s_timer == NULL);
    int before = timer_count;
    tap_handler(ACCEL_AXIS_X, 1);
    CHECK(timer_count == before);
    CHECK(s_timer == NULL);
    focus_handler(true);
    CHECK(s_timer != NULL);
    CHECK(s_passes_left == 2);
  } else if (strcmp(argv[1], "frames") == 0) {
    window_appear(NULL);
    int frames = 0;
    while (s_timer && frames < 2000) {
      frame_timer(NULL);
      frames++;
    }
    CHECK_EQ(frames, EXPECT_FRAMES);
    CHECK(s_billboard.offset == SUBPIX(BB_REST_PX));
    CHECK(s_passes_left == 0);
    CHECK_EQ(dirty_count, EXPECT_DIRTY);
    int before = dirty_count;
    tick_handler(NULL, MINUTE_UNIT);
    CHECK(dirty_count == before + 1);
  } else if (strcmp(argv[1], "obstruction") == 0) {
    // Repeated callbacks at the same integer displacement need only one draw.
    visible_height = PBL_DISPLAY_HEIGHT - 38;
    unobstructed_change_handler(0, NULL);
    CHECK(dirty_count == 1);
    unobstructed_change_handler(1, NULL);
    CHECK(dirty_count == 1);
    visible_height = PBL_DISPLAY_HEIGHT - 39;
    unobstructed_change_handler(2, NULL);
    CHECK(dirty_count == 2);
    visible_height = PBL_DISPLAY_HEIGHT;
    unobstructed_change_handler(3, NULL);
    CHECK(dirty_count == 3);
  } else if (strcmp(argv[1], "billboard") == 0) {
    s_billboard.image_x = BB_FRAME_X;
    const int shifts[] = {0, -38, -80};
    for (unsigned i = 0; i < ARRAY_LENGTH(shifts); i++) {
      for (int px = 0; px < BB_TILE_W; px++) {
        s_billboard.offset = SUBPIX(px);
        bitmap_draws = 0;
        CHECK(city_layer_draw(&s_billboard, NULL, shifts[i]) == -px);
        // At BB_CLEAR_AT the old board has just left and the next one is
        // exactly at the right edge, so neither is on screen.
        CHECK(bitmap_draws == (px == BB_CLEAR_AT ? 0 : 1));
        if (bitmap_draws) {
          CHECK(bitmap_rect.origin.x == (px < BB_CLEAR_AT
                                         ? BB_FRAME_X - px
                                         : BB_FRAME_X + BB_TILE_W - px));
          CHECK(bitmap_rect.origin.y == BB_Y + shifts[i]);
          CHECK(bitmap_rect.size.w == BB_FRAME_W);
          CHECK(bitmap_rect.size.h == BB_H);
        }
      }
    }
    city_layer_deinit(&s_billboard);
  } else {
    CHECK(false);
  }
  return 0;
}
