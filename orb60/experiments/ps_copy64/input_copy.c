#include "input_copy.h"
#include <stdint.h>
#include <string.h>
/* Reserved DDR is still noncacheable. Aligned volatile integer64 stores become
   ARM STRD: no NEON accesses to Device memory and no cache attribute changes. */
void orb_copy_input(void *destination,const void *source,size_t bytes) {
    uint8_t *dst=destination;const uint8_t *src=source;
    if((uintptr_t)dst&7u){memcpy(dst,src,bytes);return;}
    while(bytes>=8) {
        uint64_t word;memcpy(&word,src,8);
        *(volatile uint64_t *)(void *)dst=word;dst+=8;src+=8;bytes-=8;
    }
    while(bytes--)*dst++=*src++;
}
