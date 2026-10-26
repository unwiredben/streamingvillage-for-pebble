# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
"""Capture checks; run with pebble-tool's Python (Pillow and libpebble2)."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

spec = importlib.util.spec_from_file_location(
    "capture", Path(__file__).resolve().parents[1] / "tools/capture_loop.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTest(unittest.TestCase):
    def test_wait_for_rest_requires_the_city_to_stop_too(self):
        frames = []
        for x in (10, 20, 30):
            frame = Image.new("RGB", (100, 228))
            draw = ImageDraw.Draw(frame)
            draw.rectangle((40, 150, 59, 179), fill="white")
            draw.rectangle((x, 40, x+4, 60), fill="blue")
            frames.append(frame)
        frames.extend([frames[-1], frames[-1]])
        command = capture.GifCapture(type("Args", (), {"v": 0})())
        with patch.object(command, '_grab', side_effect=frames) as grab, \
             patch.object(capture.time, 'sleep'):
            command._wait_for_rest(None, 'emery', 1)
        self.assertEqual(grab.call_count, 5)

    def test_launch_waits_for_a_ready_inbox_and_rejects_failed_overrides(self):
        class StartingWatch:
            def __init__(self, responses):
                self.responses = list(responses)
                self.handlers = {}
                self.closed = False

            def register_handler(self, name, handler):
                self.handlers[name] = handler

            def send_message(self, app, data):
                ok = self.responses.pop(0)
                self.handlers['ack' if ok else 'nack'](2, app)

            def shutdown(self):
                self.closed = True

        app = 'fb61b0cc-998d-4681-a12b-40205a9dd3b2'
        ready = StartingWatch([False, True])
        with patch.object(capture, 'AppMessageService', return_value=ready), \
             patch.object(capture.time, 'sleep'):
            capture.set_force_robot(None, app, attempts=2)
        self.assertTrue(ready.closed)
        rejected = StartingWatch([False, False])
        with patch.object(capture, 'AppMessageService', return_value=rejected), \
             patch.object(capture.time, 'sleep'):
            with self.assertRaises(capture.ToolError):
                capture.set_force_robot(None, app, attempts=2)
        self.assertTrue(rejected.closed)

    def moving_frames(self, colour):
        frames = []
        for x in (10, 45, 80):
            frame = Image.new("RGB", (100, 114), (33, 0, 66))
            ImageDraw.Draw(frame).rectangle((x, 30, x + 5, 45), fill=colour)
            frames.append(frame)
        return frames

    def test_recognizes_robot_even_on_a_dim_emulator(self):
        for colour in ((170, 85, 255), (66, 33, 100)):
            self.assertTrue(capture._has_robot(self.moving_frames(colour)))

    def test_rejects_the_ufo_empty_sky_and_static_purple_art(self):
        self.assertFalse(capture._has_robot(self.moving_frames((170, 170, 255))))
        self.assertFalse(capture._has_robot(self.moving_frames((85, 0, 85))))
        frames = self.moving_frames((170, 85, 255))
        self.assertFalse(capture._has_robot([frames[0]] * 3))

    def test_two_pass_capture_ends_after_the_robot_can_leave(self):
        positions = [50, 35, 20, None, None, 90, 80, 70, 60, 55] * 2
        positions += [50, 50, 50]
        frames = []
        for x in positions:
            frame = Image.new("RGB", (100, 228))
            if x is not None:
                ImageDraw.Draw(frame).rectangle((x-10, 150, x+9, 179),
                                               fill="white")
            frames.append(frame)
        self.assertEqual(len(capture._trim_to_pass(frames, 10, 1)), 10)
        self.assertEqual(len(capture._trim_to_pass(frames, 10, 1, passes=2)), 20)

    def test_pale_windows_cannot_split_the_billboard_gap(self):
        positions = [50, 35, 20, None, None, None, 90, 75, 60, 55] * 2
        positions += [50, 50, 50]
        frames = []
        for index, x in enumerate(positions):
            frame = Image.new("RGB", (100, 228))
            if x is not None:
                ImageDraw.Draw(frame).rectangle((x-10, 150, x+9, 179), fill="white")
            elif index % 10 == 4:
                ImageDraw.Draw(frame).rectangle((40, 150, 59, 179),
                                               fill=(255, 255, 170))
            frames.append(frame)
        self.assertEqual(len(capture._trim_to_pass(frames, 10, 1, passes=2)), 20)


if __name__ == "__main__":
    unittest.main()
