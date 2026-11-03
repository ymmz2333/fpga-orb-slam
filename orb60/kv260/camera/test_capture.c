/* Mock ioctl test, independent deterministic padded pixels. Not board evidence. */
#define _POSIX_C_SOURCE 200809L
#include <linux/videodev2.h>
#include <poll.h>
#include <time.h>
#include <stdarg.h>
#include <assert.h>
static int mock_ioctl(int,unsigned long,...);
static int mock_poll(struct pollfd *,nfds_t,int);
static int mock_clock(clockid_t,struct timespec *);
#define ioctl mock_ioctl
#define poll mock_poll
#define clock_gettime mock_clock
#include "v4l2_capture.c"
#undef ioctl
#undef poll
#undef clock_gettime
static unsigned next_sequence,available;
static int mock_ioctl(int fd,unsigned long code,...) {
    (void)fd;va_list args;va_start(args,code);struct v4l2_buffer *b=va_arg(args,void*);va_end(args);
    if(code==VIDIOC_DQBUF){if(!available){errno=EAGAIN;return -1;}available=0;
        b->index=0;b->sequence=next_sequence;b->timestamp.tv_sec=1;b->timestamp.tv_usec=next_sequence*1000;
        b->flags=V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;b->bytesused=(W*2+8)*H;return 0;}
    if(code==VIDIOC_QBUF){b->sequence=0;b->flags=0;return 0;}
    assert(0);return -1;
}
static int mock_poll(struct pollfd *p,nfds_t count,int timeout){(void)count;(void)timeout;p->revents=POLLIN;return 1;}
static int mock_clock(clockid_t clock,struct timespec *out){(void)clock;out->tv_sec=20;out->tv_nsec=0;return 0;}
int main(void){
    uint8_t *input=malloc((W*2+8)*H),*packed=malloc(OW*OH*2),*gray=malloc(OW*OH);assert(input&&packed&&gray);
    for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
        input[y*(W*2+8)+x*2]=(x+y*3)%256;input[y*(W*2+8)+x*2+1]=(x*7+y*11)%256;}
    for(unsigned uyvy=0;uyvy<2;uyvy++){
        struct capture s={0};s.fd=7;s.count=2;s.format.bytesperline=W*2+8;
        s.format.pixelformat=uyvy?V4L2_PIX_FMT_UYVY:V4L2_PIX_FMT_YUYV;
        s.maps[0].p=input;s.maps[0].size=(W*2+8)*H;char meta[2048];
        for(unsigned seq=5;seq<=8;seq+=3){available=1;next_sequence=seq;
            assert(!orb_camera_next(&s,packed,OW*OH*2,gray,OW*OH,meta,sizeof(meta),100));
            assert(s.last_sequence==seq&&s.gaps==(seq==5?0:2));
            assert(strstr(meta,seq==5?"\"capture_sequence\":5":"\"capture_sequence\":8"));
            assert(strstr(meta,"\"kernel_flags\":8192"));
            for(unsigned y=0;y<OH;y++)for(unsigned x=0;x<OW;x++){
                assert(gray[y*OW+x]==input[y*(W*2+8)+(x+CX)*2+uyvy]);
                for(unsigned c=0;c<2;c++)assert(packed[(y*OW+x)*2+c]==input[y*(W*2+8)+(x+CX)*2+c]);}
        }
        available=1;next_sequence=8;assert(orb_camera_next(&s,packed,OW*OH*2,gray,OW*OH,meta,sizeof(meta),100)<0);
        /* Owned output remains intact when the kernel's backing storage changes. */
        unsigned before=packed[0];input[CX*2]^=255;assert(packed[0]==before);input[CX*2]^=255;
    }
    free(input);free(packed);free(gray);puts("V4L2_PADDED_CROP_YUYV_UYVY_IDENTITY_QBUF_OWNERSHIP_PASS");return 0;
}
