#ifndef ORB60_PIPELINE_H
#define ORB60_PIPELINE_H
#include "engine.h"
int orb_pipeline_client(int fd,struct orb_engine *engine,const uint8_t *replay,size_t replay_bytes,int profiling);
#endif
