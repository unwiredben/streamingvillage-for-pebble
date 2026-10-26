# Version 1.4.0 store asset refresh

**Goal:** Refresh listing stills and all four store GIFs, guaranteeing a visible robot in every animation.

**Approach:** Add the requested `tools/launch.py --force-robot` session override. Accept native launch argument bit 0 and a validated `ForceRobot` AppMessage for CLI/emulator launches. Capture uses that same override, records both billboard passes so the robot finishes walking before the cut, and verifies robot motion from its distinctive lavender armour. Preserve normal random selection when the override is absent. Keep the existing icon composition and regenerate its deterministic artwork.

- [x] Test the force-robot override, message validation and return to random selection on all platforms.
- [x] Add the launcher and capture option, with tests for robot recognition and two-pass trimming.
- [x] Rebuild 1.4.0 and capture all four robot runs, listing stills, GIFs and APNG masters.
- [x] Inspect decoded GIFs for robot motion, dimensions, duration and round-display transparency; document the commands and verify icons.

Verified all 28 host scenarios, three city generator checks, five artwork checks and six capture checks. Built all four platforms. Decoded each final GIF and verified left-to-right robot motion, absence of the robot at both ends, unchanged clock glyphs across the cut, expected duration and dimensions, and transparent round corners. Packaged 23 files with 1.4.0 manifest and hashes. The launcher waits for ACK, retries a fresh app inbox, and leaves the override session-only.
