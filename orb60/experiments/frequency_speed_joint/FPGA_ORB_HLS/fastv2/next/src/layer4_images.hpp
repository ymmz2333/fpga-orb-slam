/* GPL-3.0-or-later: four-lane exact separable Gaussian and integer Resize. */
#include "layer4_axis_rom.hpp"

void gaussian4_horizontal(hls::stream<uint32_t>& input,hls::stream<uint64_t>& output,int width,int height) {
#pragma HLS INLINE off
    for(int y=0;y<height;++y) {
        uint8_t head[8],tail[8],window[10]={};uint32_t cached=0;
#pragma HLS ARRAY_PARTITION variable=head complete
#pragma HLS ARRAY_PARTITION variable=tail complete
#pragma HLS ARRAY_PARTITION variable=window complete
        for(int q=0;q<2;++q) {
#pragma HLS PIPELINE II=1
            const uint32_t raw=input.read();
            for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                head[q*4+lane]=uint8_t(raw>>(8*lane));tail[q*4+lane]=head[q*4+lane];
            }
        }
HorizontalGaussianQuads:
        for(int scan=-5;scan<width+3;scan+=4) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const int base=(scan+3)&~3;
            const uint8_t carry=uint8_t(cached>>24);
            if(base>=8 && base<width) {
                cached=input.read();
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    if(base+lane<width) {
                        for(int j=0;j<7;++j) {
#pragma HLS UNROLL
                            tail[j]=tail[j+1];
                        }
                        tail[7]=uint8_t(cached>>(8*lane));
                    }
                }
            }
            for(int j=0;j<6;++j) {
#pragma HLS UNROLL
                window[j]=window[j+4];
            }
            for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                const int px=scan+lane;
                window[6+lane]=px<0?head[-px]:px<8?head[px]:px<width?
                    ((px&3)==3?carry:uint8_t(cached>>(8*(px&3)))):tail[layer_reflect(px,width)-(width-8)];
            }
            if(scan>=3) {
                uint64_t packed=0;
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    uint8_t taps[7];
#pragma HLS ARRAY_PARTITION variable=taps complete
                    for(int t=0;t<7;++t) {
#pragma HLS UNROLL
                        taps[t]=window[lane+t];
                    }
                    const uint16_t value=scan-3+lane<width?uint16_t(layer_gaussian_sum(taps)):uint16_t(0);
                    packed|=uint64_t(value)<<(16*lane);
                }
                output.write(packed);
            }
        }
    }
}

void gaussian4_vertical(hls::stream<uint64_t>& input,hls::stream<PixelQuad>& output,int width,int height) {
#pragma HLS INLINE off
    uint64_t lines[7][240];int slot=0;
#pragma HLS ARRAY_PARTITION variable=lines complete dim=1
#pragma HLS BIND_STORAGE variable=lines type=ram_s2p impl=bram
    for(int sy=0;sy<height+3;++sy) {
        uint8_t bank_of_tap[7];
#pragma HLS ARRAY_PARTITION variable=bank_of_tap complete
        for(int tap=0;tap<7;++tap) {
#pragma HLS UNROLL
            const int delta=sy>=3?layer_reflect(sy+tap-6,height)-sy:0;
            const int bank=slot+delta;bank_of_tap[tap]=uint8_t(bank<0?bank+7:bank);
        }
VerticalGaussianQuads:
        for(int x=0;x<width;x+=4) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint64_t incoming=sy<height?input.read():uint64_t(0);uint64_t column[7];
#pragma HLS ARRAY_PARTITION variable=column complete
            for(int bank=0;bank<7;++bank) {
#pragma HLS UNROLL
                if(sy<height && bank==slot) {column[bank]=incoming;lines[bank][x/4]=incoming;}
                else column[bank]=sy>=6 || bank<=sy?lines[bank][x/4]:uint64_t(0);
            }
            if(sy>=3) {
                PixelQuad quad={};quad.count=uint8_t(width-x<4?width-x:4);
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    uint16_t taps[7];
#pragma HLS ARRAY_PARTITION variable=taps complete
                    for(int tap=0;tap<7;++tap) {
#pragma HLS UNROLL
                        taps[tap]=uint16_t(column[bank_of_tap[tap]]>>(16*lane));
                    }
                    if(x+lane<width) quad.pixels|=uint32_t(uint8_t((layer_gaussian_sum(taps)+32768u)>>16))<<(8*lane);
                }
                output.write(quad);
            }
        }
        slot=slot==6?0:slot+1;
    }
}

uint8_t layer4_resize_pixel(const uint8_t top[8],const uint8_t bottom[8],uint32_t axis,uint32_t wy) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=top complete
#pragma HLS ARRAY_PARTITION variable=bottom complete
    const int index=int(axis&7u);const uint32_t wx=(axis>>3)&2047u;
    const uint32_t a=uint32_t(top[index])*(2048-wx)+uint32_t(top[index+1])*wx;
    const uint32_t b=uint32_t(bottom[index])*(2048-wx)+uint32_t(bottom[index+1])*wx;
    const uint32_t value=((a>>4)*(2048-wy)>>16)+((b>>4)*wy>>16);
    return uint8_t((value+2)>>2);
}

void resize4_quads(hls::stream<uint32_t>& input,hls::stream<PixelQuad>& output,
    int level,int width,int height,int destination_width,int destination_height) {
#pragma HLS INLINE off
    if(level==7) {
        for(int y=0;y<height;++y) {
DrainLastLevelQuads:
            for(int x=0;x<width;x+=4) {
#pragma HLS PIPELINE II=1
                input.read();
            }
        }
        return;
    }
    uint32_t previous[240];int destination_y=0;
#pragma HLS BIND_STORAGE variable=previous type=ram_s2p impl=bram
    for(int y=0;y<height;++y) {
        const uint32_t vertical=destination_y<destination_height?
            uint32_t(fastv2_profile::kResizeYAxis[fastv2_profile::kResizeYOffsets[level]+destination_y]):0;
        const uint32_t wy=(vertical>>10)&2047u;
        const bool active=destination_y<destination_height && y==int(vertical&1023u)+1;
        uint8_t top[8]={},bottom[8]={};int row_count=0;
#pragma HLS ARRAY_PARTITION variable=top complete
#pragma HLS ARRAY_PARTITION variable=bottom complete
ResizeSourceQuads:
        for(int x=0;x<width;x+=4) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint32_t raw=input.read(),above=y>0?previous[x/4]:uint32_t(0);previous[x/4]=raw;
            for(int j=0;j<4;++j) {
#pragma HLS UNROLL
                top[j]=top[j+4];bottom[j]=bottom[j+4];
                top[j+4]=uint8_t(above>>(8*j));bottom[j+4]=uint8_t(raw>>(8*j));
            }
            const uint64_t emission=uint64_t(fastv2_quad_rom::kResizeEmit[fastv2_quad_rom::kResizeOffsets[level]+x/4]);
            const uint8_t n=uint8_t(emission>>56);
            if(active && n) {
                PixelQuad quad={};quad.count=n;
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    if(lane<n) quad.pixels|=uint32_t(layer4_resize_pixel(top,bottom,uint32_t((emission>>(14*lane))&16383u),wy))<<(8*lane);
                }
                output.write(quad);row_count+=n;
            }
        }
        if(active) {
#ifndef __SYNTHESIS__
            assert(row_count==destination_width);
#endif
            ++destination_y;
        }
    }
#ifndef __SYNTHESIS__
    assert(destination_y==destination_height);
#endif
}

template<int Tag> void layer_pack_quads(hls::stream<PixelQuad>& input,hls::stream<uint64_t>& output,int width,int height) {
#pragma HLS INLINE off
    uint64_t carry=0;int position=0,consumed=0;
PackLayerQuads:
    while(consumed<width*height) {
#pragma HLS PIPELINE II=1
        const PixelQuad quad=input.read();const int n=quad.count;
#ifndef __SYNTHESIS__
        assert(n>=1 && n<=4 && consumed+n<=width*height);
#endif
        const uint32_t mask=n==4?UINT32_MAX:(UINT32_C(1)<<(8*n))-1;
        const uint64_t value=quad.pixels&mask;
        carry|=value<<(position*8);
        if(position+n>=8) {output.write(carry);carry=value>>((8-position)*8);position=position+n-8;}
        else position+=n;
        consumed+=n;
    }
    if(position) output.write(carry);
}
