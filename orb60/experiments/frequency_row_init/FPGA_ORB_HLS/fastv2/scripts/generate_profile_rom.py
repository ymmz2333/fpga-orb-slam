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
            assert source_b == source_a + 1 and 0 <= source_a < 1024 and 0 <= weight < 2048
            resize_x.append(source_a | (weight << 10))
        for target in range(HEIGHTS[level + 1]):
            source_a, source_b, weight = resize_axis(
                target, HEIGHTS[level], HEIGHTS[level + 1])
            assert source_b == source_a + 1 and 0 <= source_a < 1024 and 0 <= weight < 2048
            resize_y.append(source_a | (weight << 10))

    profile_lines = []
    for values in profiles:
        profile_lines.append("    {" + ", ".join(str(value) for value in values) + "},")

    return f"""#pragma once

// Generated by fastv2/scripts/generate_profile_rom.py. Do not edit manually.

#include <cstdint>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif

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

#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<21> ResizeCoordinate;
#else
typedef uint32_t ResizeCoordinate;
#endif
static const ResizeCoordinate kResizeXAxis[{len(resize_x)}] = {{
{format_array(resize_x, lambda value: f'UINT32_C(0x{value:06x})', 5)}
}};

static const ResizeCoordinate kResizeYAxis[{len(resize_y)}] = {{
{format_array(resize_y, lambda value: f'UINT32_C(0x{value:06x})', 5)}
}};

}} // namespace fastv2_profile
"""


def generate_pair_header() -> str:
    offsets, values = [], []
    for width, height, budget in zip(WIDTHS, HEIGHTS, BUDGETS):
        g = profile_geometry(width, height, budget)
        singles = axis_info(width, g[0], g[2], g[4], g[6], g[7])
        offsets.append(len(values))
        assert all(0 <= value < (1 << 30) for value in singles)
        for x in range(0, width, 2):
            values.append(singles[x] | ((singles[x + 1] if x + 1 < width else 0) << 30))
    return f'''#pragma once
// Generated paired geometry; preserves both original 30-bit axis records.
#include <cstdint>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif
namespace fastv2_profile2 {{
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<60> PairGeometry;
#else
typedef uint64_t PairGeometry;
#endif
static const int kPairOffsets[8] = {{{', '.join(map(str, offsets))}}};
static const PairGeometry kAxisXPairInfo[{len(values)}] = {{
{format_array(values, lambda value: f'UINT64_C(0x{value:015x})', 4)}
}};
}}
'''


def generate_resize_emit_header() -> str:
    """Schedule each output pair at its first fully available input pair.

    Each entry contains two exact 21-bit axes and a valid bit. Six consecutive
    samples suffice; no output counter/coordinate-ROM feedback is required.
    """
    offsets, entries, tails = [], [], []
    for level in range(7):
        sw, dw = WIDTHS[level], WIDTHS[level + 1]
        offsets.append(len(entries))
        pair = 0
        tail=resize_axis(dw-1,sw,dw) if dw&1 else (0,1,0)
        tails.append(tail[0] | (tail[2]<<10))
        if dw&1:
            last_x=2*((sw-1)//2)
            assert last_x-4 <= tail[0] < tail[1] <= sw-1
        for sx in range(0, sw, 2):
            packed = 0
            if pair < dw//2:
                a = resize_axis(2 * pair, sw, dw)
                b = resize_axis(2 * pair + 1, sw, dw)
                if b[1] <= min(sx + 1, sw - 1):
                    assert sx - 4 <= a[0] <= a[1] <= b[1] <= sx + 1
                    assert a[1] == a[0] + 1 and b[1] == b[0] + 1
                    packed = (a[0] | (a[2] << 10)) | ((b[0] | (b[2] << 10)) << 21) | (1 << 42)
                    pair += 1
                    if pair < dw//2:
                        following = resize_axis(2 * pair + 1, sw, dw)
                        assert following[1] > min(sx + 1, sw - 1)
            entries.append(packed)
        assert pair == dw//2
    return f'''#pragma once
// Generated source-pair schedule; no image data or runtime division.
#include <cstdint>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif
namespace fastv2_layer_rom {{
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<43> ResizeEmit;
#else
typedef uint64_t ResizeEmit;
#endif
static const int kResizeEmitOffsets[7] = {{{', '.join(map(str, offsets))}}};
static const uint32_t kResizeTailAxis[7] = {{{', '.join(map(str, tails))}}};
static const ResizeEmit kResizeEmit[{len(entries)}] = {{
{format_array(entries, lambda value: f'UINT64_C(0x{value:011x})', 4)}
}};
}}
'''


def consecutive_runs(values: list[int]) -> tuple[list[int], list[int]]:
    """Exclusive run ends; append a bounded lookahead sentinel per profile."""
    ends, records = [], []
    for index, value in enumerate(values):
        if not records or value != records[-1]:
            if records:
                ends.append(index)
            records.append(value)
    ends.append(len(values))
    # The final run is never advanced during a valid raster. One sentinel
    # makes the prefetched next record legal without a last-run branch.
    ends.append(1023)
    records.append(0)
    return ends, records


def generate_segment_header() -> str:
    """Lossless run tables for the exact paired X and single Y geometry."""
    x_offsets, y_offsets, x_ends, y_ends, x_info, y_info = [], [], [], [], [], []
    for width, height, budget in zip(WIDTHS, HEIGHTS, BUDGETS):
        g = profile_geometry(width, height, budget)
        xs = axis_info(width, g[0], g[2], g[4], g[6], g[7])
        ys = axis_info(height, g[1], g[3], g[5], g[6], g[8])
        pairs = [xs[x] | ((xs[x + 1] if x + 1 < width else 0) << 30)
                 for x in range(0, width, 2)]
        xe, xv = consecutive_runs(pairs)
        ye, yv = consecutive_runs(ys)
        x_offsets.append(len(x_info)); y_offsets.append(len(y_info))
        x_ends.extend(xe); x_info.extend(xv)
        y_ends.extend(ye); y_info.extend(yv)
    return f'''#pragma once
// Generated lossless geometry runs; ends are exclusive raster positions.
#include <cstdint>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif
namespace fastv2_segment {{
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<10> RunEnd;
typedef ap_uint<60> PairInfo;
typedef ap_uint<30> AxisInfo;
#else
typedef uint16_t RunEnd;
typedef uint64_t PairInfo;
typedef uint32_t AxisInfo;
#endif
static const int kPairRunOffsets[8] = {{{', '.join(map(str, x_offsets))}}};
static const int kYRunOffsets[8] = {{{', '.join(map(str, y_offsets))}}};
static const RunEnd kPairRunEnds[{len(x_ends)}] = {{
{format_array(x_ends, str, 16)}
}};
static const PairInfo kPairRunInfo[{len(x_info)}] = {{
{format_array(x_info, lambda v: f'UINT64_C(0x{v:015x})', 4)}
}};
static const RunEnd kYRunEnds[{len(y_ends)}] = {{
{format_array(y_ends, str, 16)}
}};
static const AxisInfo kYRunInfo[{len(y_info)}] = {{
{format_array(y_info, lambda v: f'UINT32_C(0x{v:08x})', 6)}
}};
}}
'''


def generate_quad_headers() -> tuple[str, str]:
    offsets, ends, records = [], [], []
    for w,h,budget in zip(WIDTHS,HEIGHTS,BUDGETS):
        g=profile_geometry(w,h,budget)
        xs=axis_info(w,g[0],g[2],g[4],g[6],g[7])
        values=[sum((xs[x+i] if x+i<w else 0)<<(30*i) for i in range(4)) for x in range(0,w,4)]
        e,v=consecutive_runs(values);offsets.append(len(records));ends.extend(e);records.extend(v)
    geometry='''#pragma once
// Generated exact four-lane geometry runs; end positions count source quads.
#include "geometry_runs.hpp"
namespace fastv2_quad_rom {
using fastv2_segment::AxisInfo;
using fastv2_segment::RunEnd;
'''
    geometry+=f'static const int kXOffsets[8] = {{{", ".join(map(str,offsets))}}};\n'
    geometry+=f'static const RunEnd kXEnds[{len(ends)}] = {{\n{format_array(ends,str,16)}\n}};\n'
    geometry+=f'static const AxisInfo kXInfo[4][{len(records)}] = {{\n'
    for lane in range(4):
        geometry+='{\n'+format_array([(r>>(lane*30))&((1<<30)-1) for r in records],lambda v:f'UINT32_C(0x{v:08x})',6)+'\n},\n'
    geometry+='};\n}\n'
    offsets,entries=[],[]
    for level in range(7):
        sw,dw=WIDTHS[level],WIDTHS[level+1];offsets.append(len(entries));target=0
        for x in range(0,sw,4):
            packed=0;n=0
            while target<dw:
                a,b,weight=resize_axis(target,sw,dw)
                if b>min(x+3,sw-1):break
                position=a-(x-4)
                assert n<4 and 0<=position<7 and b==a+1 and 0<=weight<2048
                packed|=(position|(weight<<3))<<(14*n)
                n+=1;target+=1
            entries.append(packed|(n<<56))
            assert n>0, 'Fixed downscale emits one nonempty variable-width packet per source quad'
        assert target==dw
    emit='''#pragma once
// Generated exact 4PPC emission: four relative 3-bit indices/11-bit weights,
// plus a 3-bit count. No runtime coordinate division or output feedback ROM.
#include <cstdint>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif
namespace fastv2_quad_rom {
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<59> ResizeQuadEmit;
#else
typedef uint64_t ResizeQuadEmit;
#endif
'''
    emit+=f'static const int kResizeOffsets[7] = {{{", ".join(map(str,offsets))}}};\n'
    emit+=f'static const ResizeQuadEmit kResizeEmit[{len(entries)}] = {{\n{format_array(entries,lambda v:f"UINT64_C(0x{v:015x})",4)}\n}};\n}}\n'
    return geometry,emit


def main() -> None:
    """Write the generated header next to the public fastv2 interface."""
    script_path = Path(__file__).resolve()
    output_path = script_path.parent.parent / "include" / "fastv2_profile_rom.hpp"
    output_path.write_text(generate_header(), encoding="utf-8", newline="\n")
    pair_path = script_path.parent.parent / 'next/include/front2_axis_rom.hpp'
    pair_path.write_text(generate_pair_header(), encoding='utf-8', newline='\n')
    emit_path = script_path.parent.parent / 'next/include/layer2_axis_rom.hpp'
    emit_path.write_text(generate_resize_emit_header(), encoding='utf-8', newline='\n')
    segment_path = script_path.parent.parent / 'next/include/geometry_runs.hpp'
    segment_path.write_text(generate_segment_header(), encoding='utf-8', newline='\n')
    quad_geometry,quad_resize=generate_quad_headers()
    (script_path.parent.parent/'next/include/geometry4.hpp').write_text(quad_geometry,encoding='utf-8',newline='\n')
    (script_path.parent.parent/'next/include/layer4_axis_rom.hpp').write_text(quad_resize,encoding='utf-8',newline='\n')
    print(f"generated {output_path}")


if __name__ == "__main__":
    main()
