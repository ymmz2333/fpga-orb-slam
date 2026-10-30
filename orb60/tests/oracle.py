"""Independent NumPy/R11 oracle. Never imports a DUT or its profile ROM."""
from math import isqrt
import numpy as np

WIDTHS = (960, 800, 667, 556, 463, 386, 322, 268)
HEIGHTS = (720, 600, 500, 417, 347, 289, 241, 201)
BUDGETS = (217, 181, 151, 126, 105, 87, 73, 60)
FRONT_CASES = (
    (7, 0, 20, 7, 1, 1000, 0), (7, 1, 20, 7, 1, 0, 0),
    (7, 2, 40, 40, 0, 1000, 0), (7, 2, 255, 40, 1, 1000, 0),
    (5, 2, 40, 40, 0, 1000, 0), (7, 2, 40, 40, 0, 0, 0),
    (0, 2, 1, 1, 1, 1000, 0), (7, 0, 20, 7, 0, 1000, 1),
    (7, 0, 20, 7, 0, 1000, 0), (7, 2, 40, 40, 0, 53, 0),
    (7, 2, 40, 40, 0, 54, 0))
FRONT2_CASES = FRONT_CASES + tuple((level, 2, 20, 7, 1, 1000, 0) for level in (1, 2, 3, 4, 6))
LAYER2_CASES = FRONT2_CASES + ((0,3,20,7,1,1000,0),(0,1,20,7,1,1000,0),(2,0,20,7,1,1000,0))
RESIZE_CASES = ((6, 0), (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0),
                (6, 1), (6, 2), (6, 3), (-1, 0), (7, 0), (6, 0))
GAUSSIAN_CASES = ((7, 0), (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0),
                  (7, 1), (7, 2), (7, 3), (-1, 0), (8, 0), (7, 0))
POISON = bytes.fromhex('f00f5a6aefbeadde')
PORT_BYTES = 960 * 720


def pixels(level, pattern, front=False):
    w, h = WIDTHS[level], HEIGHTS[level]
    y, x = np.indices((h, w), dtype=np.int64)
    if front:
        if pattern == 3:
            return np.full((h,w),255,dtype=np.uint8)
        if pattern == 1:
            return np.zeros((h, w), dtype=np.uint8)
        if pattern == 0:
            checker = np.where((x // 5 + y // 7) & 1, 91, 13)
            return ((x * 17 + y * 29 + checker + (x * y) % 67) & 255).astype(np.uint8)
        state = 0x94a00103 + level
    else:
        if pattern == 1:
            return np.zeros((h, w), dtype=np.uint8)
        if pattern == 2:
            return np.full((h, w), 255, dtype=np.uint8)
        if pattern == 0:
            return ((x * 37 + y * 53 + x * y * 3 + level * 19 + 17) & 255).astype(np.uint8)
        state = 0x193ad501 + level
    values = bytearray(w * h)
    for i in range(w * h):
        state = (state * 1664525 + 1013904223) & 0xffffffff
        values[i] = state >> 24
    return np.frombuffer(values, dtype=np.uint8).reshape(h, w)


def packed_image(active, output=False):
    result = bytearray(POISON * (PORT_BYTES // 8))
    data = active.tobytes() if active is not None else b''
    if output:
        result[:(len(data) + 7) // 8 * 8] = bytes((len(data) + 7) // 8 * 8)
    result[:len(data)] = data
    return bytes(result)


def axis(src, dst):
    n = (2 * np.arange(dst, dtype=np.int64) + 1) * src - dst
    d = 2 * dst
    a, r = n // d, n % d
    q, f = (r * 2048) // d, (r * 2048) % d
    weight = q + ((f > d - f) | ((f == d - f) & ((q & 1) != 0)))
    outside = (a < 0) | (a >= src - 1)
    return np.clip(a, 0, src - 1), np.clip(a + 1, 0, src - 1), np.where(outside, 0, weight)


def resize(image, level):
    xa, xb, wx = axis(WIDTHS[level], WIDTHS[level + 1])
    ya, yb, wy = axis(HEIGHTS[level], HEIGHTS[level + 1])
    raw = image.astype(np.int64)
    top = raw[ya[:, None], xa] * (2048 - wx) + raw[ya[:, None], xb] * wx
    bottom = raw[yb[:, None], xa] * (2048 - wx) + raw[yb[:, None], xb] * wx
    value = (((top >> 4) * (2048 - wy[:, None])) >> 16) + (((bottom >> 4) * wy[:, None]) >> 16)
    return ((value + 2) >> 2).astype(np.uint8)


def gaussian(image):
    h, w = image.shape
    taps = (18, 34, 48, 56, 48, 34, 18)
    extended = np.pad(image.astype(np.uint32), ((0, 0), (3, 3)), mode='reflect')
    horizontal = sum(t * extended[:, k:k + w] for k, t in enumerate(taps))
    extended = np.pad(horizontal, ((3, 3), (0, 0)), mode='reflect')
    vertical = sum(t * extended[k:k + h, :] for k, t in enumerate(taps))
    return ((vertical + 32768) >> 16).astype(np.uint8)


def fast_scores(image):
    h, w = image.shape
    raw = image.astype(np.int16)
    center = raw[3:h - 3, 3:w - 3]
    offsets = ((0, 3), (1, 3), (2, 2), (3, 1), (3, 0), (3, -1), (2, -2), (1, -3),
               (0, -3), (-1, -3), (-2, -2), (-3, -1), (-3, 0), (-3, 1), (-2, 2), (-1, 3))
    differences = [raw[3 + dy:h - 3 + dy, 3 + dx:w - 3 + dx] - center for dx, dy in offsets]
    best = np.zeros(center.shape, dtype=np.int16)
    for start in range(16):
        arc = [differences[(start + k) % 16] for k in range(9)]
        best = np.maximum(best, np.maximum(np.minimum.reduce(arc), -np.maximum.reduce(arc)))
    result = np.zeros(image.shape, dtype=np.uint8)
    result[3:h - 3, 3:w - 3] = np.maximum(0, best - 1).astype(np.uint8)
    return result


def front(image, test):
    level, _, high, low, dual, capacity, delta = test
    summary = [0x20000] + [0] * 15
    if delta:
        summary[1] = 1
        return summary, []
    w, h, budget = WIDTHS[level] - 32, HEIGHTS[level] - 32, BUDGETS[level]
    cols, rows = max(1, w // 35), max(1, h // 35)
    tw, th = (w + cols - 1) // cols, (h + rows - 1) // rows
    scores = fast_scores(image)
    candidates = []
    for ty in range(rows):
        for tx in range(cols):
            ix, iy = 16 + tx * tw, 16 + ty * th
            mx, my = min(ix + tw + 6, image.shape[1] - 16), min(iy + th + 6, image.shape[0] - 16)
            if iy >= image.shape[0] - 19 or ix >= image.shape[1] - 22:
                continue
            tile = scores[iy + 3:my - 3, ix + 3:mx - 3]
            padded = np.pad(tile, 1)
            keep = tile >= (low if dual else high)
            for dy in range(3):
                for dx in range(3):
                    if (dx, dy) != (1, 1):
                        keep &= tile > padded[dy:dy + tile.shape[0], dx:dx + tile.shape[1]]
            yy, xx = np.nonzero(keep)
            candidates.extend((int(x + ix - 13), int(y + iy - 13), int(tile[y, x]), ty * cols + tx)
                              for y, x in zip(yy, xx))
    side = max(1, isqrt(w * h // budget))
    cc, cr = max(1, w // side), max(1, h // side)
    cells = [[] for _ in range(cc * cr)]
    for point in candidates:
        x, y, _, _ = point
        cells[min(y // side, cr - 1) * cc + min(x // side, cc - 1)].append(point)
    winners, empty, fallback = [], 0, 0
    for cell in cells:
        if not cell:
            empty += 1
            continue
        winner = min(cell, key=lambda p: (-p[2], p[1], p[0]))
        fallback += bool(dual and winner[2] < high)
        winners.append(winner)
    if len(winners) > budget:
        winners.sort(key=lambda p: (-p[2], p[1], p[0]))
        winners = winners[:budget]
    summary[2:13] = [len(candidates), len(winners), side, cc, cr, empty, fallback, cols, rows, tw, th]
    if len(winners) > capacity:
        summary[1] = 4
        winners = []
    return summary, winners
