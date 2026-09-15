#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Point this at the SDK's sdk-core/pebble directory; each platform's headers
# live in a subdirectory of it.  PEBBLE_SDK_INCLUDE (one platform's include
# directory) is still honoured, for muscle memory.
if [[ -z "${PEBBLE_SDK_PEBBLE:-}" && -n "${PEBBLE_SDK_INCLUDE:-}" ]]; then
  PEBBLE_SDK_PEBBLE=$(dirname "$(dirname "$PEBBLE_SDK_INCLUDE")")
fi
: "${PEBBLE_SDK_PEBBLE:?Set to the sdk-core/pebble directory of your Pebble SDK}"

test_binary=$(mktemp /tmp/streamingvillage-tests.XXXXXX)
trap 'rm -f "$test_binary"' EXIT

platforms=("$@")
if [[ ${#platforms[@]} -eq 0 ]]; then
  platforms=(emery basalt)
fi

result=0
for platform in "${platforms[@]}"; do
  case "$platform" in
    emery)  defines="-DPBL_PLATFORM_EMERY -DPBL_DISPLAY_WIDTH=200 -DPBL_DISPLAY_HEIGHT=228" ;;
    basalt) defines="-DPBL_PLATFORM_BASALT -DPBL_DISPLAY_WIDTH=144 -DPBL_DISPLAY_HEIGHT=168" ;;
    *) echo "unknown platform: $platform" >&2; exit 2 ;;
  esac

  # build/<platform> holds the resource ids a `pebble build` generated.
  gcc -std=gnu11 -O2 -ffunction-sections -fdata-sections \
    -DPBL_COLOR $defines \
    -Itests/include -I"$PEBBLE_SDK_PEBBLE/$platform/include" \
    -Ibuild/include -I"build/$platform" \
    tests/power_savings.c -Wl,--gc-sections -o "$test_binary"

  for scenario in focus frames obstruction billboard; do
    if "$test_binary" "$scenario"; then
      echo "PASS: $platform $scenario"
    else
      result=1
    fi
  done
done
exit "$result"
