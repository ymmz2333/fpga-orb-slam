#!/usr/bin/env python3
"""Create deterministic synthetic images for A1 startup/shutdown checks only."""
import pathlib
import random
import re
import struct
import zlib

root = pathlib.Path(__file__).resolve().parent.parent
output = root / "runtime/smoke_input"
images = output / "mav0/cam0/data"
images.mkdir(parents=True, exist_ok=True)
width, height, frames = 752, 480, 24
generator = random.Random(3588)
landmarks = []
for v in range(28, height - 25, 19):
    for u in range(28, width - 25, 19):
        depth = generator.uniform(3.0, 7.0)
        patch = bytes(generator.choice((30, 240)) for _ in range(121))
        landmarks.append((depth, u + generator.uniform(-2, 2), v + generator.uniform(-2, 2), patch))
landmarks.sort(reverse=True)


def chunk(kind, content):
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)


timestamps = []
for index in range(frames):
    image = bytearray([15]) * (width * height)
    camera_x = index * 0.025
    for depth, u, v, patch in landmarks:
        center_x = round(u - 500.0 * camera_x / depth)
        center_y = round(v)
        for y in range(11):
            row = center_y + y - 5
            if not 0 <= row < height:
                continue
            for x in range(11):
                column = center_x + x - 5
                if 0 <= column < width:
                    image[row * width + column] = patch[y * 11 + x]
    scanlines = b"".join(b"\0" + image[row * width:(row + 1) * width] for row in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")
    timestamp = 1400000000000000000 + index * 50000000
    timestamps.append(str(timestamp))
    (images / (str(timestamp) + ".png")).write_bytes(png)
(output / "timestamps.txt").write_text("\n".join(timestamps) + "\n")
settings = (root / "vendor/ORB_SLAM3/Examples/Monocular/EuRoC.yaml").read_text()
values = {"Camera1.fx": 500.0, "Camera1.fy": 500.0, "Camera1.cx": 376.0, "Camera1.cy": 240.0,
          "Camera1.k1": 0.0, "Camera1.k2": 0.0, "Camera1.p1": 0.0, "Camera1.p2": 0.0,
          "Camera.newWidth": width, "Camera.newHeight": height}
for name, value in values.items():
    settings, count = re.subn(r"(?m)^" + re.escape(name) + r":.*$", name + ": " + str(value), settings)
    if count != 1:
        raise RuntimeError("Missing or repeated setting: " + name)
(output / "smoke.yaml").write_text(settings)
(output / "README.txt").write_text("SYNTHETIC A1 INPUT. Not EuRoC. No accuracy or performance claims. Seed=3588.\n")
print("Created synthetic A1 smoke sequence:", output)
