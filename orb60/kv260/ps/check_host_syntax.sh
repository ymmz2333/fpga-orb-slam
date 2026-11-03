#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
source="$root/orb60/build/kv260_system/ps_source_v2_20261102"
cmake -S "$source/Thirdparty/g2o" -B "$source/Thirdparty/g2o/build_host_syntax" -DCMAKE_BUILD_TYPE=Release
for file in src/System.cc src/Map.cc Examples/Monocular/mono_kv260.cc; do
    printf 'KV260_PS_HOST_SYNTAX %s\n' "$file"
    g++ -std=c++14 -DCOMPILEDWITHC11 -DREGISTER_TIMES -fsyntax-only -w \
      -I"$source" -I"$source/include" -I"$source/include/CameraModels" \
      -I"$source/Thirdparty/Sophus" -I/usr/include/eigen3 -I/usr/include/opencv4 \
      "$source/$file"
done
echo KV260_PS_HOST_SYNTAX_PASS_NOT_AARCH64_LINK
