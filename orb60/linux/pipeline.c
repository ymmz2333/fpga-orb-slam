#define _POSIX_C_SOURCE 200809L
#include "pipeline.h"
#include "stream_crc.h"
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>

/* A slot has exactly one owner. Queue capacity and pool capacity are both
   three; waiting for a free slot propagates TCP backpressure to the sender. */
#define SLOTS 3
struct input {
    uint8_t header[64],*pixels;
    unsigned offset,status;
    uint64_t begin,rx_ns,copy_ns,crc_ns,ready;
};
struct result {
    uint8_t header[64],payload[ORB60_RESULT_MAX];
    size_t bytes;
    uint32_t count,status;
    uint64_t begin,rx_ns,copy_ns,crc_ns,queue_ns;
    struct orb_engine_profile profile;
};
struct queue {unsigned index[SLOTS],head,count,high;};
struct context {
    int fd,stop,rx_done,worker_done,fatal,profiling;
    struct orb_engine *engine;
    const uint8_t *replay;
    size_t replay_bytes;
    pthread_mutex_t lock;
    pthread_cond_t changed;
    struct input inputs[SLOTS];
    struct result results[SLOTS];
    unsigned input_used[SLOTS],result_used[SLOTS];
    struct queue ready,completed;
    uint64_t received,processed,sent,stamp,coverage[8];
    unsigned active;
};
static uint64_t now_ns(void) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000ull+(unsigned long)t.tv_nsec;
}
/* lock held; wall time in each RX/PL/TX activity combination, not CPU time. */
static void stage(struct context *c,unsigned bit,int enabled) {
    uint64_t t=now_ns();c->coverage[c->active]+=t-c->stamp;c->stamp=t;
    if(enabled)c->active|=bit;else c->active&=~bit;
}
static void push(struct queue *q,unsigned i) {
    q->index[(q->head+q->count)%SLOTS]=i;++q->count;
    if(q->count>q->high)q->high=q->count;
}
static unsigned pop(struct queue *q) {
    unsigned i=q->index[q->head];q->head=(q->head+1)%SLOTS;--q->count;return i;
}
static int reserve(struct context *c,unsigned used[SLOTS]) {
    for(;;) {
        if(c->stop)return -1;
        for(unsigned i=0;i<SLOTS;++i)if(!used[i]){used[i]=1;return (int)i;}
        pthread_cond_wait(&c->changed,&c->lock);
    }
}
static void abort_connection(struct context *c) {
    pthread_mutex_lock(&c->lock);c->stop=1;
    shutdown(c->fd,SHUT_RDWR);pthread_cond_broadcast(&c->changed);
    pthread_mutex_unlock(&c->lock);
}
static int receive(int fd,void *data,size_t bytes) {
    uint8_t *p=data;
    while(bytes) {
        ssize_t n=recv(fd,p,bytes,0);if(n<0&&errno==EINTR)continue;
        if(n<=0)return -1;
        p+=n;bytes-=(size_t)n;
    }
    return 0;
}
static int send_result(int fd,uint8_t header[64],uint8_t *payload,size_t bytes) {
    struct iovec iov[2]={{header,64},{payload,bytes}};
    struct msghdr msg={0};msg.msg_iov=iov;msg.msg_iovlen=2;
    while(msg.msg_iovlen) {
        ssize_t sent=sendmsg(fd,&msg,MSG_NOSIGNAL);
        if(sent<0&&errno==EINTR)continue;
        if(sent<=0)return -1;
        size_t n=(size_t)sent;
        while(msg.msg_iovlen&&n>=msg.msg_iov->iov_len) {
            n-=msg.msg_iov->iov_len;++msg.msg_iov;--msg.msg_iovlen;
        }
        if(msg.msg_iovlen){msg.msg_iov->iov_base=(uint8_t*)msg.msg_iov->iov_base+n;msg.msg_iov->iov_len-=n;}
    }
    return 0;
}
static void *receiver(void *opaque) {
    struct context *c=opaque;uint8_t scratch[32768];uint64_t last_id=0,last_ts=0;int have_last=0;
    for(;;) {
        pthread_mutex_lock(&c->lock);int index=reserve(c,c->input_used);pthread_mutex_unlock(&c->lock);
        if(index<0)break;
        struct input *in=&c->inputs[index];in->status=0;in->copy_ns=0;in->crc_ns=0;
        if(receive(c->fd,in->header,64)) {
            pthread_mutex_lock(&c->lock);c->input_used[index]=0;pthread_mutex_unlock(&c->lock);break;
        }
        in->begin=now_ns();uint8_t *h=in->header;uint64_t id=orb_get64(h+16),ts=orb_get64(h+24);
        int shape=memcmp(h,"ORB60NET",8)==0&&orb_get32(h+8)==0x00400001u
            &&orb_get32(h+12)==ORB60_FRAME&&orb_get32(h+32)==ORB60_WIDTH&&orb_get32(h+36)==ORB60_HEIGHT
            &&orb_get32(h+40)<=1&&orb_get32(h+44)==ORB60_CAPACITY&&orb_get32(h+48)==ORB60_IMAGE_BYTES
            &&orb_get32(h+52)==0&&orb_get32(h+60)==0&&ts>0&&(!have_last||(id>last_id&&ts>last_ts));
        pthread_mutex_lock(&c->lock);stage(c,1,1);pthread_mutex_unlock(&c->lock);
        int truncated=0;
        if(!shape)in->status=EINVAL;
        else {
            uint32_t crc=0;
            for(size_t at=0;at<ORB60_IMAGE_BYTES;) {
                size_t n=ORB60_IMAGE_BYTES-at;if(n>sizeof(scratch))n=sizeof(scratch);
                if(receive(c->fd,scratch,n)){truncated=1;break;}
                uint64_t crc_start=now_ns();crc=orb_stream_crc(crc,scratch,n);in->crc_ns+=now_ns()-crc_start;
                uint64_t before=now_ns();memcpy(in->pixels+at,scratch,n);in->copy_ns+=now_ns()-before;at+=n;
            }
            if(!truncated) {
                if(crc!=orb_get32(h+56))in->status=EBADMSG;
                else {orb_engine_publish_input();last_id=id;last_ts=ts;have_last=1;}
            }
        }
        in->rx_ns=now_ns()-in->begin;in->ready=now_ns();
        pthread_mutex_lock(&c->lock);stage(c,1,0);
        if(truncated||c->stop)c->input_used[index]=0;
        else {push(&c->ready,(unsigned)index);++c->received;}
        pthread_cond_broadcast(&c->changed);pthread_mutex_unlock(&c->lock);
        if(truncated||in->status)break;
    }
    pthread_mutex_lock(&c->lock);c->rx_done=1;pthread_cond_broadcast(&c->changed);pthread_mutex_unlock(&c->lock);
    return NULL;
}
static void *sender(void *opaque) {
    struct context *c=opaque;
    for(;;) {
        pthread_mutex_lock(&c->lock);
        while(!c->completed.count&&!c->worker_done&&!c->stop)pthread_cond_wait(&c->changed,&c->lock);
        if(c->stop||!c->completed.count){pthread_mutex_unlock(&c->lock);break;}
        unsigned i=pop(&c->completed);stage(c,4,1);pthread_mutex_unlock(&c->lock);
        struct result *r=&c->results[i];uint8_t *h=r->header;uint64_t begin=now_ns();
        orb_put32(h+12,ORB60_RESULT);orb_put32(h+44,r->count);orb_put32(h+48,(unsigned)r->bytes);
        orb_put32(h+52,r->status);orb_put32(h+56,orb_crc32(r->payload,r->bytes));
        orb_put32(h+60,c->replay?ORB60_SIMULATED:0);
        uint64_t crc_end=now_ns();int failed=send_result(c->fd,h,r->payload,r->bytes);uint64_t end=now_ns();
        if(!failed) {
            if(c->profiling) {
                fprintf(stdout,"PIPELINE_FRAME {\"id\":%llu,\"count\":%u,\"status\":%u,\"rx_ns\":%llu,\"copy_ns\":%llu,\"input_crc_ns\":%llu,\"queue_ns\":%llu,\"pl_ns\":%llu,\"snapshot_ns\":%llu,\"reply_crc_ns\":%llu,\"send_ns\":%llu,\"total_ns\":%llu,\"image_ns\":[",
                (unsigned long long)orb_get64(h+16),r->count,r->status,(unsigned long long)r->rx_ns,
                (unsigned long long)r->copy_ns,(unsigned long long)r->crc_ns,(unsigned long long)r->queue_ns,
                (unsigned long long)r->profile.core_ns,(unsigned long long)r->profile.snapshot_ns,
                (unsigned long long)(crc_end-begin),(unsigned long long)(end-crc_end),(unsigned long long)(end-r->begin));
                for(unsigned l=0;l<8;++l)fprintf(stdout,"%s%llu",l?",":"",(unsigned long long)r->profile.image_ns[l]);
                fprintf(stdout,"],\"desc_ns\":[");
                for(unsigned l=0;l<8;++l)fprintf(stdout,"%s%llu",l?",":"",(unsigned long long)r->profile.desc_ns[l]);
                fprintf(stdout,"]}\n");
            }
        }
        pthread_mutex_lock(&c->lock);stage(c,4,0);c->result_used[i]=0;if(!failed)++c->sent;
        pthread_cond_broadcast(&c->changed);pthread_mutex_unlock(&c->lock);
        if(failed){abort_connection(c);break;}
    }
    return NULL;
}
int orb_pipeline_client(int fd,struct orb_engine *engine,const uint8_t *replay,size_t replay_bytes,int profiling) {
    struct context *c=calloc(1,sizeof(*c));if(!c)return -1;
    c->fd=fd;c->engine=engine;c->replay=replay;c->replay_bytes=replay_bytes;c->profiling=profiling;c->stamp=now_ns();
    pthread_mutex_init(&c->lock,NULL);pthread_cond_init(&c->changed,NULL);
    for(unsigned i=0;i<SLOTS;++i) {
        c->inputs[i].offset=ORB60_RX_BASE+i*ORB60_RX_STRIDE;
        c->inputs[i].pixels=replay?malloc(ORB60_IMAGE_BYTES):engine->ddr+c->inputs[i].offset;
        if(!c->inputs[i].pixels){c->stop=1;break;}
    }
    /* Each translation unit's CRC tables are initialized before concurrent use. */
    (void)orb_crc32(NULL,0);(void)orb_stream_crc(0,NULL,0);
    pthread_t rx,tx;int rx_started=0,tx_started=0,startup_error=c->stop;
    if(!startup_error) {if(pthread_create(&rx,NULL,receiver,c))startup_error=1;else rx_started=1;}
    if(!startup_error) {if(pthread_create(&tx,NULL,sender,c))startup_error=1;else tx_started=1;}
    if(startup_error){c->fatal=1;abort_connection(c);}
    for(;;) {
        pthread_mutex_lock(&c->lock);
        while(!c->ready.count&&!c->rx_done&&!c->stop)pthread_cond_wait(&c->changed,&c->lock);
        if(c->stop||!c->ready.count){pthread_mutex_unlock(&c->lock);break;}
        int output=reserve(c,c->result_used);
        if(output<0){pthread_mutex_unlock(&c->lock);break;}
        unsigned input=pop(&c->ready);stage(c,2,1);pthread_mutex_unlock(&c->lock);
        struct input *in=&c->inputs[input];struct result *out=&c->results[output];
        memcpy(out->header,in->header,64);out->begin=in->begin;out->rx_ns=in->rx_ns;out->copy_ns=in->copy_ns;out->crc_ns=in->crc_ns;
        out->queue_ns=now_ns()-in->ready;out->status=in->status;out->count=0;out->bytes=0;
        memset(&out->profile,0,sizeof(out->profile));
        if(!out->status) {
            if(replay) {
                memcpy(out->payload,replay,replay_bytes);out->bytes=replay_bytes;
                for(unsigned l=0;l<8;++l)out->count+=orb_get32(out->payload+4*l);
            }else if(orb_engine_run_at(engine,in->offset,in->copy_ns,out->payload,&out->bytes,&out->count,3000)) {
                out->status=(unsigned)errno;c->fatal=1;
            }
            out->profile=engine->profile;
        }
        if(out->status) {
            const char *message=c->fatal?"PL failure: reset/reload before reuse":"invalid frame header, order or CRC";
            out->bytes=strlen(message);memcpy(out->payload,message,out->bytes);out->count=0;
        }
        pthread_mutex_lock(&c->lock);stage(c,2,0);c->input_used[input]=0;++c->processed;
        push(&c->completed,(unsigned)output);pthread_cond_broadcast(&c->changed);pthread_mutex_unlock(&c->lock);
        if(out->status){shutdown(fd,SHUT_RD);break;}
    }
    pthread_mutex_lock(&c->lock);c->worker_done=1;pthread_cond_broadcast(&c->changed);pthread_mutex_unlock(&c->lock);
    if(rx_started)pthread_join(rx,NULL);
    if(tx_started)pthread_join(tx,NULL);
    stage(c,0,0);
    fprintf(stdout,"PIPELINE_SUMMARY {\"received\":%llu,\"processed\":%llu,\"sent\":%llu,\"rx_slots\":3,\"result_slots\":3,\"ready_high\":%u,\"result_high\":%u,\"rx_pl_overlap_ns\":%llu,\"pl_tx_overlap_ns\":%llu,\"all_three_ns\":%llu,\"fatal\":%d}\n",
        (unsigned long long)c->received,(unsigned long long)c->processed,(unsigned long long)c->sent,
        c->ready.high,c->completed.high,(unsigned long long)(c->coverage[3]+c->coverage[7]),
        (unsigned long long)(c->coverage[6]+c->coverage[7]),(unsigned long long)c->coverage[7],c->fatal);
    fflush(stdout);int result=c->fatal?-1:0;
    for(unsigned i=0;i<SLOTS;++i)if(replay)free(c->inputs[i].pixels);
    pthread_cond_destroy(&c->changed);pthread_mutex_destroy(&c->lock);free(c);return result;
}
