#define _POSIX_C_SOURCE 200809L
#include "engine.h"
#include "orb60_registers.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static const unsigned widths[8]={960,800,667,556,463,386,322,268};
static const unsigned heights[8]={720,600,500,417,347,289,241,201};
static const unsigned budgets[8]={217,181,151,126,105,87,73,60};
/* Identical address ownership to the accepted shared-DDR RTL frame harness. */
static const unsigned raws[3]={0x100ff8,0x1b0ff8,0x260ff8};
static const unsigned blurs[2]={0x310ff8,0x3c0ff8};
enum {FEATURES=0x530ff8};
static unsigned points(unsigned l){return 0x470ff8+0x4000*l;}
static unsigned summary(unsigned l){return 0x500fc0+0x80*l;}
static unsigned layer_stats(unsigned l){return 0x510fc0+0x80*l;}
static unsigned desc_stats(unsigned l){return 0x520fc0+0x80*l;}
static uint64_t now_ns(void) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000ull+(unsigned long)t.tv_nsec;
}
static void barrier(void) {
#if defined(__arm__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __sync_synchronize();
#endif
}
void orb_engine_publish_input(void){barrier();}
static unsigned raw_for_level(struct orb_engine *e,unsigned l){return l?raws[l%3]:e->frame_raw0_offset;}
static uint32_t mmio_read(struct orb_engine *e,unsigned core,unsigned offset) {
    uint32_t value=e->regs[core][offset/4];barrier();return value;
}
static void mmio_write(struct orb_engine *e,unsigned core,unsigned offset,uint32_t value) {
    barrier();e->regs[core][offset/4]=value;barrier();
}
static int map_info(const char *device,unsigned map,const char *field,uint64_t *v) {
    const char *base=strrchr(device,'/');char path[256];
    snprintf(path,sizeof(path),"/sys/class/uio/%s/maps/map%u/%s",base?base+1:device,map,field);
    FILE *f=fopen(path,"r");if(!f)return -1;
    unsigned long long x;int ok=fscanf(f,"%llx",&x)==1;fclose(f);*v=x;return ok?0:-1;
}
int orb_engine_open(struct orb_engine *e,const char *device) {
    memset(e,0,sizeof(*e));e->fd=-1;
    const uint64_t addr[3]={0x43c00000u,0x43c10000u,ORB60_DDR_BASE};
    const uint64_t size[3]={65536,65536,ORB60_DDR_SIZE};
    for(unsigned i=0;i<3;++i) {
        uint64_t a=0,n=0,o=0;
        if(map_info(device,i,"addr",&a)||map_info(device,i,"size",&n)||map_info(device,i,"offset",&o)
           ||a!=addr[i]||n!=size[i]||o!=0) {errno=EINVAL;return -1;}
    }
    e->fd=open(device,O_RDWR|O_SYNC);if(e->fd<0)return -1;
    if(flock(e->fd,LOCK_EX|LOCK_NB)) {orb_engine_close(e);return -1;}
    for(unsigned i=0;i<3;++i) {
        void *p=mmap(NULL,(size_t)size[i],PROT_READ|PROT_WRITE,MAP_SHARED,e->fd,(off_t)i*sysconf(_SC_PAGESIZE));
        if(p==MAP_FAILED){orb_engine_close(e);return -1;}
        if(i<2)e->regs[i]=(volatile uint32_t *)p;else e->ddr=(uint8_t *)p;
    }
    e->read=mmio_read;e->write=mmio_write;
    return 0;
}
void orb_engine_close(struct orb_engine *e) {
    for(unsigned i=0;i<2;++i)if(e->regs[i])munmap((void *)e->regs[i],65536);
    if(e->ddr)munmap(e->ddr,ORB60_DDR_SIZE);
    if(e->fd>=0)close(e->fd);
    memset(e,0,sizeof(*e));e->fd=-1;
}
static void put(struct orb_engine *e,unsigned c,unsigned r,unsigned v){e->write(e,c,r,v);}
static unsigned get(struct orb_engine *e,unsigned c,unsigned r){return e->read(e,c,r);}
static void pointer(struct orb_engine *e,unsigned c,unsigned r,unsigned offset){put(e,c,r,ORB60_DDR_BASE+offset);}
static int launch_image(struct orb_engine *e,unsigned l) {
    if(!(get(e,0,L_AP_CTRL)&4u))return -1;
    pointer(e,0,L_IMAGE_R,raw_for_level(e,l));pointer(e,0,L_BLURRED,blurs[l%2]);
    pointer(e,0,L_RESIZED,raws[(l+1)%3]);pointer(e,0,L_SELECTED,points(l));
    pointer(e,0,L_RESULT,summary(l));pointer(e,0,L_STATS,layer_stats(l));
    put(e,0,L_LEVEL,l);put(e,0,L_BUDGET,budgets[l]);put(e,0,L_HIGH_THRESHOLD,20);
    put(e,0,L_LOW_THRESHOLD,7);put(e,0,L_DUAL_THRESHOLD,1);put(e,0,L_SELECTED_CAPACITY,ORB60_CAPACITY);
    put(e,0,L_AP_CTRL,1);if(e->profiling)e->profile.image_start[l]=now_ns();return 0;
}
static int finish_image(struct orb_engine *e,unsigned l,unsigned *count) {
    const uint8_t *s=e->ddr+summary(l),*t=e->ddr+layer_stats(l);
    barrier();unsigned n=orb_get32(s+12);
    if(get(e,0,L_AP_RETURN)!=0||orb_get32(s)!=0x20000||orb_get32(s+4)!=0||n>budgets[l]||n>256
       ||orb_get32(t)!=0x600003||orb_get32(t+4)!=0||orb_get32(t+8)!=l
       ||orb_get32(t+12)!=widths[l]||orb_get32(t+16)!=heights[l]
       ||orb_get32(t+20)!=((widths[l]*heights[l]+7)&~7u)
       ||orb_get32(t+24)!=orb_get32(t+20)||!orb_get32(t+44))return -1;
    *count=n;return 0;
}
static int launch_desc(struct orb_engine *e,unsigned l,unsigned count,unsigned offset) {
    if(count>256||offset+count>ORB60_CAPACITY||!(get(e,1,D_AP_CTRL)&4u))return -1;
    pointer(e,1,D_RAW,raw_for_level(e,l));pointer(e,1,D_BLURRED,blurs[l%2]);pointer(e,1,D_POINTS,points(l));
    pointer(e,1,D_FEATURES,FEATURES);pointer(e,1,D_STATS,desc_stats(l));
    put(e,1,D_WIDTH,widths[l]);put(e,1,D_HEIGHT,heights[l]);put(e,1,D_COUNT,count);
    put(e,1,D_LEVEL,l);put(e,1,D_FRAME_OFFSET,offset);put(e,1,D_CAPACITY,ORB60_CAPACITY);
    put(e,1,D_AP_CTRL,1);if(e->profiling)e->profile.desc_start[l]=now_ns();return 0;
}
static int finish_desc(struct orb_engine *e,unsigned l,unsigned count,unsigned offset) {
    barrier();const uint8_t *s=e->ddr+desc_stats(l);
    return get(e,1,D_AP_RETURN)!=0||orb_get32(s)!=0x600002||orb_get32(s+4)!=0
        ||orb_get32(s+8)!=l||orb_get32(s+12)!=count||orb_get32(s+16)!=count
        ||orb_get32(s+20)!=offset||orb_get32(s+32)!=count*16||orb_get32(s+36)!=count*64
        ||!orb_get32(s+40)?-1:0;
}
static int wait_pair(struct orb_engine *e,unsigned level,int image,unsigned timeout_ms) {
    uint64_t end=now_ns()+(uint64_t)timeout_ms*1000000ull;
    int done0=!image,done1=0;
    while(!done0||!done1) {
        if(!done0) {done0=!!(get(e,0,L_AP_CTRL)&2u);
            if(done0&&e->profiling)e->profile.image_ns[level+1]=now_ns()-e->profile.image_start[level+1];}
        if(!done1) {done1=!!(get(e,1,D_AP_CTRL)&2u);
            if(done1&&e->profiling)e->profile.desc_ns[level]=now_ns()-e->profile.desc_start[level];}
        if(now_ns()>end){errno=ETIMEDOUT;return -1;}
    }
    barrier();return 0;
}
static int run_frame(struct orb_engine *e,const uint8_t *image,unsigned input_offset,uint64_t copy_ns,
                   uint8_t *out,size_t *bytes,uint32_t *count,unsigned timeout_ms) {
    if(!out||!bytes||!count||!timeout_ms){errno=EINVAL;return -1;}
    e->frame_raw0_offset=input_offset;
    memset(&e->profile,0,sizeof(e->profile));
    memset(out,0,ORB60_RESULT_MAX);
    uint64_t start=now_ns();
    if(image){memcpy(e->ddr+input_offset,image,ORB60_IMAGE_BYTES);barrier();copy_ns=now_ns()-start;}
    else barrier();
    start=now_ns();
    e->profile.copy_ns=copy_ns;
    /* Poison summaries, not entire images. Stale records cannot pass acceptance. */
    for(unsigned l=0;l<8;++l) {
        memset(e->ddr+summary(l),0xa5,64);memset(e->ddr+layer_stats(l),0xa5,64);
        memset(e->ddr+desc_stats(l),0xa5,64);
    }
    if(launch_image(e,0))goto failed;
    uint64_t end=now_ns()+(uint64_t)timeout_ms*1000000ull;
    while(!(get(e,0,L_AP_CTRL)&2u))if(now_ns()>end){errno=ETIMEDOUT;return -1;}
    if(e->profiling)e->profile.image_ns[0]=now_ns()-e->profile.image_start[0];
    unsigned counts[8]={0},offsets[8]={0},total=0;
    if(finish_image(e,0,&counts[0]))goto failed;
    for(unsigned l=0;l<8;++l) {
        offsets[l]=total;total+=counts[l];
        if(launch_desc(e,l,counts[l],offsets[l]))goto failed;
        if(l<7 && launch_image(e,l+1))goto failed;
        if(wait_pair(e,l,l<7,timeout_ms))return -1;
        if(finish_desc(e,l,counts[l],offsets[l]))goto failed;
        if(l<7 && finish_image(e,l+1,&counts[l+1]))goto failed;
    }
    barrier();e->profile.core_ns=now_ns()-start;
    orb_put64(out+64,e->profile.core_ns);orb_put64(out+72,copy_ns);
    uint64_t snapshot_start=e->profiling?now_ns():0;
    for(unsigned l=0;l<8;++l) {orb_put32(out+4*l,counts[l]);orb_put32(out+32+4*l,offsets[l]);}
    memcpy(out+ORB60_META_BYTES,e->ddr+FEATURES,total*64);
    uint8_t *stats=out+ORB60_META_BYTES+total*64;
    for(unsigned l=0;l<8;++l) {
        memcpy(stats+l*128,e->ddr+layer_stats(l),64);
        memcpy(stats+l*128+64,e->ddr+desc_stats(l),64);
    }
    if(e->profiling)e->profile.snapshot_ns=now_ns()-snapshot_start;
    *bytes=ORB60_META_BYTES+total*64+ORB60_STATS_BYTES;*count=total;return 0;
failed:
    errno=EIO;return -1;
}
int orb_engine_run(struct orb_engine *e,const uint8_t *image,uint8_t *out,
                   size_t *bytes,uint32_t *count,unsigned timeout_ms) {
    if(!image){errno=EINVAL;return -1;}
    return run_frame(e,image,raws[0],0,out,bytes,count,timeout_ms);
}
int orb_engine_run_at(struct orb_engine *e,unsigned input_offset,uint64_t copy_ns,
                      uint8_t *out,size_t *bytes,uint32_t *count,unsigned timeout_ms) {
    if(input_offset<ORB60_RX_BASE || input_offset>=ORB60_RX_BASE+3*ORB60_RX_STRIDE ||
       (input_offset-ORB60_RX_BASE)%ORB60_RX_STRIDE || input_offset+ORB60_IMAGE_BYTES>ORB60_DDR_SIZE) {
        errno=EINVAL;return -1;
    }
    return run_frame(e,NULL,input_offset,copy_ns,out,bytes,count,timeout_ms);
}
