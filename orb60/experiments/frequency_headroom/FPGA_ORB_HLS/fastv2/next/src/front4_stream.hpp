/* GPL-3.0-or-later: shared packed lines, four FAST lanes and lossless merge. */
#include "geometry4.hpp"
#include "merge4.hpp"
struct PixelQuad {uint32_t pixels;uint8_t count;};

void unpack_front4_words(hls::stream<uint64_t>& input,hls::stream<uint32_t>& output,int width,int height) {
#pragma HLS INLINE off
    uint64_t cached=0;int position=8;
    for(int y=0;y<height;++y) {
UnpackQuads:
        for(int x=0;x<width;x+=4) {
#pragma HLS PIPELINE II=1
            const int n=width-x<4?width-x:4;
            const uint64_t next=8-position<n?input.read():uint64_t(0);
            const uint64_t first=position==8?0:cached>>(position*8);
            const int available=8-position;
            uint64_t value=first;
            if(available<n) {
                value|=next<<(available*8);cached=next;position=n-available;
            } else position+=n;
            uint32_t quad=0;
            for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                if(lane<n) quad|=uint32_t(uint8_t(value>>(lane*8)))<<(lane*8);
            }
            output.write(quad);
        }
    }
}

template<int Lane> uint8_t front4_score(const uint8_t window[7][10]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=0
    uint8_t ring[16];
#pragma HLS ARRAY_PARTITION variable=ring complete
    ring[0]=window[6][3+Lane];ring[1]=window[6][4+Lane];
    ring[2]=window[5][5+Lane];ring[3]=window[4][6+Lane];
    ring[4]=window[3][6+Lane];ring[5]=window[2][6+Lane];
    ring[6]=window[1][5+Lane];ring[7]=window[0][4+Lane];
    ring[8]=window[0][3+Lane];ring[9]=window[0][2+Lane];
    ring[10]=window[1][1+Lane];ring[11]=window[2][Lane];
    ring[12]=window[3][Lane];ring[13]=window[4][Lane];
    ring[14]=window[5][1+Lane];ring[15]=window[6][2+Lane];
    return fast_score(window[3][3+Lane],ring);
}

void scan_front4_quads(hls::stream<uint32_t>& input,hls::stream<CandidateQuad>& output,
    const fastv2_profile::Profile& p,int high,int low,int dual) {
#pragma HLS INLINE off
    uint32_t pixels[7][240],scores[2][240];
#pragma HLS ARRAY_PARTITION variable=pixels complete dim=1
#pragma HLS ARRAY_PARTITION variable=scores complete dim=1
#pragma HLS ARRAY_PARTITION variable=fastv2_quad_rom::kXInfo complete dim=1
#pragma HLS BIND_STORAGE variable=pixels type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=scores type=ram_s2p impl=bram
    int count=0,level=find_profile(p.width,p.height,p.budget);
    int yc=fastv2_segment::kYRunOffsets[level];
    uint32_t yi=uint32_t(fastv2_segment::kYRunInfo[yc]),ynext=uint32_t(fastv2_segment::kYRunInfo[yc+1]);
    int ye=int(fastv2_segment::kYRunEnds[yc]),ynextend=int(fastv2_segment::kYRunEnds[yc+1]);
    for(int y=0;y<p.height;++y) {
        if(y>=ye) {yi=ynext;ye=ynextend;++yc;ynext=uint32_t(fastv2_segment::kYRunInfo[yc+1]);ynextend=int(fastv2_segment::kYRunEnds[yc+1]);}
        int xc=fastv2_quad_rom::kXOffsets[level],xe=int(fastv2_quad_rom::kXEnds[xc]),xnextend=int(fastv2_quad_rom::kXEnds[xc+1]);
        uint32_t xi[4],xnext[4];uint8_t window[7][10]={},nms[3][6]={};
#pragma HLS ARRAY_PARTITION variable=xi complete
#pragma HLS ARRAY_PARTITION variable=xnext complete
#pragma HLS ARRAY_PARTITION variable=window complete dim=0
#pragma HLS ARRAY_PARTITION variable=nms complete dim=0
        for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
            xi[lane]=uint32_t(fastv2_quad_rom::kXInfo[lane][xc]);xnext[lane]=uint32_t(fastv2_quad_rom::kXInfo[lane][xc+1]);
        }
RasterQuads:
        for(int x=0;x<p.width;x+=4) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_FLATTEN off
            const uint32_t raw=input.read();
            if(x/4>=xe) {
                xe=xnextend;++xc;xnextend=int(fastv2_quad_rom::kXEnds[xc+1]);
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    xi[lane]=xnext[lane];xnext[lane]=uint32_t(fastv2_quad_rom::kXInfo[lane][xc+1]);
                }
            }
            uint32_t column[7];
#pragma HLS ARRAY_PARTITION variable=column complete
            for(int r=0;r<6;++r) {
#pragma HLS UNROLL
                column[r]=y>=6-r?pixels[r+1][x/4]:uint32_t(0);pixels[r][x/4]=column[r];
            }
            column[6]=raw;pixels[6][x/4]=raw;
            for(int r=0;r<7;++r) {
#pragma HLS UNROLL
                for(int c=0;c<6;++c) {
#pragma HLS UNROLL
                    window[r][c]=window[r][c+4];
                }
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    window[r][6+lane]=uint8_t(column[r]>>(8*lane));
                }
            }
            if(y<6) continue;
            const uint8_t s[4]={x>=6?front4_score<0>(window):uint8_t(0),
                x+1>=6 && x+1<p.width?front4_score<1>(window):uint8_t(0),
                x+2>=6 && x+2<p.width?front4_score<2>(window):uint8_t(0),
                x+3>=6 && x+3<p.width?front4_score<3>(window):uint8_t(0)};
#pragma HLS ARRAY_PARTITION variable=s complete
            const uint32_t current=uint32_t(s[0])|(uint32_t(s[1])<<8)|(uint32_t(s[2])<<16)|(uint32_t(s[3])<<24);
            const int sy=y-6;
            const uint32_t old2=sy>=2?scores[0][x/4]:uint32_t(0),old1=sy>=1?scores[1][x/4]:uint32_t(0);
            scores[0][x/4]=old1;scores[1][x/4]=current;
            const uint32_t values[3]={old2,old1,current};
#pragma HLS ARRAY_PARTITION variable=values complete
            for(int r=0;r<3;++r) {
#pragma HLS UNROLL
                nms[r][0]=nms[r][4];nms[r][1]=nms[r][5];
                for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                    nms[r][lane+2]=uint8_t(values[r]>>(8*lane));
                }
            }
            if(sy<2) continue;
            CandidateQuad quad={};int valid_count=0;
#pragma HLS ARRAY_PARTITION variable=quad.words complete
            for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                const int ex=x+lane-20,ey=y-20,response=nms[1][lane+1];
                const int xs=int(xi[lane]&1023u),xt=int((xi[lane]>>10)&1023u),ys=int(yi&1023u),yt=int((yi>>10)&1023u);
                bool keep=x+lane<p.width && ex>=3 && ex<p.effective_width-3 && ey>=3 && ey<p.effective_height-3 && response>=(dual?low:high);
                for(int dy=-1;dy<=1;++dy) {
#pragma HLS UNROLL
                    for(int dx=-1;dx<=1;++dx) {
#pragma HLS UNROLL
                        if(dx || dy) {
                            const int other=ex+dx>=xs && ex+dx<xt && ey+dy>=ys && ey+dy<yt?nms[dy+1][dx+lane+1]:0;
                            if(other>=response) keep=false;
                        }
                    }
                }
                const int cell=int((yi>>25)&31u)*p.cell_cols+int((xi[lane]>>25)&31u);
                const Point point={ex,ey,response,int((yi>>20)&31u)*p.tile_cols+int((xi[lane]>>20)&31u)};
                quad.words[lane]=pack_point(point)|(uint64_t(cell)<<41);
                quad.mask|=uint8_t(keep)<<lane;valid_count+=int(keep);
            }
            if(quad.mask) output.write(quad);count+=valid_count;
        }
    }
    CandidateQuad end={};end.words[0]=(UINT64_C(1)<<63)|uint64_t(unsigned(count));output.write(end);
}

void serialize_front4_quads(hls::stream<CandidateQuad>& input,hls::stream<uint64_t>& output) {
#pragma HLS INLINE off
    uint64_t words[4];uint8_t remaining=0;
#pragma HLS ARRAY_PARTITION variable=words complete
MergeQuads:
    for(;;) {
#pragma HLS PIPELINE II=1
        if(!remaining) {
            const CandidateQuad quad=input.read();
            if(quad.words[0]>>63) {output.write(quad.words[0]);break;}
            for(int lane=0;lane<4;++lane) {
#pragma HLS UNROLL
                words[lane]=quad.words[lane];
            }
            remaining=quad.mask;
        }
        if(remaining) {
            const int lane=(remaining&1)?0:(remaining&2)?1:(remaining&4)?2:3;
            output.write(words[lane]);remaining&=uint8_t(~(1u<<lane));
        }
    }
}
