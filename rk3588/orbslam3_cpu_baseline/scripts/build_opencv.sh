#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
opencv_source="${OPENCV_SOURCE_DIR:-$experiment_root/vendor/opencv}"
run_logged opencv-configure cmake -S "$opencv_source" -B "$experiment_root/build/opencv" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$install_prefix" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DBUILD_LIST=core,imgproc,imgcodecs,features2d,calib3d,highgui,video,videoio \
    -DBUILD_SHARED_LIBS=ON -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF \
    -DBUILD_opencv_python2=OFF -DBUILD_opencv_python3=OFF -DBUILD_opencv_java=OFF \
    -DWITH_QT=OFF -DWITH_GTK=OFF -DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF \
    -DWITH_OPENCL=OFF -DWITH_TBB=OFF -DOPENCV_ENABLE_NONFREE=OFF
run_logged opencv-build cmake --build "$experiment_root/build/opencv" --parallel "$jobs"
run_logged opencv-install cmake --install "$experiment_root/build/opencv"
