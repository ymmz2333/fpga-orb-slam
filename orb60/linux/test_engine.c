#include "engine.h"
#include "orb60_registers.h"
#include "stream_crc.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const unsigned budgets[8]={217,181,151,126,105,87,73,60};
static const unsigned widths[8]={960,800,667,556,463,386,322,268};
static const unsigned heights[8]={720,600,500,417,347,289,241,201};
struct model {unsigned reg[2][64],active[2],ticks[2],mode,count_mode,overlaps,images,descriptors;};
static uint8_t *memory(struct orb_engine *e,unsigned pointer){
    assert(pointer>=ORB60_DDR_BASE && pointer<ORB60_DDR_BASE+ORB60_DDR_SIZE);
    return e->ddr+pointer-ORB60_DDR_BASE;
}
static void finish(struct orb_engine *e,unsigned core) {
    struct model *m=e->test_context;unsigned *r=m->reg[core];
    unsigned l=r[(core?D_LEVEL:L_LEVEL)/4];
    if(!core) {
        uint8_t *s=memory(e,r[L_RESULT/4]),*t=memory(e,r[L_STATS/4]);memset(s,0,64);memset(t,0,64);
        unsigned count=m->count_mode?0:budgets[l];
        orb_put32(s,m->mode==1?0:0x20000);orb_put32(s+12,count);
        orb_put32(t,0x600003);orb_put32(t+8,l);orb_put32(t+12,widths[l]);orb_put32(t+16,heights[l]);
        orb_put32(t+20,(widths[l]*heights[l]+7)&~7u);orb_put32(t+24,orb_get32(t+20));orb_put32(t+44,1234);
        memset(memory(e,r[L_BLURRED/4]),(int)(0x80+l),64);
        if(l<7)memset(memory(e,r[L_RESIZED/4]),(int)(l+1),64);
    }else {
        assert(memory(e,r[D_RAW/4])[0]==l && memory(e,r[D_BLURRED/4])[0]==0x80+l);
        unsigned count=r[D_COUNT/4],offset=r[D_FRAME_OFFSET/4];
        uint8_t *s=memory(e,r[D_STATS/4]);memset(s,0,64);
        orb_put32(s,0x600002);orb_put32(s+8,l);orb_put32(s+12,count);orb_put32(s+16,count);
        orb_put32(s+20,offset);orb_put32(s+32,count*16);orb_put32(s+36,count*64);orb_put32(s+40,456);
        for(unsigned i=0;i<count;++i)memset(memory(e,r[D_FEATURES/4])+64*(offset+i),(int)l,64);
    }
    m->active[core]=0;r[0]=6;
}
static unsigned read_reg(struct orb_engine *e,unsigned core,unsigned address) {
    struct model *m=e->test_context;
    if(address==0 && m->active[core] && m->mode!=2) {
        if(++m->ticks[core]>=((core==0)?5:9))finish(e,core);
    }
    unsigned value=m->reg[core][address/4];
    if(address==0)m->reg[core][0]&=~2u;
    return value;
}
static void write_reg(struct orb_engine *e,unsigned core,unsigned address,unsigned value) {
    struct model *m=e->test_context;m->reg[core][address/4]=value;
    if(address==0 && value==1) {
        assert(!m->active[core]);m->active[core]=1;m->ticks[core]=0;
        unsigned *r=m->reg[core];
        if(core) {
            ++m->descriptors;unsigned l=r[D_LEVEL/4];
            assert(memory(e,r[D_RAW/4])[0]==l);
            assert(memory(e,r[D_BLURRED/4])[0]==0x80+l);
        }else {
            ++m->images;unsigned l=r[L_LEVEL/4];assert(memory(e,r[L_IMAGE_R/4])[0]==l);
            assert(r[L_BUDGET/4]==budgets[l] && r[L_SELECTED_CAPACITY/4]==1000);
            if(m->active[1]) {
                ++m->overlaps;
                assert(r[L_BLURRED/4]!=m->reg[1][D_BLURRED/4]);
                if(l<7)assert(r[L_RESIZED/4]!=m->reg[1][D_RAW/4]);
            }
        }
    }
}
int main(void) {
    assert(orb_crc32("123456789",9)==0xcbf43926u);
    uint32_t crc=orb_stream_crc(0,"1234",4);assert(orb_stream_crc(crc,"56789",5)==0xcbf43926u);
    uint8_t *image=calloc(1,ORB60_IMAGE_BYTES),*out=malloc(ORB60_RESULT_MAX);
    struct orb_engine e={0};e.ddr=calloc(1,ORB60_DDR_SIZE);e.read=read_reg;e.write=write_reg;
    assert(image&&out&&e.ddr);
    for(unsigned mode=0;mode<4;++mode) {
        struct model m={0};e.test_context=&m;m.mode=mode<3?mode:0;m.count_mode=mode==3;
        m.reg[0][0]=m.reg[1][0]=4;size_t bytes=0;uint32_t count=0;
        int result=orb_engine_run(&e,image,out,&bytes,&count,3);
        if(mode==1){assert(result<0 && errno==EIO);continue;}
        if(mode==2){assert(result<0 && errno==ETIMEDOUT);continue;}
        assert(result==0 && count==(mode==3?0:1000));
        assert(bytes==128+64*count+1024 && m.overlaps==7 && m.images==8 && m.descriptors==8);
        unsigned offset=0;
        for(unsigned l=0;l<8;++l) {
            assert(orb_get32(out+32+4*l)==offset);unsigned n=orb_get32(out+4*l);
            assert(n==(mode==3?0:budgets[l]));
            for(unsigned i=0;i<n*64;++i)assert(out[128+64*offset+i]==l);
            offset+=n;
        }
    }
    for(unsigned slot=0;slot<3;++slot) {
        struct model m={0};e.test_context=&m;m.reg[0][0]=m.reg[1][0]=4;
        memset(e.ddr+0x100ff8,0xee,64);
        memset(e.ddr+ORB60_RX_BASE+slot*ORB60_RX_STRIDE,0,ORB60_IMAGE_BYTES);
        size_t bytes=0;uint32_t count=0;
        assert(orb_engine_run_at(&e,ORB60_RX_BASE+slot*ORB60_RX_STRIDE,456,out,&bytes,&count,3)==0);
        assert(count==1000&&orb_get64(out+72)==456&&m.images==8&&m.descriptors==8&&m.overlaps==7);
    }
    {size_t n=0;uint32_t count=0;assert(orb_engine_run_at(&e,0x100ff8,0,out,&n,&count,3)<0&&errno==EINVAL);}
    free(image);free(out);free(e.ddr);puts("ENGINE_8_LEVEL_OWNERSHIP_APPEND_EMPTY_BAD_ABI_TIMEOUT_PASS");return 0;
}
