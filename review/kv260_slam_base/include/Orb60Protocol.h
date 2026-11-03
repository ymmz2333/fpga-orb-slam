#ifndef ORB60_PROTOCOL_H
#define ORB60_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#define ORB60_WIDTH 960u
#define ORB60_HEIGHT 720u
#define ORB60_CAPACITY 1000u
#define ORB60_IMAGE_BYTES (ORB60_WIDTH * ORB60_HEIGHT)
#define ORB60_HEADER_BYTES 64u
#define ORB60_META_BYTES 128u
#define ORB60_STATS_BYTES 1024u
#define ORB60_RESULT_MAX (ORB60_META_BYTES + ORB60_CAPACITY * 64u + ORB60_STATS_BYTES)
#define ORB60_FRAME 1u
#define ORB60_RESULT 2u
#define ORB60_SIMULATED 1u
static inline uint32_t orb_get32(const void *p) {
    const uint8_t *b = (const uint8_t *)p;
    return (uint32_t)b[0] | (uint32_t)b[1]<<8 | (uint32_t)b[2]<<16 | (uint32_t)b[3]<<24;
}
static inline uint64_t orb_get64(const void *p) {
    return (uint64_t)orb_get32(p) | (uint64_t)orb_get32((const uint8_t *)p+4)<<32;
}
static inline void orb_put32(void *p, uint32_t v) {
    uint8_t *b=(uint8_t *)p;
    for (unsigned i=0;i<4;++i) b[i]=(uint8_t)(v>>(8*i));
}
static inline void orb_put64(void *p, uint64_t v) {
    orb_put32(p,(uint32_t)v);orb_put32((uint8_t *)p+4,(uint32_t)(v>>32));
}
static inline uint32_t orb_crc32(const void *p, size_t n) {
    /* Slicing-by-8 avoids a bit-serial PS bottleneck for 691,200-byte frames.
       Each threaded adapter initializes this table before starting workers. */
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
    const uint8_t *b=(const uint8_t *)p;uint32_t c=~(uint32_t)0;
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
