# Streaming Village — a Pebble watchface

A parallax cityscape at sunset. Three layers scroll right to left at different
speeds, and the time rides past on a billboard.

![billboard](screenshots/emery-billboard.png)
![skyline](screenshots/emery-skyline.png)
![the same scene on a Pebble Time](screenshots/basalt-billboard.png)
![skyline on a Pebble Time](screenshots/basalt-skyline.png)

The first two are a Pebble Time 2; the last two are the same scene on a Pebble
Time.

![billboard on a Pebble Round 2](screenshots/gabbro-billboard.png)
![skyline on a Pebble Round 2](screenshots/gabbro-skyline.png)
![billboard on a Pebble Time Round](screenshots/chalk-billboard.png)
![skyline on a Pebble Time Round](screenshots/chalk-skyline.png)

And the two round watches — a Pebble Round 2 and a Pebble Time Round — where
the display crops the corners off every band.

Built for four platforms, all 64-colour displays, so they share a palette and
differ only in scale:

| platform | watch | display |
|---|---|---|
| emery | Pebble Time 2 | 200x228 |
| basalt | Pebble Time / Time Steel | 144x168 |
| chalk | Pebble Time Round | 180x180, round |
| gabbro | Pebble Round 2 | 260x260, round |

`main.c` has a `#error` guard so it can't be built for a platform it has no
layout for.

## The layers

| layer | tiles | speed | contents |
|---|---|---|---|
| sky | 1 | static | the dithered sunset gradient, opaque |
| background | 6 | ~3.75 px/s | mountain ridge with a rim-lit crest |
| foreground | 8, or 6 on gabbro | ~15 px/s | near towers with lit windows, street lamps, road |
| billboard | 1 | ~30 px/s | the billboard that carries the time |

And where each one sits:

| layer | emery | basalt | chalk | gabbro |
|---|---|---|---|---|
| sky | 200x88 at y=0 | 144x64 at y=0 | 180x69 at y=0 | 260x100 at y=0 |
| background | 200x40 at y=48 | 144x29 at y=35 | 180x31 at y=38 | 260x45 at y=55 |
| foreground | 200x200 at y=28 | 144x147 at y=21 | 180x157 at y=23 | 260x228 at y=32 |
| billboard | 120x122 at y=134 | 86x89 at y=98 | 108x96 at y=105 | 156x139 at y=152 |
| billboard repeat | 320px | 230px | 288px | 416px |
| foreground loop | 1600px | 1152px | 1440px | 1560px |

Every platform scrolls at the same physical speed; what changes is the
panorama width. gabbro is the one platform that does not use eight foreground
tiles — see [Memory](#memory). See also
[Four sizes, one layout](#four-sizes-one-layout).

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
seconds on emery, a little under 20 on basalt, a little over 23 on chalk and
a little under 32 on gabbro, but nothing depends on those numbers.

`start_animation` is idempotent, and has to be: activation fires both
`.appear` and `did_focus`, about a second apart. It sets the pass count rather
than adding to it, and a run already in progress keeps its existing timer, so
a tap or a second activation event resets the count instead of extending the
run.

Taps while unfocused cannot restart the animation. Each timer step still
advances all three scroll positions, but requests a redraw only if an integer
pixel position changes (or the run ends). An uninterrupted run takes 506 steps
and requests 486 animation redraws on emery, 386 and 366 on basalt, 462 and
442 on chalk, 634 and 614 on gabbro; in every case the remaining 20 steps
change only fractional
positions during the billboard pauses. `tests/power_savings.c` pins those
counts.

### The billboard gap

The billboard tile is one display width plus one billboard wide — 320 = 200 +
120 on emery, 230 = 144 + 86 on basalt, 288 = 180 + 108 on chalk,
416 = 260 + 156 on gabbro. That makes the board clear the left
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

                emery       basalt       chalk      gabbro
    sky         1 x  8,800  1 x  4,608  1 x  6,210  1 x 13,000  (4-bit, 9 colours)
    background  2 x  2,000  2 x  1,044  2 x  1,395  2 x  2,925  (2-bit, 3 colours)
    foreground  2 x 20,000  2 x 10,584  2 x 14,130  2 x 29,640  (4-bit, 9 colours)
    billboard   1 x  7,320  1 x  3,827  1 x  5,184  1 x 10,842  (4-bit, 6 colours)
                  --------    --------    --------    --------
                    60,120      31,691      42,444      88,972

                of 128KB     of 64KB     of 64KB     of 128KB

Chalk is the tightest: it has basalt's 64KB heap but a display half again as
large in area, which leaves about 13KB clear once the tiles are resident.
Basalt has the most room of the four — the firmware reports a 32,384-byte peak
against a 62,400-byte heap, the difference from the table being the `GBitmap`
structs themselves. Halving the display width is close to halving
the bitmap cost, which is why the artwork is regenerated per platform rather
than reused — two 200x200 foreground tiles alone would be 40KB of basalt's
64KB, and a 200px tile on gabbro's 260px display would let the viewport
straddle three logical tiles, which the two-slot cache cannot serve.

Every layer's artwork stays at or under 16 unique colours, which is what lets
the resources be declared `SmallestPalette` — the SDK then picks the narrowest
bit depth each one actually needs, which is how the mountains come out at 2
bits. The build fails loudly if a layer ever exceeds 16, and
`tools/gen_art.py` prints each layer's colour count.

Resources are stored as `pbi` rather than `png`. PNG resources would be much
smaller on flash — the dithered sky especially — but decoding one needs a
transient buffer on top of everything already resident, and the tiles are
loaded mid-animation. Uncompressed, the packs come to 192,751 bytes on emery,
104,002 on basalt, 137,435 on chalk and 223,807 on gabbro, each against a
256KB per-platform limit.

That limit is what sets gabbro's foreground panorama at six tiles rather than
eight. A 260x228 tile costs 29,640 bytes, so eight of them would be 237KB of
the 256KB budget on their own and the pack would come to roughly 283KB —
buildable and sideloadable, since the hard limit is 1024KB, but over the
ceiling the appstore enforces. Six tiles is a 1560px loop, about 104 seconds
at 15 px/s, and nothing on the watch notices: `city_layer` reads its tile
count from the array it is handed. `package.json` keeps `IMG_FG_6` and
`IMG_FG_7` off gabbro with a per-resource `targetPlatforms`, so those two
bitmaps are not in its pack at all, and `main.c` sizes `s_fg_ids` to match.
`tests/test_billboard_art.py` asserts every platform's pack stays inside the
budget.

## Four sizes, one layout

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

Only three values genuinely differ per platform: the billboard's panel margin,
the clock face, and — on gabbro alone — the foreground tile count. The system
fonts come in fixed sizes, so the digits step to the nearest one that clears
the panel: `FONT_KEY_LECO_32_BOLD_NUMBERS` will not fit basalt's 32px panel or
chalk's 34px one whatever its width, so both use
`FONT_KEY_LECO_26_BOLD_NUMBERS_AM_PM`, and gabbro's 49px panel goes the other
way to `FONT_KEY_LECO_36_BOLD_NUMBERS`.

### The round ones

chalk and gabbro are round, and nothing in the code accounts for that. There
are no `PBL_ROUND` branches: the bands stay full width and the display simply
crops the corners off them. That is the right answer here rather than a
shortcut — the scene is horizontal by construction, so what the circle takes
is sky at the top corners, the far ends of the ridge, and kerb at the bottom
corners, none of which carry information. The one thing that has to stay
inside the circle is the clock panel, and it clears the inscribed circle at
every corner with room to spare on both: x 43..137 / y 114..148 on chalk,
x 62..198 / y 165..214 on gabbro.

### Per-platform resources

The four artwork sets share one set of resource names. `package.json` declares
the bare `images/fg_0.png`, and the SDK's `find_most_specific_filename`
resolves it to `fg_0~emery.png`, `fg_0~basalt.png`, `fg_0~chalk.png` or
`fg_0~gabbro.png` from the platform's tags — so there is one media entry per
image, one `RESOURCE_ID_IMG_FG_0`, and one id array in `main.c`.
`menu_icon.png` is identical on all four and stays untagged.

## Artwork

There are no hand-drawn assets. `tools/gen_art.py` generates the sky and every
scrolling tile procedurally — 15 per platform, 13 on gabbro — for all four
platforms in one pass (pure Python — it writes the PNGs itself, so no Pillow
needed):

    python3 tools/gen_art.py

It draws each layer onto a horizontally wrapping canvas, so shapes may straddle
the seam and the panoramas loop cleanly. All colours are on Pebble's 64-colour
grid.

Geometry lives in a `Layout` per platform, scaled from the emery reference the
same way `main.c` scales its `#define`s. Decorative detail is *not* scaled and
is listed per platform in `EMERY_DECO` / `BASALT_DECO` / `CHALK_DECO` /
`GABBRO_DECO`: at 0.72x a window grid turns to mush and a rim light
disappears, and at 1.3x it looks sparse, so window pitch, lamp spacing, dash
length and the like are chosen rather than computed. Because the scaling is
the identity at 200x228, regenerating has to leave the emery PNGs
byte-identical — that is the regression check for any change in this file.

## Store animations

`tools/capture_loop.py` records the scene in motion, one animated GIF per
platform, for the storefront listings:

    tools/capture_loop.py                 # every target platform
    tools/capture_loop.py basalt chalk    # just these

GIF is the default because it is the only format the stores actually animate.
They reject WebP outright, and they accept an APNG upload but serve back only
its first frame. `--format apng` and `--format webp` still write those — both
are smaller and exactly lossless, so they are worth keeping as masters — and
`--convert` re-encodes whatever is already in `screenshots/` into another format
without going near the emulator:

    tools/capture_loop.py --format apng   # lossless masters
    tools/capture_loop.py --convert       # masters -> GIF for the store

The script installs the app in the emulator, waits for the activation run to
come to rest, taps the watch to start a fresh one, and pulls frames off the
QEMU monitor with `screendump`. `pebble screenshot --gif-all-platforms` is the
obvious alternative and is the wrong tool here: it records a fixed seven-second
clip straddling a minute boundary, and this scene only animates in bursts, so
by the time that capture starts the run has long since stopped.

### One pass, and finding where it ends

The clip is one billboard pass. A run is a whole number of passes and both
starts and ends at the centred offset, so one pass is the shortest segment that
begins and ends with the billboard — and so the clock — in the same place. It
is not a perfect loop, and nothing short enough to be one exists: the three
layers have incommensurate periods, 193 frames against 1536 and 4608 on basalt,
so the whole scene only returns to its starting state after minutes. A pass
puts the cut where it shows least, with the billboard, the clock and the road
identical across it and only the skyline behind them stepping along.

The seam is measured rather than assumed, by tracking the clock panel — the
only near-white thing in its band — and ending the pass where it returns to
where it started. Two things make that harder than it sounds, and both produced
wrong clips before they were handled. Comparing whole frames does not work at
all: the layers that cannot line up dominate the difference, enough to pick a
frame most of a pass away. And the search has to be confined to the single
crossing between one stall and the next. Before the stall the board has not
gone anywhere yet; and stray near-white pixels from the lit windows jitter the
measured centre by a fraction of a pixel, so walking outward until the distance
grows stops on the jitter rather than at the seam. Within the window the best
match is unambiguous, and every platform lands within a pixel. A seam further
off than that, or a pass more than a quarter away from the length the constants
imply, is an error rather than a bad file.

### Timing the emulator will not give you

Nothing about the emulator's timing can be taken on faith. Installing the app
activates it, which starts a run of its own, and that has to finish before the
tap or the tap merely extends it — so the script watches the billboard until it
stops instead of sleeping on the nominal figure. Sleeping was not paranoid
enough: because a run ends a fixed number of billboard crossings after the tap
rather than a fixed time, an early tap can leave the scene coming to rest
*inside* the capture, and then every resting frame matches the first one and the
seam lands anywhere. Nor does the emulator keep app timers to `FRAME_MS`: a
basalt pass takes 8.9s of wall clock against the 9.65s the constants specify,
and under load gabbro stretched the other way, 19.0s against 15.85s. So the
frames are played back over the nominal duration rather than the recorded one,
which is what makes the animation run at the speed a watch runs it.

Getting that onto a GIF takes one more step, because a GIF holds no frame rate:
it holds a delay per frame, in whole hundredths of a second. None of these
passes runs at a rate that divides into that — basalt's 18.4 fps would round to
5cs and play 8% fast, losing exactly the pacing above. Rounding each frame's
*cumulative* position instead spreads the error, so frames come out 5cs or 6cs
and the total is exact to the centisecond. ffmpeg can only be told a constant
rate, and feeding it per-frame durations through the concat demuxer comes back
quantised into a 4cs/8cs stutter, so the delays are written into the encoded
file afterwards — two bytes in each frame's control block. It is worth keeping
ffmpeg for the encode: it rewrites pixels that did not change as the
transparent index, which this scene compresses to about half of what writing
whole frames does.

### Colour and the unlit panel

Nothing that can be injected lights the backlight on a watchface, so the panel
is recorded unlit — a flat 67% linear scale — and scaled back up per frame.
That reconstruction is good to a single level but not exact, because the
emulator floors some channels on the way down: the palette lands on 84 and 170
where the display's 64-colour grid has 85 and 170.

The GIFs are visibly lossless. basalt, emery and gabbro come back pixel-for-
pixel identical to the APNG masters, because the art uses fifteen colours and a
GIF holds 256. chalk is the one exception, and only at the rim: its emulator
antialiases the edge of the round display, which pushes the count to 259 and
over what is left after reserving an entry for transparency, so 0.4% of its
pixels shift by at most 6 of 255. The round displays keep their transparent
corners, which is also why their frames carry a dispose-to-background flag
rather than the retain-previous one the rectangular platforms use.

At 230 KiB to 2.2 MiB the files are large but within what the stores take;
`--frame-step N` roughly halves the size per doubling if one of them ever
refuses, and shortens nothing.

## Build

    pebble build                         # builds all four platforms
    pebble install --emulator emery      # emulator
    pebble install --emulator basalt
    pebble install --emulator chalk
    pebble install --emulator gabbro
    pebble install --cloudpebble         # a real watch, via the phone

gabbro needs a recent SDK: it first appears in 4.33.1.

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
procedural artwork, asserts the layout invariants `main.c` derives from, and
sizes each platform's resource pack against the 256KB appstore ceiling.
