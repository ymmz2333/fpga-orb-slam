/* Integration example only: compile with paired engine.c/headers on Zynq Linux.
 * Caller owns frame lifetime. Never open this while the network server owns UIO.
 * On engine failure, stop and reset/reload PL before reuse; there is no CPU ORB.
 */
#include "engine.h"
#include <string.h>
struct orb60_frame_features {uint64_t frame_id,timestamp_ns;uint32_t count;uint8_t records[64000];};
int orb60_extract_direct(struct orb_engine *engine,const uint8_t gray[960*720],uint64_t frame_id,
                        uint64_t timestamp_ns,struct orb60_frame_features *out){
    uint8_t payload[ORB60_RESULT_MAX];size_t bytes=0;uint32_t count=0;
    if(!engine||!gray||!out||!timestamp_ns)return -1;
    if(orb_engine_run(engine,gray,payload,&bytes,&count,2000))return -2;
    if(count>1000||bytes!=128+64u*count+1024)return -3;
    out->frame_id=frame_id;out->timestamp_ns=timestamp_ns;out->count=count;
    memcpy(out->records,payload+128,64u*count);return 0;
}
