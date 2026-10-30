"""Tiny dependency-free grayscale image helpers.

PGM is used so the template works with the existing Python installation and
does not require NumPy, Pillow, or OpenCV.  Most image viewers can open PGM.
"""
from pathlib import Path


def make_test_pattern(width, height):
    """Return a deterministic grayscale pattern as bytes."""
    data = bytearray()
    for y in range(height):
        for x in range(width):
            checker = 55 if ((x // 4) ^ (y // 3)) & 1 else 0
            data.append((x * 11 + y * 17 + checker) & 0xFF)
    return bytes(data)


def invert_reference(data):
    return bytes(255 - value for value in bytearray(data))


def write_pgm(path, width, height, data):
    path = Path(path)
    if len(data) != width * height:
        raise ValueError("pixel count does not match image dimensions")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write("P5\n{} {}\n255\n".format(width, height).encode("ascii"))
        stream.write(bytes(data))


def read_pgm(path):
    """Read a binary P5 PGM without external packages."""
    raw = Path(path).read_bytes()
    if not raw.startswith(b"P5"):
        raise ValueError("only binary P5 PGM is supported")

    tokens = []
    index = 2
    while len(tokens) < 3:
        while index < len(raw) and raw[index:index + 1].isspace():
            index += 1
        if index < len(raw) and raw[index:index + 1] == b"#":
            while index < len(raw) and raw[index:index + 1] not in (b"\n", b"\r"):
                index += 1
            continue
        start = index
        while index < len(raw) and not raw[index:index + 1].isspace():
            index += 1
        tokens.append(int(raw[start:index]))

    width, height, maximum = tokens
    if maximum != 255:
        raise ValueError("only 8-bit PGM is supported")
    while index < len(raw) and raw[index:index + 1].isspace():
        index += 1
    pixels = raw[index:index + width * height]
    if len(pixels) != width * height:
        raise ValueError("truncated PGM data")
    return width, height, pixels

