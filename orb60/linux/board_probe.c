#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc,char **argv) {
    int loaded=argc==2&&!strcmp(argv[1],"--loaded");
    if(argc>1&&!loaded)return 2;
    int fd=open("/dev/mem",O_RDONLY|O_SYNC);if(fd<0){perror("/dev/mem");return 1;}
    volatile uint32_t *s=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0xf8000000);
    if(s==MAP_FAILED){perror("SLCR mmap");close(fd);return 1;}
    uint32_t id=s[0x530/4],pll=s[0x108/4],fclk=s[0x170/4],rst=s[0x240/4],shifter=s[0x900/4];
    /* This carrier supplies 33.333333MHz PS_CLK. IO_PLL FBDIV30, FCLK /5/2. */
    unsigned fb=(pll>>12)&127u,d0=(fclk>>8)&63u,d1=(fclk>>20)&63u;
    printf("SLCR IDCODE=0x%08x IO_PLL=0x%08x FCLK0=0x%08x RESET=0x%08x SHIFTER=0x%08x\n",id,pll,fclk,rst,shifter);
    int valid=(id&0x0fffffffu)==0x0373b093u&&fb==30&&d0==5&&d1==2&&(fclk&0x30u)==0;
    munmap((void *)s,4096);
    for(unsigned p=0;p<4;++p) {
        volatile uint32_t *a=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0xf8008000u+4096*p);
        if(a==MAP_FAILED){perror("AFI mmap");close(fd);return 1;}
        printf("AFI%u RDCHAN_CTRL=0x%08x WRCHAN_CTRL=0x%08x\n",p,a[0],a[0x14/4]);
        /* All accepted m_axi/HP paths use 64-bit data, not AFI's32-bit mode. */
        if((a[0]&1)||(a[0x14/4]&1))valid=0;
        munmap((void *)a,4096);
    }
    if(loaded) {
        valid=valid&&rst==0&&(shifter&15)==15;
        for(unsigned p=0;p<2;++p) {
            volatile uint32_t *a=mmap(NULL,65536,PROT_READ,MAP_SHARED,fd,0x43c00000u+65536*p);
            if(a==MAP_FAILED){perror("control mmap");close(fd);return 1;}
            unsigned control=a[0];printf("CORE%u AP_CTRL=0x%08x\n",p,control);
            valid=valid&&!!(control&4u);munmap((void *)a,65536);
        }
    }
    close(fd);puts(valid?"BOARD_PS_CONFIGURATION_PASS":"BOARD_PS_CONFIGURATION_MISMATCH");return valid?0:1;
}
