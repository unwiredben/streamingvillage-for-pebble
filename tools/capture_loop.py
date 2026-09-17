#!/usr/bin/env python3
# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Capture a looping animation of the scrolling scene, one per platform.

Writes an animated GIF per platform, which is what the storefronts animate: they
reject WebP outright, and accept an APNG upload but serve back only its first
frame.  Both remain available as `--format`, and are worth keeping as masters --
they are smaller and exactly lossless -- with `--convert` to re-encode them to
GIF without going near the emulator again.

`pebble screenshot --gif-all-platforms` records a fixed 7-second clip straddling
a minute boundary, which is the wrong window for this watchface: the scene only
animates in bursts, and by the time that capture starts the run has finished.
This script instead installs the app, waits for the activation run to come to
rest, taps the watch to start a fresh one, and pulls frames straight off the
QEMU monitor with `screendump`.

It keeps one billboard pass.  A run is a whole number of passes and both starts
and ends at the centred offset, so one pass is the shortest segment that begins
and ends with the billboard -- and so the clock, the only thing anyone reads --
in the same place.  It is not a perfect loop: the three parallax layers have
incommensurate periods (on basalt the billboard repeats every 193 frames, the
foreground every 1536 and the background every 4608), so nothing shorter than
minutes returns the whole scene to its starting state.  One pass puts the cut
where it shows least, with the billboard and the digits identical across it and
only the skyline behind them stepping along.

The seam is found by watching the billboard rather than by comparing whole
frames: the layers that cannot line up dominate any image difference, which is
enough to pick a frame most of a pass away from the right one.  The clock panel
is the only near-white thing in its band, so its horizontal centre is easy to
measure, and the pass ends where it comes back to where it started.

Run from the project directory:

    tools/capture_loop.py                 # every target platform
    tools/capture_loop.py basalt chalk    # just these
"""

import os
import sys

# pebble-tool lives in its own virtualenv (it needs Pillow and libpebble2, which
# the system interpreter has no reason to carry), so re-exec under its
# interpreter rather than asking anyone to hunt for the path.
try:
    import pebble_tool  # noqa: F401
except ImportError:
    import shutil

    launcher = shutil.which("pebble")
    if launcher is None:
        sys.exit("pebble-tool is not on PATH; cannot find an interpreter with pebble_tool.")
    with open(launcher) as f:
        shebang = f.readline().strip()
    if not shebang.startswith("#!"):
        sys.exit("Cannot determine pebble-tool's interpreter from {}.".format(launcher))
    interpreter = shebang[2:].strip()
    if os.path.realpath(interpreter) == os.path.realpath(sys.executable):
        sys.exit("pebble_tool is not importable under {}.".format(interpreter))
    os.execv(interpreter, [interpreter, os.path.abspath(__file__)] + sys.argv[1:])

import argparse
import shutil
import struct
import subprocess
import tempfile
import time

from PIL import Image

from libpebble2.communication.transports.qemu.protocol import QemuTap

from pebble_tool.commands.emucontrol import send_data_to_qemu
from pebble_tool.commands.install import ToolAppInstaller
from pebble_tool.commands.screenshot import ScreenshotCommand
from pebble_tool.exceptions import ToolError
from pebble_tool.sdk import get_sdk_persist_dir, sdk_manager, sdk_version
from pebble_tool.util import get_persist_dir
from pebble_tool.util.wsl import maybe_apply_wsl_hacks

# An animated PNG is still a .png -- anything that sniffs the extension has to
# see one -- so the loops sit alongside the stills under a -loop name.
FILE_EXTENSION = {"apng": "png", "webp": "webp", "gif": "gif"}

# The emulator's screendump surrounds the panel with a black border, so frames
# have to be cropped back to the real display before they are masked or saved.
DISPLAY_SIZE = {
    "basalt": (144, 168),
    "chalk": (180, 180),
    "emery": (200, 228),
    "gabbro": (260, 260),
}

# FRAME_MS * steps-per-pass, from main.c and readme.md.  Only a prior: the seam
# is measured, and this bounds how long to record and sanity-checks the result.
NOMINAL_PASS_SECONDS = {
    "basalt": 9.65,
    "chalk": 11.55,
    "emery": 12.65,
    "gabbro": 15.85,
}
DEFAULT_PASS_SECONDS = 12.0

# How much longer than one nominal pass to record.  Has to cover the drift while
# staying inside the two passes the run actually lasts.
CAPTURE_MARGIN = 0.7

# Corner masks from pebble-tool's ScreenshotCommand._roundify, which lifted them
# from display_spalding.c.  Top half only; the shape is symmetric.
ROUNDNESS = {
    "chalk": [76, 71, 66, 63, 60, 57, 55, 52, 50, 48, 46, 45, 43, 41, 40, 38, 37,
              36, 34, 33, 32, 31, 29, 28, 27, 26, 25, 24, 23, 22, 22, 21, 20, 19,
              18, 18, 17, 16, 15, 15, 14, 13, 13, 12, 12, 11, 10, 10, 9, 9, 8, 8, 7,
              7, 7, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1,
              0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "gabbro": [119, 110, 105, 100, 96, 93, 89, 86, 84, 81, 79, 77, 74, 72, 70, 68, 67,
               65, 63, 62, 60, 58, 57, 55, 54, 53, 51, 50, 49, 48, 46, 45, 44, 43, 42,
               41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 30, 29, 28, 27, 26, 26,
               25, 24, 23, 23, 22, 21, 21, 20, 20, 19, 18, 18, 17, 17, 16, 15, 15, 14,
               14, 13, 13, 12, 12, 12, 11, 11, 10, 10, 9, 9, 9, 8, 8, 7, 7, 7, 6, 6,
               6, 6, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1,
               1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}


def setup_environment():
    """Do what pebble_tool.run_tool does before dispatching a command.

    Without this, qemu-pebble is not on PATH and the emulator never spawns.
    """
    maybe_apply_wsl_hacks()
    if sdk_version() is not None:
        os.environ["PATH"] = "{}:{}".format(
            os.path.join(get_persist_dir(), "SDKs", sdk_version(), "toolchain", "bin"),
            os.environ["PATH"])
    extra_path = os.environ.get("PEBBLE_EXTRA_PATH")
    if extra_path:
        os.environ["PATH"] = "{}:{}".format(extra_path, os.environ["PATH"])


class GifCapture(ScreenshotCommand):
    """Borrows pebble-tool's emulator plumbing; supplies its own capture window."""

    def __init__(self, args):
        super(GifCapture, self).__init__()
        self.args = args
        self.pebble = None
        self._verbosity = args.v  # normally set by BaseCommand.__call__, which we bypass

    def capture(self, platform_name, pbw_path, filename):
        target_sdk = self.args.sdk or sdk_manager.get_current_sdk()
        persist_dir = get_sdk_persist_dir(platform_name, target_sdk)
        if os.path.exists(persist_dir):
            shutil.rmtree(persist_dir)

        pass_seconds = self.args.pass_seconds or NOMINAL_PASS_SECONDS.get(
            platform_name, DEFAULT_PASS_SECONDS)
        pebble = None
        try:
            pebble = self._connect_emulator(platform_name, self.args.sdk)
            self.pebble = pebble
            # pypkjs accepts the connection before it can relay a bundle to a
            # freshly-booted watch; pebble-tool waits here too.
            time.sleep(5)
            ToolAppInstaller(pebble, pbw_path, quiet=True).install()

            monitor_port = getattr(pebble.transport, "qemu_monitor_port", None)
            if not monitor_port:
                raise ToolError("QEMU monitor port not available; cannot capture frames.")

            frames, fps = self._record(pebble, monitor_port, platform_name, pass_seconds)
            frames = _trim_to_pass(frames, fps, pass_seconds)
            if self.args.frame_step > 1:
                frames = frames[::self.args.frame_step]
            # Play the pass back over the time it takes on a watch rather than
            # the time it took here: the emulator's app timer does not keep to
            # FRAME_MS, so the capture is a few percent off real hardware.  This
            # also absorbs --frame-step, which drops frames without shortening
            # the pass.
            playback_fps = len(frames) / pass_seconds
            if abs(playback_fps - fps) > 0.05 * fps:
                print("  pacing playback at {:.1f} fps rather than the captured {:.1f} "
                      "to match hardware".format(playback_fps, fps))
            frames = _normalize_brightness(frames)
            roundness = None if self.args.no_round_mask else ROUNDNESS.get(platform_name)
            if roundness:
                frames = _mask_corners(frames, roundness)
            _encode(frames, filename, pass_seconds, self.args.format)
        finally:
            self._close_pebble_connection(pebble)
            self.pebble = None
            self._shutdown_platform_emulator(platform_name, self.args.sdk)

    def _grab(self, monitor_port, temp_dir, index, platform_name):
        """One cropped frame, or None if the dump never landed."""
        ppm_path = os.path.join(temp_dir, "probe_{:05d}.ppm".format(index))
        self._qemu_monitor_command(monitor_port, "screendump {}".format(ppm_path))
        frame = _read_ppm(ppm_path)
        if frame is None:
            return None
        return _crop_to_display(frame, platform_name)

    def _wait_for_rest(self, monitor_port, platform_name, pass_seconds):
        """Block until the scene stops moving.

        Installing the app activates it, which starts a run of its own.  That has
        to be over before the tap, or the tap merely extends it: the capture
        would start mid-pass, and -- because the run ends a fixed number of
        billboard crossings after the tap, not a fixed time -- it could come to
        rest inside the capture window.  How long the run takes is exactly what
        this script does not want to assume, so watch the billboard instead of
        sleeping on the nominal figure.
        """
        timeout = 5 * pass_seconds + 15
        print("  waiting up to {:.0f}s for the scene to come to rest...".format(timeout))
        temp_dir = tempfile.mkdtemp(prefix="pebble-rest-")
        try:
            deadline = time.time() + timeout
            index = 0
            previous = None
            stable = 0
            while time.time() < deadline:
                index += 1
                frame = self._grab(monitor_port, temp_dir, index, platform_name)
                centre = None
                if frame is not None:
                    peak = max(channel[1] for channel in frame.getextrema())
                    centre = _panel_centre(frame, _billboard_band(frame.size[1]), peak * 0.55)
                # The billboard is off-screen for two seconds of every pass, so
                # an absent panel is motion, not rest.
                if centre is not None and previous is not None and abs(centre - previous) < 0.5:
                    stable += 1
                    if stable >= 2:
                        return
                else:
                    stable = 0
                previous = centre
                time.sleep(0.6)
            raise ToolError("Scene was still moving after {:.0f}s.".format(timeout))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _record(self, pebble, monitor_port, platform_name, pass_seconds):
        """Capture a little over one pass.  Returns the frames and their rate."""
        self._wait_for_rest(monitor_port, platform_name, pass_seconds)

        # Start just past a wall-clock minute boundary, so the minute never rolls
        # over mid-capture -- a changing digit would be a seam of its own.  The
        # panel is recorded unlit and normalized during encoding, exactly as
        # pebble-tool does, because nothing we can inject lights a watchface.
        wait = 60 - (time.time() % 60) + 1.0
        if wait < 2.0:
            wait += 60
        print("  waiting {:.1f}s for a clean window...".format(wait))
        time.sleep(wait)

        # A tap restarts the run from the centred offset the scene is resting at.
        send_data_to_qemu(pebble.transport, QemuTap(axis=QemuTap.Axis.X, direction=1))

        duration = pass_seconds * (1 + CAPTURE_MARGIN)
        print("  capturing {:.1f}s at up to {} fps...".format(duration, self.args.fps))
        temp_dir = tempfile.mkdtemp(prefix="pebble-loop-")
        requests = []
        try:
            # Only ask QEMU for dumps in here, and decode them afterwards: the
            # writes are asynchronous, so waiting for each file to land would
            # both slow the loop down and race the last of the bytes.
            interval = 1.0 / self.args.fps
            start = time.perf_counter()
            next_frame = start
            index = 0
            while time.perf_counter() - start < duration:
                now = time.perf_counter()
                if now < next_frame:
                    time.sleep(next_frame - now)
                next_frame = max(next_frame + interval, time.perf_counter())
                index += 1

                ppm_path = os.path.join(temp_dir, "frame_{:05d}.ppm".format(index))
                stamp = time.perf_counter()
                try:
                    self._qemu_monitor_command(monitor_port, "screendump {}".format(ppm_path))
                except Exception as e:
                    print("  frame {} failed: {}".format(index, e))
                    continue
                requests.append((stamp, ppm_path))

            frames = []
            stamps = []
            for stamp, ppm_path in requests:
                frame = _read_ppm(ppm_path)
                if frame is None:
                    print("  frame {} never landed".format(os.path.basename(ppm_path)))
                    continue
                frames.append(_crop_to_display(frame, platform_name))
                stamps.append(stamp)

            if len(frames) < 2:
                raise ToolError("Captured {} frames; need at least two.".format(len(frames)))

            # screendump costs more than the frame interval on a busy machine, so
            # the rate actually achieved is what the GIF has to be played back
            # at -- encoding at the requested rate would speed the scene up by
            # however much the capture fell behind.
            fps = (len(frames) - 1) / (stamps[-1] - stamps[0])
            print("  captured {} frames at {:.1f} fps".format(len(frames), fps))
            if fps < self.args.fps * 0.9:
                print("  note: capture fell well short of {} fps; the GIF will be coarse but "
                      "correctly paced".format(self.args.fps))
            return frames, fps
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _read_ppm(path, timeout=1.0):
    """Decode a screendump, waiting for QEMU to finish writing it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                with Image.open(path) as img:
                    return img.convert("RGB")
            except OSError:
                pass  # still being written
        time.sleep(0.01)
    return None


def _crop_to_display(frame, platform_name):
    """Trim the black border the emulator's screendump puts around the panel."""
    size = DISPLAY_SIZE.get(platform_name)
    if size is None:
        return frame
    width, height = size
    have_width, have_height = frame.size
    if have_width < width or have_height < height:
        raise ToolError("Screendump is {}x{}, smaller than {}'s {}x{} display.".format(
            have_width, have_height, platform_name, width, height))
    left = (have_width - width) // 2
    top = (have_height - height) // 2
    return frame.crop((left, top, left + width, top + height))


def _billboard_band(height):
    """Rows spanned by the billboard's clock panel.

    Mirrors main.c: the panel starts BB_PANEL_Y below BB_Y and is BB_PANEL_H
    tall, all three scaled from the 228px emery reference, which reduces to a
    fraction of the display height on every platform.
    """
    return (height * (134 + 12) // 228, height * (134 + 12 + 44) // 228)


def _panel_centre(frame, band, threshold):
    """Horizontal centre of the clock panel, or None if it is off-screen.

    The panel is white and the lit windows around it are strongly coloured, so
    thresholding on the *smallest* channel picks out the panel and nothing else.
    """
    top, bottom = band
    width = frame.size[0]
    pixels = frame.load()
    count = 0
    weighted = 0
    for y in range(top, bottom):
        for x in range(width):
            r, g, b = pixels[x, y]
            if min(r, g, b) >= threshold:
                count += 1
                weighted += x
    if count < width:  # less than a row's worth: the panel is not there
        return None
    return weighted / float(count)


def _trim_to_pass(frames, fps, pass_seconds):
    """Keep frames[0:seam], one billboard pass, measured off the clock panel."""
    band = _billboard_band(frames[0].size[1])
    peak = max(max(channel[1] for channel in frame.getextrema()) for frame in frames)
    centres = [_panel_centre(frame, band, peak * 0.55) for frame in frames]
    if centres[0] is None:
        raise ToolError("Billboard was not on screen at the start of the capture.")

    # The billboard leaves the display once per pass, and the gap is the
    # deliberate stall with the skyline empty.  Between that gap and the next one
    # the board crosses the display exactly once, so the frame in there that best
    # matches frame 0 is the seam.  Bounding the search matters both ways: before
    # the gap the board has not gone anywhere yet, and stray near-white pixels
    # from the lit windows jitter the centre by a fraction of a pixel, so walking
    # until the distance grows stops early on the jitter rather than at the seam.
    gap = next((i for i in range(1, len(centres))
                if centres[i] is None and any(c is not None for c in centres[i:])), None)
    if gap is None:
        raise ToolError("Capture did not cover a pass: the billboard never left and came back.")
    crossing = next((i for i in range(gap, len(centres)) if centres[i] is not None), None)
    if crossing is None:
        raise ToolError("Capture ended during the billboard's pause; record for longer.")
    end = next((i for i in range(crossing, len(centres)) if centres[i] is None), len(centres))

    seam = min(range(crossing, end), key=lambda i: abs(centres[i] - centres[0]))
    offset = centres[seam] - centres[0]

    measured = seam / fps
    print("  pass is {} frames ({:.2f}s, nominal {:.2f}s); billboard lands {:+.1f}px "
          "from where it started".format(seam, measured, pass_seconds, offset))
    if end == len(centres):
        print("  warning: the capture ended before the billboard left again, so the seam is "
              "the best of a window that may have been cut short")
    if abs(offset) > 2.0:
        raise ToolError(
            "Billboard lands {:+.1f}px from where it started, which would show as a jump. "
            "Try a higher --fps.".format(offset))
    if abs(measured - pass_seconds) > 0.25 * pass_seconds:
        raise ToolError(
            "Measured pass of {:.2f}s is nowhere near the {:.2f}s the constants imply, so the "
            "seam is probably wrong. Pass --pass-seconds to override the expected "
            "length.".format(measured, pass_seconds))
    return frames[:seam]


def _read_loop(path):
    """Frames and total running time of a loop this script wrote earlier.

    The duration comes from the file rather than the table, so re-encoding
    preserves whatever pacing the capture settled on.  Brightness and the corner
    mask are already baked in.
    """
    frames = []
    total_ms = 0.0
    with Image.open(path) as animation:
        count = getattr(animation, "n_frames", 1)
        for index in range(count):
            animation.seek(index)
            frames.append(animation.convert("RGBA"))
            total_ms += animation.info.get("duration") or 0
    if not frames:
        raise ToolError("No frames in {}.".format(path))
    if total_ms <= 0:
        raise ToolError("{} carries no frame timing to re-encode from.".format(path))
    return frames, total_ms / 1000.0


def _normalize_brightness(frames):
    """Scale the unlit panel back up to full brightness.

    Nothing that can be injected lights the backlight on a watchface, so the
    capture is of an unlit display: a flat linear scale on every channel.  Doing
    this here rather than in an ffmpeg filter keeps every output format built
    from identical pixels, and lets the GIF writer see the real colour count.
    """
    peak = max(max(channel[1] for channel in frame.getextrema()) for frame in frames)
    if peak <= 0 or peak >= 250:
        return frames
    print("  panel was captured at {:.0f}% brightness; scaling back up".format(peak / 2.55))
    # lrint, to match the lutrgb expression this replaces.
    lut = [min(255, int(round(value * 255.0 / peak))) for value in range(256)]
    return [frame.point(lut * len(frame.getbands())) for frame in frames]


def _mask_corners(frames, roundness):
    """Punch the round display's corners out to transparency."""
    skips = list(roundness) + list(reversed(roundness))
    width, height = frames[0].size
    if len(skips) != height:
        raise ToolError("Corner mask is {} rows; display is {}.".format(len(skips), height))
    mask = Image.new("L", (width, height), 255)
    pixels = mask.load()
    for y, skip in enumerate(skips):
        for x in range(width):
            if not skip <= x < width - skip:
                pixels[x, y] = 0
    masked = []
    for frame in frames:
        rgba = frame.convert("RGBA")
        rgba.putalpha(mask)
        masked.append(rgba)
    return masked


def _gif_delays(count, total_seconds):
    """Whole-centisecond delays for each frame, summing to total_seconds.

    A GIF cannot hold a frame rate: it holds a delay per frame, in hundredths of
    a second.  None of these passes runs at a rate that divides into that, so a
    single delay would have to be rounded and the loop would drift -- basalt's
    18.3 fps rounds to 5cs and plays 8% fast, which is exactly the hardware
    pacing this script goes to trouble to get right.  Rounding each frame's
    cumulative position instead spreads the error: frames come out 5cs or 6cs,
    a 10ms difference nobody can see, and the total is exact.
    """
    edges = [int(round(total_seconds * 100.0 * index / count)) for index in range(count + 1)]
    return [edges[index + 1] - edges[index] for index in range(count)]


def _walk_gif(data):
    """Yield the offset of every graphic control extension, in order.

    Just enough GIF structure to find them: the header and its global colour
    table, then blocks, skipping each one's sub-block chain.
    """
    if data[:6] not in (b"GIF89a", b"GIF87a"):
        raise ToolError("Not a GIF.")
    offset = 13
    if data[10] & 0x80:
        offset += 3 * 2 ** ((data[10] & 7) + 1)
    while offset < len(data):
        marker = data[offset]
        if marker == 0x3B:  # trailer
            return
        if marker == 0x21:  # extension
            label = data[offset + 1]
            if label == 0xF9:
                yield offset
            offset += 2
            while data[offset] != 0:
                offset += 1 + data[offset]
            offset += 1
        elif marker == 0x2C:  # image descriptor
            flags = data[offset + 9]
            offset += 10
            if flags & 0x80:
                offset += 3 * 2 ** ((flags & 7) + 1)
            offset += 1  # LZW minimum code size
            while data[offset] != 0:
                offset += 1 + data[offset]
            offset += 1
        else:
            raise ToolError("Unexpected GIF block {:#x} at {}.".format(marker, offset))


def _patch_gif_delays(filename, delays):
    """Rewrite each frame's delay in place.

    ffmpeg's GIF encoder is worth keeping -- it rewrites pixels that did not
    change as the transparent index, which this scene compresses to about half
    what writing whole frames does -- but it can only be told a constant frame
    rate, and feeding it per-frame durations through the concat demuxer comes
    back quantised into a 4cs/8cs stutter.  The delays are two bytes inside each
    control block, so set them afterwards instead.
    """
    data = bytearray(open(filename, "rb").read())
    offsets = list(_walk_gif(data))
    if len(offsets) != len(delays):
        raise ToolError("GIF has {} frames but {} delays.".format(len(offsets), len(delays)))
    for offset, delay in zip(offsets, delays):
        # 0x21 0xF9 <block size> <flags> <delay lo> <delay hi> ...
        struct.pack_into("<H", data, offset + 4, delay)
    open(filename, "wb").write(data)


def _encode(frames, filename, total_seconds, image_format):
    output_dir = os.path.dirname(filename)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    temp_dir = tempfile.mkdtemp(prefix="pebble-loop-enc-")
    try:
        for index, frame in enumerate(frames):
            frame.save(os.path.join(temp_dir, "frame_{:05d}.png".format(index)))
        pattern = os.path.join(temp_dir, "frame_%05d.png")
        rate = "{:.4f}".format(len(frames) / total_seconds)

        if image_format == "apng":
            # RGBA rather than indexed: an APNG palette holds 256 entries, and
            # while the art itself uses 15 colours, chalk's emulator antialiases
            # the rim of its round display and pushes the count past 460.  The -f
            # is needed because ffmpeg otherwise reads a .png output as a request
            # for one file per frame.
            _ffmpeg(["ffmpeg", "-framerate", rate, "-i", pattern,
                     "-vf", "format=rgba",
                     "-c:v", "apng", "-pred", "mixed", "-plays", "0",
                     "-f", "apng", "-y", filename, "-v", "error"], "APNG encoding")
        elif image_format == "webp":
            # Lossless, and bgra because libwebp_anim's only other pixel formats
            # are subsampled YUV, which would smear both the dithered sunset and
            # the single-pixel windows.  The encoder merges frames that repeat --
            # the billboard's stall produces a few -- and keeps their duration.
            _ffmpeg(["ffmpeg", "-framerate", rate, "-i", pattern,
                     "-vf", "format=rgba",
                     "-c:v", "libwebp_anim", "-lossless", "1",
                     "-compression_level", "6", "-pix_fmt", "bgra", "-loop", "0",
                     "-y", filename, "-v", "error"], "WebP encoding")
        else:
            # 255 colours and a reserved transparent entry, which the round
            # displays need for their corners and which every platform benefits
            # from: ffmpeg writes pixels that did not change as transparent, and
            # this scene compresses to about half the size that way.
            palette = os.path.join(temp_dir, "palette.png")
            _ffmpeg(["ffmpeg", "-framerate", rate, "-i", pattern,
                     "-vf", "palettegen=max_colors=255:reserve_transparent=1",
                     "-y", palette, "-v", "error"], "palette generation")
            _ffmpeg(["ffmpeg", "-framerate", rate, "-i", pattern, "-i", palette,
                     "-filter_complex", "[0:v][1:v]paletteuse=dither=none:alpha_threshold=128",
                     "-loop", "0", "-y", filename, "-v", "error"], "GIF encoding")
            _patch_gif_delays(filename, _gif_delays(len(frames), total_seconds))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("  saved {} ({}x{}, {} frames over {:.2f}s, {:.1f} KiB)".format(
        filename, frames[0].size[0], frames[0].size[1], len(frames), total_seconds,
        os.path.getsize(filename) / 1024.0))


def _ffmpeg(command, step):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ToolError("{} failed: {}".format(step, result.stderr.strip()))


def _find_loop(out_dir, platform_name, target_extension):
    """The best existing loop to re-encode: the lossless ones before the GIF."""
    for extension in ("png", "webp", "gif"):
        if extension == target_extension:
            continue
        candidate = os.path.join(out_dir, "{}-loop.{}".format(platform_name, extension))
        if os.path.exists(candidate):
            return candidate
    raise ToolError("No loop to convert for {} in {}; capture one first.".format(
        platform_name, out_dir))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platforms", nargs="*",
                        help="Platforms to capture (default: every target platform).")
    parser.add_argument("--fps", type=int, default=20,
                        help="Frame rate to aim for (default: 20, the rate the app animates at).")
    parser.add_argument("--format", choices=["gif", "apng", "webp"], default="gif",
                        help="Output format (default: gif, the only one the storefronts actually "
                             "animate). apng and webp are smaller and exactly lossless, and are "
                             "worth keeping as masters to --convert from.")
    parser.add_argument("--convert", action="store_true",
                        help="Re-encode the loops already in --out-dir into --format instead of "
                             "capturing new ones. Needs no emulator.")
    parser.add_argument("--frame-step", type=int, default=1, metavar="N",
                        help="Keep only every Nth frame. Halves the file size per doubling, at "
                             "the cost of a coarser scroll; the loop still runs for a pass.")
    parser.add_argument("--pass-seconds", type=float,
                        help="Override the expected length of one billboard pass.")
    parser.add_argument("--no-round-mask", action="store_true",
                        help="Leave the corners of round displays opaque.")
    parser.add_argument("--out-dir", default="screenshots", help="Where to write the loops.")
    parser.add_argument("--sdk", help="SDK version to launch (default: the active SDK).")
    parser.add_argument("-v", action="count", default=0, help="Verbosity, passed to pebble-tool.")
    args = parser.parse_args()

    setup_environment()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required. Install with: sudo apt install ffmpeg")

    command = GifCapture(args)
    project, pbw_path = command._ensure_project_pbw(args)
    platforms, version = command._extract_pbw_metadata(pbw_path, project)
    if args.platforms:
        unknown = [p for p in args.platforms if p not in platforms]
        if unknown:
            sys.exit("Not a target platform of this app: {}".format(", ".join(unknown)))
        platforms = args.platforms

    out_dir = os.path.join(project.project_dir, args.out_dir)
    target_extension = FILE_EXTENSION[args.format]

    if args.convert:
        for platform_name in platforms:
            print("=== {} ===".format(platform_name))
            source = _find_loop(out_dir, platform_name, target_extension)
            frames, total_seconds = _read_loop(source)
            print("  {} frames over {:.2f}s from {}".format(
                len(frames), total_seconds, os.path.basename(source)))
            _encode(frames, os.path.join(out_dir, "{}-loop.{}".format(platform_name,
                                                                      target_extension)),
                    total_seconds, args.format)
        return

    print("PBW {} (version {})".format(pbw_path, version))

    for platform_name in platforms:
        print("=== {} ===".format(platform_name))
        command.capture(platform_name, pbw_path,
                        os.path.join(out_dir, "{}-loop.{}".format(platform_name,
                                                                  target_extension)))


if __name__ == "__main__":
    main()
