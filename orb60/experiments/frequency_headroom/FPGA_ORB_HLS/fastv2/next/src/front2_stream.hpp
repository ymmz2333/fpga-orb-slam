#pragma once

struct CandidatePair2 { uint64_t first, second; uint8_t mask; };

void read_front2_words(const uint64_t* image, hls::stream<uint64_t>& words, int pixels) {
#pragma HLS INLINE off
    uint64_t block[64];
    const int count = (pixels + 7) / 8;
    for (int base = 0; base < count; base += 64) {
        const int n = count - base < 64 ? count - base : 64;
        std::memcpy(block, image + base, size_t(unsigned(n) & 0x7fu) * 8);
        for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
            words.write(block[i]);
        }
    }
}

/** One FIFO read at most per pair, including an odd row crossing a word edge. */
void unpack_front2_words(hls::stream<uint64_t>& words, hls::stream<uint16_t>& pixels,
                         int width, int height) {
#pragma HLS INLINE off
    uint64_t cached = 0;
    int position = 8;
    for (int y = 0; y < height; ++y) {
    UnpackPairs:
        for (int x = 0; x < width; x += 2) {
#pragma HLS PIPELINE II=1
            const int n = x + 1 < width ? 2 : 1;
            uint64_t next = 0;
            if (8 - position < n) next = words.read();
            uint8_t a, b = 0;
            if (position == 8) {
                a = uint8_t(next);
                if (n == 2) b = uint8_t(next >> 8);
                cached = next; position = n;
            } else if (position == 7 && n == 2) {
                a = uint8_t(cached >> 56); b = uint8_t(next);
                cached = next; position = 1;
            } else {
                const uint64_t shifted = cached >> (8 * position);
                a = uint8_t(shifted);
                if (n == 2) b = uint8_t(shifted >> 8);
                position += n;
            }
            pixels.write(uint16_t(a) | (uint16_t(b) << 8));
        }
    }
}

template <int Lane> uint8_t front2_score(const uint8_t window[7][8]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=2
    uint8_t ring[16];
#pragma HLS ARRAY_PARTITION variable=ring complete dim=1
    ring[0]=window[6][3+Lane]; ring[1]=window[6][4+Lane];
    ring[2]=window[5][5+Lane]; ring[3]=window[4][6+Lane];
    ring[4]=window[3][6+Lane]; ring[5]=window[2][6+Lane];
    ring[6]=window[1][5+Lane]; ring[7]=window[0][4+Lane];
    ring[8]=window[0][3+Lane]; ring[9]=window[0][2+Lane];
    ring[10]=window[1][1+Lane]; ring[11]=window[2][Lane];
    ring[12]=window[3][Lane]; ring[13]=window[4][Lane];
    ring[14]=window[5][1+Lane]; ring[15]=window[6][2+Lane];
    return fast_score(window[3][3+Lane], ring);
}

/** Packed 16-bit lines retain two adjacent pixels without doubling BRAM banks. */
void scan_front2_pairs(hls::stream<uint16_t>& input, hls::stream<CandidatePair2>& output,
    const fastv2_profile::Profile& p, int pair_offset, int high, int low, int dual) {
#pragma HLS INLINE off
    uint16_t pixel_lines[7][480], score_lines[2][480];
#pragma HLS ARRAY_PARTITION variable=pixel_lines complete dim=1
#pragma HLS ARRAY_PARTITION variable=score_lines complete dim=1
#pragma HLS BIND_STORAGE variable=pixel_lines type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=score_lines type=ram_s2p impl=bram
    int count = 0;
    const int level=find_profile(p.width,p.height,p.budget);
    int y_cursor=fastv2_segment::kYRunOffsets[level];
    uint32_t yi=uint32_t(fastv2_segment::kYRunInfo[y_cursor]);
    int y_end=int(fastv2_segment::kYRunEnds[y_cursor]);
    uint32_t y_next=uint32_t(fastv2_segment::kYRunInfo[y_cursor+1]);
    int y_next_end=int(fastv2_segment::kYRunEnds[y_cursor+1]);
    for (int y = 0; y < p.height; ++y) {
        if (y>=y_end) {
            yi=y_next; y_end=y_next_end; ++y_cursor;
            y_next=uint32_t(fastv2_segment::kYRunInfo[y_cursor+1]);
            y_next_end=int(fastv2_segment::kYRunEnds[y_cursor+1]);
        }
        int x_cursor=pair_offset;
        uint64_t geometry=uint64_t(fastv2_segment::kPairRunInfo[x_cursor]);
        int x_end=int(fastv2_segment::kPairRunEnds[x_cursor]);
        uint64_t x_next=uint64_t(fastv2_segment::kPairRunInfo[x_cursor+1]);
        int x_next_end=int(fastv2_segment::kPairRunEnds[x_cursor+1]);
        const int ys = int(yi & 1023u), ye = int((yi >> 10) & 1023u);
        uint8_t window[7][8], nms[3][4];
#pragma HLS ARRAY_PARTITION variable=window complete dim=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=2
#pragma HLS ARRAY_PARTITION variable=nms complete dim=1
#pragma HLS ARRAY_PARTITION variable=nms complete dim=2
        for (int r = 0; r < 7; ++r) {
#pragma HLS UNROLL
            for (int c = 0; c < 8; ++c) {
#pragma HLS UNROLL
                window[r][c] = 0;
            }
        }
        for (int r = 0; r < 3; ++r) {
#pragma HLS UNROLL
            for (int c = 0; c < 4; ++c) {
#pragma HLS UNROLL
                nms[r][c] = 0;
            }
        }
    RasterPairs:
        for (int x = 0; x < p.width; x += 2) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint16_t raw = input.read();
            if (x/2>=x_end) {
                geometry=x_next; x_end=x_next_end; ++x_cursor;
                x_next=uint64_t(fastv2_segment::kPairRunInfo[x_cursor+1]);
                x_next_end=int(fastv2_segment::kPairRunEnds[x_cursor+1]);
            }
            uint16_t column[7];
#pragma HLS ARRAY_PARTITION variable=column complete dim=1
            for (int r = 0; r < 6; ++r) {
#pragma HLS UNROLL
                column[r] = y >= 6-r ? pixel_lines[r+1][x/2] : uint16_t(0);
                pixel_lines[r][x/2] = column[r];
            }
            column[6] = raw; pixel_lines[6][x/2] = raw;
            for (int r = 0; r < 7; ++r) {
#pragma HLS UNROLL
                for (int c = 0; c < 6; ++c) {
#pragma HLS UNROLL
                    window[r][c] = window[r][c+2];
                }
                window[r][6] = uint8_t(column[r]);
                window[r][7] = uint8_t(column[r] >> 8);
            }
            if (y < 6 || x < 6) continue;
            const uint8_t s0 = front2_score<0>(window);
            const uint8_t s1 = x+1 < p.width ? front2_score<1>(window) : uint8_t(0);
            const int sy = y-6, sx = (x-6)/2;
            const uint16_t old2 = sy >= 2 ? score_lines[0][sx] : uint16_t(0);
            const uint16_t old1 = sy >= 1 ? score_lines[1][sx] : uint16_t(0);
            score_lines[0][sx] = old1;
            score_lines[1][sx] = uint16_t(s0) | (uint16_t(s1) << 8);
            uint16_t values[3] = {old2, old1, uint16_t(uint16_t(s0) | (uint16_t(s1) << 8))};
#pragma HLS ARRAY_PARTITION variable=values complete dim=1
            for (int r = 0; r < 3; ++r) {
#pragma HLS UNROLL
                nms[r][0] = nms[r][2]; nms[r][1] = nms[r][3];
                nms[r][2] = uint8_t(values[r]); nms[r][3] = uint8_t(values[r] >> 8);
            }
            if (x < 8 || sy < 2) continue;
            CandidatePair2 pair = {0, 0, 0};
            uint64_t tokens[2] = {0, 0};
            bool valid[2] = {false, false};
#pragma HLS ARRAY_PARTITION variable=tokens complete dim=1
#pragma HLS ARRAY_PARTITION variable=valid complete dim=1
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                const int ex = x+lane-20, ey = y-20;
                const uint32_t xi = uint32_t((geometry >> (30*lane)) & UINT64_C(0x3fffffff));
                const int xs = int(xi & 1023u), xe = int((xi >> 10) & 1023u);
                const int response = nms[1][1+lane];
                bool keep = x+lane < p.width && ex >= 3 && ex < p.effective_width-3 &&
                    ey >= 3 && ey < p.effective_height-3 && response >= (dual ? low : high);
                for (int dy = -1; dy <= 1; ++dy) {
#pragma HLS UNROLL
                    for (int dx = -1; dx <= 1; ++dx) {
#pragma HLS UNROLL
                        if (dx == 0 && dy == 0) continue;
                        const int neighbour = ex+dx >= xs && ex+dx < xe && ey+dy >= ys && ey+dy < ye
                            ? nms[dy+1][dx+1+lane] : 0;
                        if (neighbour >= response) keep = false;
                    }
                }
                const int cell = int((yi >> 25) & 31u) * p.cell_cols + int((xi >> 25) & 31u);
                const Point point = {ex, ey, response, int((yi >> 20) & 31u)*p.tile_cols+int((xi >> 20) & 31u)};
                tokens[lane] = pack_point(point) | (uint64_t(cell) << 41);
                valid[lane] = keep;
            }
            pair.first = tokens[0]; pair.second = tokens[1];
            pair.mask = uint8_t(valid[0]) | (uint8_t(valid[1]) << 1);
            if (pair.mask != 0) output.write(pair);
            count += int(valid[0]) + int(valid[1]);
        }
    }
    const CandidatePair2 end = {(UINT64_C(1) << 63) | uint64_t(unsigned(count)), 0, 0};
    output.write(end);
}

/** Lossless raster merge: a double-valid pair reserves the following cycle. */
void serialize_front2_pairs(hls::stream<CandidatePair2>& pairs, hls::stream<uint64_t>& tokens) {
#pragma HLS INLINE off
    bool second_pending = false;
    uint64_t second = 0;
MergePairs:
    for (;;) {
#pragma HLS PIPELINE II=1
        if (second_pending) {
            tokens.write(second); second_pending = false;
        } else {
            const CandidatePair2 pair = pairs.read();
            if ((pair.first >> 63) != 0) {tokens.write(pair.first); break;}
            if (pair.mask & 1) tokens.write(pair.first);
            else if (pair.mask & 2) tokens.write(pair.second);
            if (pair.mask == 3) {second = pair.second; second_pending = true;}
        }
    }
}

void front2_dataflow(const uint64_t* image, uint64_t* selected, uint64_t* result,
    const fastv2_profile::Profile& p, int pair_offset, int high, int low, int dual,
    int capacity, hls::stream<uint8_t>& completion) {
#pragma HLS INLINE off
    hls::stream<uint64_t> words, candidates;
    hls::stream<uint16_t> pixels;
    hls::stream<CandidatePair2> pairs;
#pragma HLS STREAM variable=words depth=128
#pragma HLS STREAM variable=pixels depth=64
#pragma HLS STREAM variable=pairs depth=64
#pragma HLS STREAM variable=candidates depth=128
#pragma HLS AGGREGATE variable=pairs compact=bit
#pragma HLS BIND_STORAGE variable=words type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=pixels type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=pairs type=fifo impl=bram
#pragma HLS DATAFLOW
    read_front2_words(image, words, p.width*p.height);
    unpack_front2_words(words, pixels, p.width, p.height);
    scan_front2_pairs(pixels, pairs, p, pair_offset, high, low, dual);
    serialize_front2_pairs(pairs, candidates);
    consume_and_select(candidates, selected, result, p, high, dual, capacity, completion);
}
