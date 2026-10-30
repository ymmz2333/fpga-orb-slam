#pragma once

template <typename T> uint32_t layer_gaussian_sum(const T a[7]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=a complete dim=1
    return ((uint32_t(a[0])+uint32_t(a[6]))*18u +
            (uint32_t(a[1])+uint32_t(a[5]))*34u) +
           ((uint32_t(a[2])+uint32_t(a[4]))*48u + uint32_t(a[3])*56u);
}

int layer_reflect(int x, int size) {
#pragma HLS INLINE
    return x < 0 ? -x : x >= size ? 2*size-x-2 : x;
}

/** Odd-position virtual pairs align two adjacent seven-tap output windows. */
void gaussian2_horizontal(hls::stream<uint16_t>& input, hls::stream<uint32_t>& output,
                          int width, int height) {
#pragma HLS INLINE off
    for (int y=0; y<height; ++y) {
        uint8_t head[6], tail[6], window[8] = {};
#pragma HLS ARRAY_PARTITION variable=head complete dim=1
#pragma HLS ARRAY_PARTITION variable=tail complete dim=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=1
        for (int pair=0; pair<3; ++pair) {
#pragma HLS PIPELINE II=1
            const uint16_t raw=input.read();
            head[2*pair]=uint8_t(raw); head[2*pair+1]=uint8_t(raw>>8);
            tail[2*pair]=uint8_t(raw); tail[2*pair+1]=uint8_t(raw>>8);
        }
        uint8_t carry=0;
    HorizontalGaussianPairs:
        for (int scan=-3; scan<width+3; scan+=2) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            uint8_t a, b;
            if (scan<0) a=head[-scan];
            else if (scan<6) a=head[scan];
            else if (scan<width) a=carry;
            else a=tail[layer_reflect(scan,width)-(width-6)];
            const int next=scan+1;
            if (next<0) b=head[-next];
            else if (next<6) b=head[next];
            else if (next<width) {
                const uint16_t raw=input.read();
                b=uint8_t(raw); carry=uint8_t(raw>>8);
                if (next+1<width) {
                    for (int i=0; i<4; ++i) {
#pragma HLS UNROLL
                        tail[i]=tail[i+2];
                    }
                    tail[4]=b; tail[5]=carry;
                } else {
                    for (int i=0; i<5; ++i) {
#pragma HLS UNROLL
                        tail[i]=tail[i+1];
                    }
                    tail[5]=b;
                }
            } else b=tail[layer_reflect(next,width)-(width-6)];
            for (int i=0; i<6; ++i) {
#pragma HLS UNROLL
                window[i]=window[i+2];
            }
            window[6]=a; window[7]=b;
            if (scan>=3) {
                uint8_t s[2][7];
#pragma HLS ARRAY_PARTITION variable=s complete dim=0
                for (int lane=0; lane<2; ++lane) {
#pragma HLS UNROLL
                    for (int tap=0; tap<7; ++tap) {
#pragma HLS UNROLL
                        s[lane][tap]=window[tap+lane];
                    }
                }
                const uint16_t low=uint16_t(layer_gaussian_sum(s[0]));
                const uint16_t high=scan-2<width ? uint16_t(layer_gaussian_sum(s[1])) : uint16_t(0);
                output.write(uint32_t(low)|(uint32_t(high)<<16));
            }
        }
    }
}

/** Two horizontal sums per word retain the same per-line bit capacity as 1PPC. */
void gaussian2_vertical(hls::stream<uint32_t>& input, hls::stream<uint16_t>& output,
                        int width, int height) {
#pragma HLS INLINE off
    uint32_t lines[7][480];
#pragma HLS ARRAY_PARTITION variable=lines complete dim=1
#pragma HLS BIND_STORAGE variable=lines type=ram_s2p impl=bram
    int slot=0;
    for (int sy=0; sy<height+3; ++sy) {
        uint8_t bank_of_tap[7];
#pragma HLS ARRAY_PARTITION variable=bank_of_tap complete dim=1
        for (int tap=0; tap<7; ++tap) {
#pragma HLS UNROLL
            const int delta=sy>=3 ? layer_reflect(sy+tap-6,height)-sy : 0;
            const int bank=slot+delta;
            bank_of_tap[tap]=uint8_t(bank<0 ? bank+7 : bank);
        }
    VerticalGaussianPairs:
        for (int x=0; x<width; x+=2) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint32_t incoming=sy<height ? input.read() : uint32_t(0);
            uint32_t column[7];
#pragma HLS ARRAY_PARTITION variable=column complete dim=1
            for (int bank=0; bank<7; ++bank) {
#pragma HLS UNROLL
                if (sy<height && bank==slot) {
                    column[bank]=incoming; lines[bank][x/2]=incoming;
                } else column[bank]=sy>=6 || bank<=sy ? lines[bank][x/2] : uint32_t(0);
            }
            if (sy>=3) {
                uint16_t samples[2][7];
#pragma HLS ARRAY_PARTITION variable=samples complete dim=0
                for (int lane=0; lane<2; ++lane) {
#pragma HLS UNROLL
                    for (int tap=0; tap<7; ++tap) {
#pragma HLS UNROLL
                        samples[lane][tap]=uint16_t(column[bank_of_tap[tap]]>>(16*lane));
                    }
                }
                const uint8_t a=uint8_t((layer_gaussian_sum(samples[0])+32768u)>>16);
                const uint8_t b=x+1<width ? uint8_t((layer_gaussian_sum(samples[1])+32768u)>>16) : uint8_t(0);
                output.write(uint16_t(a)|(uint16_t(b)<<8));
            }
        }
        slot=slot==6 ? 0 : slot+1;
    }
}

/** The fixed downscale uses adjacent source rows and at most six window columns.
 * One previous-row bank supplies two pixels each cycle, with explicit read-before
 * write. No random DDR access, duplicated row packet or dependency suppression.
 */
uint8_t layer_resize_pixel(const uint8_t top[6], const uint8_t bottom[6],
    uint32_t axis, int source_x, uint32_t wy) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=top complete dim=1
#pragma HLS ARRAY_PARTITION variable=bottom complete dim=1
    const int position=int(axis&1023u)-(source_x-4);
    const uint32_t wx=(axis>>10)&2047u;
#ifndef __SYNTHESIS__
    assert(position>=0 && position+1<6);
#endif
    const uint32_t a=uint32_t(top[position])*(2048-wx)+uint32_t(top[position+1])*wx;
    const uint32_t b=uint32_t(bottom[position])*(2048-wx)+uint32_t(bottom[position+1])*wx;
    const uint32_t value=((a>>4)*(2048-wy)>>16)+((b>>4)*wy>>16);
    return uint8_t((value+2)>>2);
}

void resize2_pairs(hls::stream<uint16_t>& input, hls::stream<uint16_t>& output,
                   int level, int width, int height, int destination_width, int destination_height) {
#pragma HLS INLINE off
    if (level==7) {
        for (int y=0; y<height; ++y) {
        DrainLastLevelPairs:
            for (int x=0; x<width; x+=2) {
#pragma HLS PIPELINE II=1
                input.read();
            }
        }
        return;
    }
    uint16_t previous[480];
#pragma HLS BIND_STORAGE variable=previous type=ram_s2p impl=bram
    int destination_y=0;
    for (int y=0; y<height; ++y) {
        const uint32_t vertical=destination_y<destination_height
            ? uint32_t(fastv2_profile::kResizeYAxis[fastv2_profile::kResizeYOffsets[level]+destination_y]) : 0;
        const int source_b=int(vertical&1023u)+1;
        const uint32_t wy=(vertical>>10)&2047u;
        const bool active=destination_y<destination_height && y==source_b;
        uint8_t top[6]={}, bottom[6]={};
#pragma HLS ARRAY_PARTITION variable=top complete dim=1
#pragma HLS ARRAY_PARTITION variable=bottom complete dim=1
    ResizeSourcePairs:
        for (int x=0; x<width; x+=2) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint16_t raw=input.read();
            const uint16_t above=y>0 ? previous[x/2] : uint16_t(0);
            previous[x/2]=raw;
            for (int i=0; i<4; ++i) {
#pragma HLS UNROLL
                top[i]=top[i+2]; bottom[i]=bottom[i+2];
            }
            top[4]=uint8_t(above); top[5]=uint8_t(above>>8);
            bottom[4]=uint8_t(raw); bottom[5]=uint8_t(raw>>8);
            const uint64_t emission=fastv2_layer_rom::kResizeEmit[fastv2_layer_rom::kResizeEmitOffsets[level]+x/2];
            if (active && (emission>>42)) {
                uint16_t pair=0;
                for (int lane=0; lane<2; ++lane) {
#pragma HLS UNROLL
                    const uint32_t axis=uint32_t((emission>>(21*lane))&UINT64_C(0x1fffff));
                    pair |= uint16_t(layer_resize_pixel(top,bottom,axis,x,wy))<<(8*lane);
                }
                output.write(pair);
            }
        }
        if (active) {
            if (destination_width&1) {
                // These two odd destination widths can require three output
                // pixels at the final source pair. Serialize the last single.
                output.write(uint16_t(layer_resize_pixel(top,bottom,
                    fastv2_layer_rom::kResizeTailAxis[level],(width-1)&~1,wy)));
            }
            ++destination_y;
        }
    }
#ifndef __SYNTHESIS__
    assert(destination_y==destination_height);
#endif
}

/** Flat image packer discards the second lane at every odd-width row end. */
template<int Tag> void layer_pack_pairs(hls::stream<uint16_t>& input,
    hls::stream<uint64_t>& output, int width, int height) {
#pragma HLS INLINE off
    uint64_t carry=0;
    int position=0;
    for (int y=0; y<height; ++y) {
    PackLayerPairs:
        for (int x=0; x<width; x+=2) {
#pragma HLS PIPELINE II=1
            const int n=x+1<width ? 2 : 1;
            const uint16_t raw=input.read();
            const uint16_t valid=n==2 ? raw : uint16_t(raw&255u);
            carry |= uint64_t(valid)<<(position*8);
            if (position+n>=8) {
                output.write(carry);
                carry=position==7 && n==2 ? uint64_t(raw>>8) : uint64_t(0);
                position=position+n-8;
            } else position+=n;
        }
    }
    if (position!=0) output.write(carry);
}

template<int Tag> void layer_write_words(hls::stream<uint64_t>& input,
    uint64_t* destination, int pixels, hls::stream<uint8_t>& done) {
#pragma HLS INLINE off
    uint64_t block[64];
#pragma HLS BIND_STORAGE variable=block type=ram_s2p impl=bram
    const int count=(pixels+7)/8;
    for (int base=0; base<count; base+=64) {
        const int n=count-base<64 ? count-base : 64;
    CollectLayerWords:
        for (int i=0; i<n; ++i) {
#pragma HLS PIPELINE II=1
            block[i]=input.read();
        }
        std::memcpy(destination+base,block,size_t(unsigned(n)&127u)*8);
    }
    done.write(1);
}
