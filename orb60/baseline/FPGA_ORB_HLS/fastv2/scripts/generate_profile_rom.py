"""Generate immutable fastv2 geometry and exact resize lookup tables."""

from pathlib import Path


WIDTHS = (960, 800, 667, 556, 463, 386, 322, 268)
HEIGHTS = (720, 600, 500, 417, 347, 289, 241, 201)
BUDGETS = (217, 181, 151, 126, 105, 87, 73, 60)


def round_even(value: int, divisor: int) -> int:
    """Return value/divisor rounded to nearest with ties to even."""
    quotient, remainder = divmod(value, divisor)
    if remainder > divisor - remainder or (
        remainder == divisor - remainder and quotient & 1
    ):
        quotient += 1
    return quotient


def resize_axis(target: int, source_size: int, destination_size: int) -> tuple[int, int, int]:
    """Return the exact v1.0 bilinear source pair and Q0.11 weight."""
    numerator = (2 * target + 1) * source_size - destination_size
    denominator = 2 * destination_size
    source_a = numerator // denominator
    remainder = numerator - source_a * denominator
    if source_a < 0:
        return 0, 0, 0
    if source_a >= source_size - 1:
        return source_size - 1, source_size - 1, 0
    return source_a, source_a + 1, round_even(remainder * 2048, denominator)


def profile_geometry(width: int, height: int, budget: int) -> tuple[int, ...]:
    """Return frozen effective, tile, and grid geometry for one level."""
    effective_width = width - 32
    effective_height = height - 32
    tile_cols = max(1, effective_width // 35)
    tile_rows = max(1, effective_height // 35)
    tile_width = (effective_width + tile_cols - 1) // tile_cols
    tile_height = (effective_height + tile_rows - 1) // tile_rows
    cell_side = max(1, int((effective_width * effective_height // budget) ** 0.5))
    while (cell_side + 1) ** 2 <= effective_width * effective_height // budget:
        cell_side += 1
    while cell_side**2 > effective_width * effective_height // budget:
        cell_side -= 1
    cell_cols = max(1, effective_width // cell_side)
    cell_rows = max(1, effective_height // cell_side)
    return (
        effective_width,
        effective_height,
        tile_cols,
        tile_rows,
        tile_width,
        tile_height,
        cell_side,
        cell_cols,
        cell_rows,
    )


def axis_info(size: int, effective_size: int, tile_count: int, tile_extent: int,
              cell_side: int, cell_count: int) -> list[int]:
    """Pack tile boundaries, tile index, and grid-cell index for one axis."""
    result: list[int] = []
    tile_index = 0
    tile_start = 3
    tile_end = min(3 + tile_extent, effective_size - 3)
    for source_coordinate in range(size):
        effective_coordinate = source_coordinate - 20
        if effective_coordinate >= tile_end and tile_index + 1 < tile_count:
            tile_index += 1
            tile_start += tile_extent
            tile_end = min(tile_end + tile_extent, effective_size - 3)
        cell_index = max(0, min(cell_count - 1, effective_coordinate // cell_side))
        packed = (
            (tile_start & 0x3FF)
            | ((tile_end & 0x3FF) << 10)
            | ((tile_index & 0x1F) << 20)
            | ((cell_index & 0x1F) << 25)
        )
        result.append(packed)
    return result


def format_array(values: list[int], formatter, per_line: int) -> str:
    """Format a deterministic comma-separated C++ initializer."""
    lines = []
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        lines.append("    " + ", ".join(formatter(value) for value in chunk) + ",")
    return "\n".join(lines)


def generate_header() -> str:
    """Build the complete generated C++ header text."""
    profiles = []
    x_offsets = []
    y_offsets = []
    x_info: list[int] = []
    y_info: list[int] = []
    for width, height, budget in zip(WIDTHS, HEIGHTS, BUDGETS):
        geometry = profile_geometry(width, height, budget)
        effective_width, effective_height = geometry[0], geometry[1]
        tile_cols, tile_rows, tile_width, tile_height = geometry[2:6]
        cell_side, cell_cols, cell_rows = geometry[6:9]
        x_offsets.append(len(x_info))
        y_offsets.append(len(y_info))
        x_info.extend(axis_info(
            width, effective_width, tile_cols, tile_width, cell_side, cell_cols))
        y_info.extend(axis_info(
            height, effective_height, tile_rows, tile_height, cell_side, cell_rows))
        profiles.append((width, height, budget, *geometry, x_offsets[-1], y_offsets[-1]))

    resize_x_offsets = []
    resize_y_offsets = []
    resize_x: list[int] = []
    resize_y: list[int] = []
    for level in range(7):
        resize_x_offsets.append(len(resize_x))
        resize_y_offsets.append(len(resize_y))
        for target in range(WIDTHS[level + 1]):
            source_a, source_b, weight = resize_axis(
                target, WIDTHS[level], WIDTHS[level + 1])
            resize_x.append(source_a | (source_b << 11) | (weight << 22))
        for target in range(HEIGHTS[level + 1]):
            source_a, source_b, weight = resize_axis(
                target, HEIGHTS[level], HEIGHTS[level + 1])
            resize_y.append(source_a | (source_b << 11) | (weight << 22))

    profile_lines = []
    for values in profiles:
        profile_lines.append("    {" + ", ".join(str(value) for value in values) + "},")

    return f"""#pragma once

// Generated by fastv2/scripts/generate_profile_rom.py. Do not edit manually.

#include <cstdint>

namespace fastv2_profile {{

/** Frozen geometry and ROM offsets for one 960x720 pyramid level. */
struct Profile {{
    int width;
    int height;
    int budget;
    int effective_width;
    int effective_height;
    int tile_cols;
    int tile_rows;
    int tile_width;
    int tile_height;
    int cell_side;
    int cell_cols;
    int cell_rows;
    int x_info_offset;
    int y_info_offset;
}};

static const Profile kProfiles[8] = {{
{chr(10).join(profile_lines)}
}};

static const uint32_t kAxisXInfo[{len(x_info)}] = {{
{format_array(x_info, lambda value: f'UINT32_C(0x{value:08x})', 6)}
}};

static const uint32_t kAxisYInfo[{len(y_info)}] = {{
{format_array(y_info, lambda value: f'UINT32_C(0x{value:08x})', 6)}
}};

static const int kResizeXOffsets[7] = {{{', '.join(map(str, resize_x_offsets))}}};
static const int kResizeYOffsets[7] = {{{', '.join(map(str, resize_y_offsets))}}};

static const uint64_t kResizeXAxis[{len(resize_x)}] = {{
{format_array(resize_x, lambda value: f'UINT64_C(0x{value:09x})', 5)}
}};

static const uint64_t kResizeYAxis[{len(resize_y)}] = {{
{format_array(resize_y, lambda value: f'UINT64_C(0x{value:09x})', 5)}
}};

}} // namespace fastv2_profile
"""


def main() -> None:
    """Write the generated header next to the public fastv2 interface."""
    script_path = Path(__file__).resolve()
    output_path = script_path.parent.parent / "include" / "fastv2_profile_rom.hpp"
    output_path.write_text(generate_header(), encoding="utf-8", newline="\n")
    print(f"generated {output_path}")


if __name__ == "__main__":
    main()
