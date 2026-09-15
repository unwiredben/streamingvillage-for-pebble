# Streaming Village — a Pebble watchface

A parallax cityscape at sunset. Three layers scroll right to left at different
speeds, and the time rides past on a billboard.

![billboard](screenshots/billboard.png)
![skyline](screenshots/skyline.png)
![the same scene on a Pebble Time](screenshots/basalt-billboard.png)

The first two are a Pebble Time 2; the third is the same scene on a Pebble
Time.

Built for the **Pebble Time 2** (emery, 200x228) and the **Pebble Time /
Time Steel** (basalt, 144x168) — both 64-colour displays, so the two share a
palette and differ only in scale. `main.c` has a `#error` guard so it can't be
built for a platform it has no layout for.

## The layers

| layer | emery | basalt | tiles | speed | contents |
|---|---|---|---|---|---|
| sky | 200x88 at y=0 | 144x64 at y=0 | 1 | static | the dithered sunset gradient, opaque |
| background | 200x40 at y=48 | 144x29 at y=35 | 6 | ~3.75 px/s | mountain ridge with a rim-lit crest |
| foreground | 200x200 at y=28 | 144x147 at y=21 | 8 | ~15 px/s | near towers with lit windows, street lamps, road |
| billboard | 120x122 at y=134, 320px repeat | 86x89 at y=98, 230px repeat | 1 | ~30 px/s | the billboard that carries the time |

Both platforms scroll at the same physical speed and use the same tile counts;
only the panorama width changes (the foreground loop is 1600px on emery and
1152px on basalt). See [Two sizes, one layout](#two-sizes-one-layout).

The background is a shallow band and the towers are tall, so the sunset reads
as a thin strip above the horizon rather than half the display. Most towers
top out below the mountain valleys so the ridge stays visible behind them,
and a few landmarks cut up through it.

Depth comes from value as much as parallax: the mountains and the land below
them are mid purple, and the near towers are navy or black against it. The
billboard sits just over the top of the road, in front of the street, on a
single centre pole that runs off the bottom of the display.

The background and foreground are authored as seamless panoramas and sliced
into tiles. Every logical tile is at least as wide as the display, so any
viewport overlaps at most two adjacent tiles. Images entirely outside
the viewport are skipped; partially visible images are clipped by the graphics
context. Only two bitmaps per layer are ever resident. Scrolling one tile forward
reuses the previous right-hand tile, so crossing a boundary costs a single
resource load. The billboard panorama is a single tile, so both halves of its
draw share the one bitmap. Its stored image omits the transparent margins on
each side: it is drawn at a half-display inset within the unchanged logical tile.

Scroll positions are kept in 1/16ths of a pixel so the slow layers can move at
fractional speeds without drifting.

### One colour, one definition

The mountain silhouette fills solid from its crest to the bottom edge of its
tile, and `scene_update_proc` fills the rest of the screen below with the same
colour, so the join at `y = SKY_H` is invisible. That colour is `HORIZON` in
`tools/gen_art.py` and the `GColorFromRGB(85, 0, 85)` fill in `main.c` — the
one pair of values in the project that must be changed together.

### The dithered sunset

The sunset is ordered-dithered so it fades rather than banding, which is why it
is a separate static bitmap instead of living in the scrolling background: a
dithered gradient that slid sideways would make the dither pattern crawl. Being
static also means it is blitted once per frame and never re-dithered at
runtime.

Each segment of the ramp mixes only its own two end colours, so the whole sky
stays inside a 16-entry palette. The stops are one 85-per-channel step apart —
navy, imperial purple, violet, purple, magenta, folly, melon, rajah, amber —
which is the smallest step the 64-colour display can make.

The threshold pattern is deliberately not a Bayer matrix. In a purely vertical
fade every pixel in a row shares the same blend fraction, and each row of a
Bayer matrix spans only part of the threshold range, so neighbouring rows land
at visibly different densities and the fade picks up horizontal streaks.
Instead each row walks the full 0..63 range in van der Corput (bit-reversed)
order — any prefix of which is spread evenly across the row — rotated by a
different random amount per row so the dots never line up into columns or
diagonals.

### When it animates

The scene does not scroll continuously. It runs for `BB_PASSES` billboard
passes — two — whenever the watchface is activated (pushed onto the stack, or
given focus back after a notification) and whenever the watch is tapped, then
holds still with the billboard centred.

A run is counted in passes rather than timed. The animation always rests at
the centred offset and always starts from it, so a pass is a well-defined unit:
`frame_timer` watches for the step that would carry the billboard back to that
offset, lands exactly on it — which also keeps every pass the same length —
and stops when the last one is done. Two passes work out at a little over 25
seconds on emery and a little under 20 on basalt, but nothing depends on those
numbers.

`start_animation` is idempotent, and has to be: activation fires both
`.appear` and `did_focus`, about a second apart. It sets the pass count rather
than adding to it, and a run already in progress keeps its existing timer, so
a tap or a second activation event resets the count instead of extending the
run.

Taps while unfocused cannot restart the animation. Each timer step still
advances all three scroll positions, but requests a redraw only if an integer
pixel position changes (or the run ends). An uninterrupted run takes 506 steps
and requests 486 animation redraws on emery, 386 and 366 on basalt; in both
cases the remaining 20 steps change only fractional positions during the
billboard pauses. `tests/power_savings.c` pins those counts.

### The billboard gap

The billboard tile is one display width plus one billboard wide — 320 = 200 +
120 on emery, 230 = 144 + 86 on basalt. That makes the board clear the left
edge at the exact moment its repeat reaches the right edge, leaving no natural
gap — so
`city_layer_set_pause` stalls the layer at that offset for two seconds. The
billboard is completely absent, and no time is drawn, for that beat.

### Notifications

A notification shrinks the window from the bottom. The interesting end of the
scene is down there — the street, and the base of the billboard — so
`scene_update_proc` reads `layer_get_unobstructed_bounds` on every draw and
slides the whole scene up by however much is covered, letting the sunset run
off the top instead.

![quick view](screenshots/quick-view.png)
![quick view on a Pebble Time](screenshots/basalt-quick-view.png)

Because the scene stops, sampling those bounds during the animation is not
enough on its own — an obstruction can arrive while the face is at rest. Two
subscriptions cover that: `unobstructed_area_service_subscribe` marks the
scene dirty when the notification's integer vertical displacement changes,
and the minute tick does the same so the time still updates on a still scene.

## Memory

Two tiles resident per scrolling layer, one each for the sky and the billboard,
each palettised at the narrowest bit depth its colour count allows. Rows are
byte-aligned, so a 4-bit tile costs `ceil(w/2)` bytes per row and a 2-bit one
`ceil(w/4)`:

    emery                                basalt
    sky         1 x  8,800 =  8,800      1 x  4,608 =  4,608   (4-bit, 9 colours)
    background  2 x  2,000 =  4,000      2 x  1,044 =  2,088   (2-bit, 3 colours)
    foreground  2 x 20,000 = 40,000      2 x 10,584 = 21,168   (4-bit, 9 colours)
    billboard   1 x  7,320 =  7,320      1 x  3,827 =  3,827   (4-bit, 6 colours)
                           --------                 --------
                             60,120                   31,691

    of emery's 128KB                     of basalt's 64KB

Basalt is the tighter of the two and still has room: the firmware reports a
32,384-byte peak against a 62,400-byte heap, the difference from the table
being the `GBitmap` structs themselves. Halving the display width is close to
halving the bitmap cost, which is why the artwork is regenerated at 144px
rather than reused — two 200x200 foreground tiles alone would be 40KB of
basalt's 64KB.

Every layer's artwork stays at or under 16 unique colours, which is what lets
the resources be declared `SmallestPalette` — the SDK then picks the narrowest
bit depth each one actually needs, which is how the mountains come out at 2
bits. The build fails loudly if a layer ever exceeds 16, and
`tools/gen_art.py` prints each layer's colour count.

Resources are stored as `pbi` rather than `png`. PNG resources would be much
smaller on flash — the dithered sky especially — but decoding one needs a
transient buffer on top of everything already resident, and the tiles are
loaded mid-animation. Uncompressed, the packs come to 192,751 bytes on emery
and 104,002 on basalt, each against a 256KB per-platform limit.

## Two sizes, one layout

Nothing in `src/c/city_layer.c` knows a display size: it culls against
`PBL_DISPLAY_WIDTH` and `MIN_TILE_W` is that same width. The scene geometry
lives entirely in `main.c`'s `#define` block, and rather than list it twice it
is *derived* from the emery reference by the same integer scaling
`tools/gen_art.py` applies to the artwork:

    #define SCALE_Y(v) ((v) * PBL_DISPLAY_HEIGHT / EMERY_H)
    #define SKY_H SCALE_Y(88)

Both scalings are the identity at 200x228, so the emery numbers fall out of
the macros unchanged, and the two files stay in step by construction instead
of by remembering to edit both. The relationships the layout rests on — the
ridge sitting on the sky's bottom edge, the street landing on the bottom of
the display, a billboard tile being one display plus one board — are asserted
in `tests/test_billboard_art.py`, so a drift between generator and watchface
fails a test rather than showing up as a seam on the watch.

Only two values genuinely differ per platform: the billboard's panel margin,
and the clock face. `FONT_KEY_LECO_32_BOLD_NUMBERS` will not clear basalt's
32px panel whatever its width, so basalt uses
`FONT_KEY_LECO_26_BOLD_NUMBERS_AM_PM`.

### Per-platform resources

The two artwork sets share one set of resource names. `package.json` declares
the bare `images/fg_0.png`, and the SDK's `find_most_specific_filename`
resolves it to `fg_0~emery.png` or `fg_0~basalt.png` from the platform's tags
— so there is one media entry per image, one `RESOURCE_ID_IMG_FG_0`, and one
id array in `main.c`. `menu_icon.png` is identical on both and stays untagged.

## Artwork

There are no hand-drawn assets. `tools/gen_art.py` generates the sky and all
15 scrolling tiles procedurally, for every platform, in one pass (pure Python
— it writes the PNGs itself, so no Pillow needed):

    python3 tools/gen_art.py

It draws each layer onto a horizontally wrapping canvas, so shapes may straddle
the seam and the panoramas loop cleanly. All colours are on Pebble's 64-colour
grid.

Geometry lives in a `Layout` per platform, scaled from the emery reference the
same way `main.c` scales its `#define`s. Decorative detail is *not* scaled and
is listed per platform in `EMERY_DECO` / `BASALT_DECO`: at 0.72x a window grid
turns to mush and a rim light disappears, so window pitch, lamp spacing, dash
length and the like are chosen rather than computed. Because the scaling is
the identity at 200x228, regenerating has to leave the emery PNGs
byte-identical — that is the regression check for any change in this file.

## Build

    pebble build                         # builds emery and basalt
    pebble install --emulator emery      # emulator
    pebble install --emulator basalt
    pebble install --cloudpebble         # a real watch, via the phone

After changing `targetPlatforms`, run `pebble clean` first: waf caches the
configured platform set and will otherwise keep building the old one.

## Regression checks

After a build has generated the resource headers, run the C handler and draw
geometry checks on the host (requires GCC and the Pebble SDK):

    PEBBLE_SDK_PEBBLE=/path/to/sdk-core/pebble bash tests/run_host_tests.sh
    python3 -B tests/test_billboard_art.py

`run_host_tests.sh` covers every platform by default; pass names to narrow it.

The host checks replace platform timers and graphics calls with recording
stubs. They cover focus loss and taps, animation completion and redraw counts,
minute updates, obstruction movement, and billboard placement across every
scroll position in a tile with several notification offsets. The artwork check
compares each platform's cropped resource with the original full-width
procedural artwork, and asserts the layout invariants `main.c` derives from.
