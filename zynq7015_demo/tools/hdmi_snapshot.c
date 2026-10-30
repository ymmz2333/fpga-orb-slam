/* Read-only capture of the paired HDMI buffer, with the same exclusive lease
 * as the ORB engine. Does not start/reset/program PL or change any register. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/file.h>
int main(int argc,char **argv){
    if(argc!=3){fprintf(stderr,"Usage: hdmi-snapshot UIO OUTPUT_RGB565\n");return 2;}
    /* wc1 requires the same shared writable mapping as its normal client.
     * This utility never writes through either mapping. */
    int fd=open(argv[1],O_RDWR|O_SYNC);if(fd<0||flock(fd,LOCK_EX|LOCK_NB)){perror("Exclusive idle UIO lease required");return 1;}
    uint32_t *regs=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    uint8_t *ddr=mmap(NULL,0x1000000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,2*sysconf(_SC_PAGESIZE));
    if(regs==MAP_FAILED||ddr==MAP_FAILED){perror("mmap");return 1;}
    volatile uint32_t *hdmi=regs+0x8000/4;uint32_t active=hdmi[4];
    if(hdmi[10]!=0x5a564431u||hdmi[11]!=((1280u<<16)|720u)||(active!=0x20b00000u&&active!=0x20d00000u)){
        fprintf(stderr,"Paired HDMI version/buffer mismatch\n");return 1;}
    FILE *out=fopen(argv[2],"wb");if(!out){perror("Output");return 1;}
    size_t written=fwrite(ddr+active-0x20000000u,1,1280*720*2,out);int closed=fclose(out);
    if(written!=1280*720*2||closed){fprintf(stderr,"Capture incomplete\n");return 1;}
    printf("HDMI_SNAPSHOT_READ_ONLY buffer=0x%08x bytes=%zu\n",active,written);
    munmap(regs,0x10000);munmap(ddr,0x1000000);close(fd);return 0;
}
