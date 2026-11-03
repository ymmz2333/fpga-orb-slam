#!/bin/sh
# Build only this Linux PS capture adapter; no firmware or driver installation.
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=${1:?Usage: build.sh FRESH_OUTPUT_DIRECTORY}
test ! -e "$out"
mkdir -p "$out"
cc -std=c11 -O2 -Wall -Wextra -Werror -Wno-misleading-indentation \
    "$src/test_capture.c" -o "$out/test_capture"
"$out/test_capture" > "$out/unit.log"
cc -std=c11 -O3 -Wall -Wextra -Werror -Wno-misleading-indentation -fPIC -shared \
    "$src/v4l2_capture.c" -o "$out/liborb60_v4l2.so"
cc --version | head -n 1 > "$out/compiler.txt"
sha256sum "$src/v4l2_capture.c" "$out/liborb60_v4l2.so" > "$out/SHA256SUMS"
