#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output="$(realpath "$1")"
test -f "$output/orb60_registers.h"
gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread -I"$output" "$root/linux/server.c" "$root/linux/engine.c" "$root/linux/pipeline.c" -o "$output/orb60-server-host"
gcc -std=c11 -O2 -Wall -Wextra -Werror -I"$output" "$root/linux/test_engine.c" "$root/linux/engine.c" -o "$output/test-engine"
"$output/test-engine"
python3 "$root/linux/test_network.py" --server "$output/orb60-server-host"
python3 "$root/linux/test_pipeline.py" --server "$output/orb60-server-host"
arm-linux-gnueabihf-gcc -std=c11 -O2 -Wall -Wextra -Werror -static -mcpu=cortex-a9 -mfpu=neon \
    -pthread -I"$output" "$root/linux/server.c" "$root/linux/engine.c" "$root/linux/pipeline.c" -o "$output/orb60-server-arm"
arm-linux-gnueabihf-gcc -std=c11 -O2 -Wall -Wextra -Werror -static -mcpu=cortex-a9 \
    "$root/linux/board_probe.c" -o "$output/board-probe"
dtc -@ -I dts -O dtb "$root/linux/acz7015-orb60.dts" -o "$output/acz7015-orb60.dtbo" 2>"$output/dtc.log"
cp "$root/linux/load_board.sh" "$output/"
{ gcc --version | head -1; arm-linux-gnueabihf-gcc --version | head -1; dtc --version; } > "$output/compiler_versions.txt"
echo LINUX_DRIVER_SERVER_HOST_GATES_ARM_BUILD_PASS
