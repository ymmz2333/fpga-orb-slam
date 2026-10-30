#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
run_logged apt-update sudo -n apt-get update
run_logged apt-install sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential cmake git libeigen3-dev libboost-serialization-dev libssl-dev \
    libgl1-mesa-dev libglew-dev libegl1-mesa-dev libx11-dev libxrandr-dev libxi-dev \
    libjpeg-dev libpng-dev libtiff-dev pkg-config python3-dev python3-venv rsync unzip
run_logged apt-check sudo -n apt-get check
dpkg --audit | tee "$experiment_root/logs/dpkg-audit.log"
