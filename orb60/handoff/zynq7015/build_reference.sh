#!/bin/sh
# Build the portable reference and existing PS engine. No board access.
set -eu
bundle=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output=$1
mkdir -p "$output"
cc -std=c99 -O2 -Wall -Wextra -Werror "$bundle/reference/reference.c" "$bundle/reference/test_reference.c" -lm -o "$output/test-reference"
"$output/test-reference" "$output"
c++ -O2 -std=c++17 -Wall -Wextra -Werror "$bundle/reference/fixed_pnp.cpp" $(pkg-config --cflags --libs opencv4) -o "$output/fixed-pnp"
cc -std=c11 -O2 -Wall -Wextra -Werror -pthread -I"$bundle/reference/ps" \
    "$bundle/reference/ps/server.c" "$bundle/reference/ps/engine.c" "$bundle/reference/ps/pipeline.c" -o "$output/orb60-server-host"
cc -std=c11 -O2 -Wall -Wextra -Werror -I"$bundle/reference/ps" \
    "$bundle/reference/ps/test_engine.c" "$bundle/reference/ps/engine.c" -o "$output/test-engine"
"$output/test-engine"
cc -std=c99 -O2 -Wall -Wextra -Werror -I"$bundle/reference/ps" -c "$bundle/reference/ps_direct_example.c" -o "$output/ps-direct-example.o"
echo HANDOFF_REFERENCE_BUILD_PASS
