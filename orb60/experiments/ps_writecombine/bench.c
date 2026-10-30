#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "protocol.h"

#define APERTURE 0x01000000u
#define SCRATCH 0x00f00000u
#define GUARD 64u
#define IMAGE_BYTES (960u * 720u)
#define MAX_RUNS 200u
static volatile sig_atomic_t interrupted;
static void stop(int sig) { (void)sig; interrupted = 1; }
static void barrier(void) {
#if defined(__arm__)
    __asm__ __volatile__("dsb sy" ::: "memory");
#else
    __sync_synchronize();
#endif
}
static uint64_t ns(clockid_t clock) {
    struct timespec t;
    if (clock_gettime(clock, &t)) { perror("clock_gettime"); exit(1); }
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}
static int read_attr(const char *dev, unsigned map, const char *key, unsigned long *value) {
    char path[256];
    if (snprintf(path,sizeof(path),"/sys/class/uio/%s/maps/map%u/%s",dev,map,key) >= (int)sizeof(path)) return -1;
    FILE *f = fopen(path,"r");
    if (!f) return -1;
    int ok = fscanf(f,"%lx",value) == 1;
    fclose(f); return ok ? 0 : -1;
}
static int compare_u64(const void *a,const void *b) {
    uint64_t x=*(const uint64_t *)a,y=*(const uint64_t *)b;
    return (x>y)-(x<y);
}
static void pattern(uint8_t *p,unsigned seed) {
    uint32_t x=0x76543210u ^ seed;
    for (unsigned i=0;i<IMAGE_BYTES;++i) {
        x^=x<<13; x^=x>>17; x^=x<<5; p[i]=(uint8_t)x;
    }
}
int main(int argc,char **argv) {
    if (argc<3 || argc>4) {
        fprintf(stderr,"usage: %s /dev/uioN iterations [chunk_bytes]\n",argv[0]); return 2;
    }
    const char *dev=argv[1],*name=strrchr(dev,'/'); name=name?name+1:dev;
    if (strncmp(dev,"/dev/uio",8) || strspn(name+3,"0123456789")!=strlen(name+3) || !name[3]) return 2;
    char *end;
    unsigned long runs=strtoul(argv[2],&end,10);
    if (*end || !runs || runs>MAX_RUNS) return 2;
    unsigned long chunk=argc==4?strtoul(argv[3],&end,10):32768;
    if ((argc==4 && *end) || !chunk || chunk>IMAGE_BYTES) return 2;
    const unsigned long addresses[3]={0x43c00000,0x43c10000,0x20000000};
    const unsigned long sizes[3]={65536,65536,APERTURE};
    for (unsigned i=0;i<3;++i) {
        unsigned long address,size,offset;
        if (read_attr(name,i,"addr",&address) || read_attr(name,i,"size",&size) ||
            read_attr(name,i,"offset",&offset) || address!=addresses[i] || size!=sizes[i] || offset) {
            fprintf(stderr,"unexpected UIO map %u\n",i); return 1;
        }
    }
    int fd=open(dev,O_RDWR|O_SYNC);
    if (fd<0) { perror("open UIO"); return 1; }
    if (flock(fd,LOCK_EX|LOCK_NB)) { perror("UIO already owned"); close(fd); return 1; }
    long page=sysconf(_SC_PAGESIZE);
    for (unsigned i=0;i<2;++i) {
        volatile uint32_t *r=mmap(NULL,65536,PROT_READ,MAP_SHARED,fd,(off_t)(i*page));
        if (r==MAP_FAILED) { perror("register mmap"); close(fd); return 1; }
        unsigned control=r[0]; barrier(); munmap((void *)r,65536);
        if (!(control&4)) { fprintf(stderr,"core %u is not idle\n",i); close(fd); return 1; }
    }
    uint8_t *ddr=mmap(NULL,APERTURE,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)(2*page));
    if (ddr==MAP_FAILED) { perror("DDR mmap"); close(fd); return 1; }
    uint8_t *source=NULL,*backup=NULL,*check=NULL;
    if (posix_memalign((void **)&source,64,IMAGE_BYTES) ||
        posix_memalign((void **)&backup,64,IMAGE_BYTES+2*GUARD) ||
        posix_memalign((void **)&check,64,IMAGE_BYTES+2*GUARD)) {
        fprintf(stderr,"allocation failed\n"); free(source);free(backup);free(check);
        munmap(ddr,APERTURE);close(fd);return 1;
    }
    uint8_t *target=ddr+SCRATCH;
    memcpy(backup,target-GUARD,IMAGE_BYTES+2*GUARD); barrier();
    signal(SIGINT,stop);signal(SIGTERM,stop);
    uint64_t times[MAX_RUNS];
    uint64_t sum=0,cpu_sum=0,crc_sum=0;unsigned completed=0;int failed=0;
    (void)orb_crc32(NULL,0);
    for (unsigned i=0;i<runs+3 && !interrupted;++i) {
        pattern(source,i);
        memset(target-GUARD,0xa5,GUARD);memset(target+IMAGE_BYTES,0xa5,GUARD);barrier();
        uint64_t cpu_begin=ns(CLOCK_THREAD_CPUTIME_ID),begin=ns(CLOCK_MONOTONIC);
        for (unsigned at=0;at<IMAGE_BYTES;) {
            unsigned n=IMAGE_BYTES-at;if(n>chunk)n=(unsigned)chunk;
            memcpy(target+at,source+at,n);at+=n;
        }
        barrier();
        uint64_t elapsed=ns(CLOCK_MONOTONIC)-begin,cpu_elapsed=ns(CLOCK_THREAD_CPUTIME_ID)-cpu_begin;
        begin=ns(CLOCK_MONOTONIC);uint32_t crc=orb_crc32(source,IMAGE_BYTES);
        uint64_t crc_elapsed=ns(CLOCK_MONOTONIC)-begin;
        memcpy(check,target-GUARD,IMAGE_BYTES+2*GUARD);barrier();
        if (memcmp(check+GUARD,source,IMAGE_BYTES) || orb_crc32(check+GUARD,IMAGE_BYTES)!=crc) failed=1;
        for (unsigned g=0;g<GUARD;++g)
            if(check[g]!=0xa5 || check[GUARD+IMAGE_BYTES+g]!=0xa5)failed=1;
        if (failed) { fprintf(stderr,"data or guard mismatch at iteration %u\n",i);break; }
        if (i>=3) { times[completed]=elapsed;
            ++completed;sum+=elapsed;cpu_sum+=cpu_elapsed;crc_sum+=crc_elapsed; }
    }
    memcpy(target-GUARD,backup,IMAGE_BYTES+2*GUARD);barrier();
    memcpy(check,target-GUARD,IMAGE_BYTES+2*GUARD);barrier();
    int restored=!memcmp(check,backup,IMAGE_BYTES+2*GUARD);
    if (!restored) { fprintf(stderr,"scratch restore mismatch\n");failed=1; }
    munmap(ddr,APERTURE);close(fd);free(source);free(backup);free(check);
    if (completed) {
        qsort(times,completed,sizeof(*times),compare_u64);
        printf("{\"test\":\"orb60_ddr_copy\",\"iterations\":%u,\"bytes\":%u,\"chunk_bytes\":%lu,"
               "\"copy_mean_ms\":%.6f,\"copy_p50_ms\":%.6f,\"copy_max_ms\":%.6f,"
               "\"copy_cpu_mean_ms\":%.6f,\"copy_MB_s\":%.3f,\"crc_mean_ms\":%.6f,"
               "\"exact\":%s,\"scratch_restored\":%s,\"complete\":%s}\n",
               completed,IMAGE_BYTES,chunk,(double)sum/completed/1e6,(double)times[completed/2]/1e6,
               (double)times[completed-1]/1e6,(double)cpu_sum/completed/1e6,
               (double)IMAGE_BYTES*completed*1000.0/sum,(double)crc_sum/completed/1e6,
               failed?"false":"true",restored?"true":"false",completed==runs&&!interrupted?"true":"false");
    }
    return failed || interrupted || completed!=runs ? 1 : 0;
}
