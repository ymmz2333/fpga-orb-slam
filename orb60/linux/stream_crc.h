#ifndef ORB60_STREAM_CRC_H
#define ORB60_STREAM_CRC_H
#include "protocol.h"
/* CRC of concatenated chunks; seed/finalization match zlib.crc32(data, seed).
   Initialized on the creating thread before starting the receiver. */
static inline uint32_t orb_stream_crc(uint32_t previous,const void *p,size_t n) {
    static uint32_t table[8][256];static int ready;
    if(!ready) {
        for(unsigned v=0;v<256;++v) {
            uint32_t x=v;for(unsigned i=0;i<8;++i)x=(x>>1)^((0u-(x&1u))&0xedb88320u);
            table[0][v]=x;
        }
        for(unsigned i=1;i<8;++i)for(unsigned v=0;v<256;++v) {
            uint32_t x=table[i-1][v];table[i][v]=(x>>8)^table[0][x&255u];
        }
        ready=1;
    }
    const uint8_t *b=(const uint8_t *)p;uint32_t c=~previous;
    while(n>=8) {
        uint32_t a=c^orb_get32(b),d=orb_get32(b+4);
        c=table[7][a&255u]^table[6][(a>>8)&255u]^table[5][(a>>16)&255u]^table[4][a>>24]
         ^table[3][d&255u]^table[2][(d>>8)&255u]^table[1][(d>>16)&255u]^table[0][d>>24];
        b+=8;n-=8;
    }
    while(n--)c=(c>>8)^table[0][(c^*b++)&255u];
    return ~c;
}
#endif
