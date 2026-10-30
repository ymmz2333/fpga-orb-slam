#!/usr/bin/env bash
# PC/PS software environment only. Never invoke RK3588 or change SLAM algorithms.
set -euo pipefail
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 20.04 && "$(uname -m)" == x86_64 ]]
[[ "$(id -u)" == 0 ]] || { echo 'Run dependency installation as WSL root'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=3 update
apt-get -o Acquire::Retries=3 install -y build-essential gcc-9 g++-9 cmake git ca-certificates curl \
    libeigen3-dev libboost-serialization-dev libssl-dev libgl1-mesa-dev libglew-dev \
    libjpeg-dev libpng-dev libepoxy-dev libwayland-dev libxkbcommon-dev \
    python3 python3-numpy python3-pip python3-venv stressapptest gdb rsync unzip pkg-config
gcc-9 --version | head -n 1
cmake --version | head -n 1
dpkg-query -W -f='${Package},${Version}\n' gcc-9 g++-9 libeigen3-dev libboost-serialization-dev stressapptest
[[ "$(gcc-9 -dumpfullversion)" == 9.4.0 ]]
[[ "$(dpkg-query -W -f='${Version}' libeigen3-dev)" == 3.3.7* ]]
[[ "$(dpkg-query -W -f='${Version}' libboost-serialization-dev)" == 1.71* ]]
if ! id slam >/dev/null 2>&1; then useradd --create-home --shell /bin/bash slam; fi
mkdir -p /home/slam/orbslam3_cpu_baseline
chown slam:slam /home/slam/orbslam3_cpu_baseline
echo 'PC0_DEPENDENCIES_PASS; OpenCV/Pangolin/ORB build and platform test still pending'
