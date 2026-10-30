#ifndef ORB60_ENGINE_H
#define ORB60_ENGINE_H
#include "protocol.h"
#define ORB60_DDR_BASE 0x20000000u
#define ORB60_DDR_SIZE 0x01000000u
struct orb_engine_profile {
    uint64_t copy_ns,core_ns,snapshot_ns;
    uint64_t image_start[8],desc_start[8],image_ns[8],desc_ns[8];
};
struct orb_engine {
    int fd;
    uint8_t *ddr;
    volatile uint32_t *regs[2];
    uint32_t (*read)(struct orb_engine *,unsigned,unsigned);
    void (*write)(struct orb_engine *,unsigned,unsigned,uint32_t);
    void *test_context;
    int profiling;
    unsigned frame_raw0_offset;
    struct orb_engine_profile profile;
};
int orb_engine_open(struct orb_engine *,const char *uio);
void orb_engine_close(struct orb_engine *);
/* Any failure after ap_start requires reloading/resetting the PL before reuse. */
int orb_engine_run(struct orb_engine *,const uint8_t *image,uint8_t *payload,
                   size_t *payload_bytes,uint32_t *count,unsigned timeout_ms);
/* Network staging slots are separate from all PL working/feature buffers. */
#define ORB60_RX_BASE 0x00800000u
#define ORB60_RX_STRIDE 0x00100000u
void orb_engine_publish_input(void);
int orb_engine_run_at(struct orb_engine *,unsigned input_offset,uint64_t copy_ns,
                      uint8_t *payload,size_t *payload_bytes,uint32_t *count,unsigned timeout_ms);
#endif
