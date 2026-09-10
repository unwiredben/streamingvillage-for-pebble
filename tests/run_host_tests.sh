#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PEBBLE_SDK_INCLUDE:?Set to the emery include directory of your Pebble SDK}"
test_binary=$(mktemp /tmp/streamingvillage-tests.XXXXXX)
trap 'rm -f "$test_binary"' EXIT
gcc -std=gnu11 -O2 -ffunction-sections -fdata-sections \
  -DPBL_PLATFORM_EMERY -DPBL_COLOR -DPBL_DISPLAY_WIDTH=200 -DPBL_DISPLAY_HEIGHT=228 \
  -Itests/include -I"$PEBBLE_SDK_INCLUDE" -Ibuild/include -Ibuild/emery \
  tests/power_savings.c -Wl,--gc-sections -o "$test_binary"
result=0
for scenario in focus frames obstruction billboard; do
  if "$test_binary" "$scenario"; then
    echo "PASS: $scenario"
  else
    result=1
  fi
done
exit "$result"
