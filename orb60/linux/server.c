#define _POSIX_C_SOURCE 200809L
#include "engine.h"
#include "pipeline.h"
#include <errno.h>
#include <netdb.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static int transfer(int fd,void *data,size_t n,int write_data) {
    uint8_t *p=(uint8_t *)data;
    while(n) {
        ssize_t r=write_data?send(fd,p,n,MSG_NOSIGNAL):recv(fd,p,n,0);
        if(r<0&&errno==EINTR)continue;
        if(r<=0)return -1;
        p+=r;n-=(size_t)r;
    }
    return 0;
}
static void reply_header(uint8_t h[64],const uint8_t req[64],unsigned bytes,unsigned count,
                         unsigned status,unsigned flags,const uint8_t *payload) {
    memcpy(h,req,64);orb_put32(h+12,ORB60_RESULT);orb_put32(h+44,count);
    orb_put32(h+48,bytes);orb_put32(h+52,status);orb_put32(h+56,orb_crc32(payload,bytes));orb_put32(h+60,flags);
}
static uint64_t time_ns(void) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000ull+(unsigned long)t.tv_nsec;
}
static int client(int fd,struct orb_engine *e,const uint8_t *replay,size_t replay_size,int profiling) {
    uint8_t *image=malloc(ORB60_IMAGE_BYTES),*payload=malloc(ORB60_RESULT_MAX);
    if(!image||!payload){free(image);free(payload);return -1;}
    int fatal=0;
    for(;;) {
        uint8_t h[64],response[64];if(transfer(fd,h,64,0))break;
        uint64_t begin=profiling?time_ns():0,rx_ns=0,crc_ns=0,reply_crc_ns=0,send_ns=0,stamp=begin;
        int shape=memcmp(h,"ORB60NET",8)==0&&orb_get32(h+8)==0x00400001u
            &&orb_get32(h+12)==ORB60_FRAME&&orb_get32(h+32)==ORB60_WIDTH&&orb_get32(h+36)==ORB60_HEIGHT
            &&orb_get32(h+40)<=1&&orb_get32(h+44)==ORB60_CAPACITY&&orb_get32(h+48)==ORB60_IMAGE_BYTES
            &&orb_get32(h+52)==0&&orb_get32(h+60)==0&&orb_get64(h+24)>0;
        unsigned status=shape?0:EINVAL;size_t n=0;uint32_t count=0;
        if(shape) {
            if(transfer(fd,image,ORB60_IMAGE_BYTES,0))break;
            if(profiling){rx_ns=time_ns()-stamp;stamp=time_ns();}
            uint32_t input_crc=orb_crc32(image,ORB60_IMAGE_BYTES);
            if(profiling){crc_ns=time_ns()-stamp;stamp=time_ns();}
            if(input_crc!=orb_get32(h+56))status=EBADMSG;
            else if(replay) {memcpy(payload,replay,replay_size);n=replay_size;for(unsigned l=0;l<8;++l)count+=orb_get32(payload+l*4);}
            else if(orb_engine_run(e,image,payload,&n,&count,3000)) {status=(unsigned)errno;fatal=1;}
        }
        if(status) {
            const char *message=fatal?"PL failure: service stopped; reset/reload before reuse":"invalid frame header or CRC";
            n=strlen(message);memcpy(payload,message,n);count=0;
        }
        if(profiling)stamp=time_ns();
        reply_header(response,h,(unsigned)n,count,status,replay?ORB60_SIMULATED:0,payload);
        if(profiling){reply_crc_ns=time_ns()-stamp;stamp=time_ns();}
        if(transfer(fd,response,64,1)||transfer(fd,payload,n,1))break;
        if(profiling)send_ns=time_ns()-stamp;
        if(status||fatal)break;
        fprintf(stdout,"FRAME id=%llu role=%u count=%u engine_ns=%llu simulated=%u\n",
                (unsigned long long)orb_get64(h+16),orb_get32(h+40),count,
                (unsigned long long)orb_get64(payload+64),replay?1:0);fflush(stdout);
        if(profiling) {
            fprintf(stdout,"PROFILE {\"id\":%llu,\"rx_ns\":%llu,\"input_crc_ns\":%llu,\"copy_ns\":%llu,\"pl_ns\":%llu,\"snapshot_ns\":%llu,\"reply_crc_ns\":%llu,\"send_ns\":%llu,\"total_ns\":%llu,\"image_ns\":[",
                (unsigned long long)orb_get64(h+16),(unsigned long long)rx_ns,(unsigned long long)crc_ns,
                (unsigned long long)e->profile.copy_ns,(unsigned long long)e->profile.core_ns,
                (unsigned long long)e->profile.snapshot_ns,(unsigned long long)reply_crc_ns,
                (unsigned long long)send_ns,(unsigned long long)(time_ns()-begin));
            for(unsigned l=0;l<8;++l)fprintf(stdout,"%s%llu",l?",":"",(unsigned long long)e->profile.image_ns[l]);
            fprintf(stdout,"],\"desc_ns\":[");
            for(unsigned l=0;l<8;++l)fprintf(stdout,"%s%llu",l?",":"",(unsigned long long)e->profile.desc_ns[l]);
            fprintf(stdout,"]}\n");fflush(stdout);
        }
    }
    free(image);free(payload);return fatal?-1:0;
}
int main(int argc,char **argv) {
    const char *uio=NULL,*replay_file=NULL,*bind_host="::",*port="5600";int once=0,profiling=0,pipeline=0;
    for(int a=1;a<argc;++a) {
        if(!strcmp(argv[a],"--uio")&&a+1<argc)uio=argv[++a];
        else if(!strcmp(argv[a],"--replay")&&a+1<argc)replay_file=argv[++a];
        else if(!strcmp(argv[a],"--bind")&&a+1<argc)bind_host=argv[++a];
        else if(!strcmp(argv[a],"--port")&&a+1<argc)port=argv[++a];
        else if(!strcmp(argv[a],"--once"))once=1;
        else if(!strcmp(argv[a],"--profile"))profiling=1;
        else if(!strcmp(argv[a],"--pipeline"))pipeline=1;
        else {fprintf(stderr,"Usage: orb60-server (--uio /dev/uioX | --replay payload.bin) [--bind ::] [--port 5600] [--once] [--profile] [--pipeline]\n");return 2;}
    }
    if((!uio)==(!replay_file)){fprintf(stderr,"Choose exactly one hardware UIO or explicitly simulated replay backend\n");return 2;}
    struct orb_engine engine={0};engine.fd=-1;uint8_t *replay=NULL;size_t replay_size=0;
    if(uio && orb_engine_open(&engine,uio)){perror("UIO map validation/open");return 1;}
    engine.profiling=profiling;
    if(replay_file) {
        replay=malloc(ORB60_RESULT_MAX+1u);FILE *f=fopen(replay_file,"rb");
        if(!replay||!f){perror("replay fixture");return 1;}
        replay_size=fread(replay,1,ORB60_RESULT_MAX+1u,f);fclose(f);
        unsigned count=0;int ok=replay_size>=ORB60_META_BYTES+ORB60_STATS_BYTES;
        for(unsigned l=0;ok&&l<8;++l) {if(orb_get32(replay+32+4*l)!=count)ok=0;count+=orb_get32(replay+4*l);}
        if(!ok||count>ORB60_CAPACITY||replay_size!=ORB60_META_BYTES+64*count+ORB60_STATS_BYTES) {
            fprintf(stderr,"invalid replay payload\n");free(replay);return 2;
        }
    }
    struct addrinfo hints={0},*addresses=NULL;hints.ai_socktype=SOCK_STREAM;hints.ai_flags=AI_PASSIVE;
    int gai=getaddrinfo(bind_host,port,&hints,&addresses);if(gai){fprintf(stderr,"listen address: %s\n",gai_strerror(gai));return 1;}
    int server=-1;
    for(struct addrinfo *a=addresses;a;a=a->ai_next) {
        server=socket(a->ai_family,a->ai_socktype,a->ai_protocol);if(server<0)continue;
        int yes=1,no=0;setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
        if(a->ai_family==AF_INET6)setsockopt(server,IPPROTO_IPV6,IPV6_V6ONLY,&no,sizeof(no));
        if(!bind(server,a->ai_addr,a->ai_addrlen)&&!listen(server,1))break;
        close(server);server=-1;
    }
    freeaddrinfo(addresses);if(server<0){perror("listen");return 1;}
    signal(SIGPIPE,SIG_IGN);printf("ORB60_SERVER_READY port=%s simulated=%d\n",port,replay?1:0);fflush(stdout);
    int exit_code=0;
    do {
        int fd=accept(server,NULL,NULL);if(fd<0){if(errno==EINTR)continue;perror("accept");exit_code=1;break;}
        struct timeval timeout={10,0};int yes=1;
        setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
        setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
        int result=pipeline?orb_pipeline_client(fd,&engine,replay,replay_size,profiling):client(fd,&engine,replay,replay_size,profiling);close(fd);
        if(result){fprintf(stderr,"PL transaction failed; reload/reset required\n");exit_code=1;break;}
    }while(!once);
    close(server);if(uio)orb_engine_close(&engine);free(replay);return exit_code;
}
