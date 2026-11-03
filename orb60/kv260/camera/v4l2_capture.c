/* Linux PS camera transport only. No image resize, JPEG, ORB or PL access. */
#define _POSIX_C_SOURCE 200809L
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "v4l2_capture.h"

enum { W=1280, H=720, OW=960, OH=720, CX=160, NBUF=4 };
struct region { void *p; size_t size; };
struct capture {
    int fd, streaming;
    unsigned count;
    struct region maps[NBUF];
    struct v4l2_pix_format format;
    struct v4l2_fract interval;
    uint64_t frames, gaps, first_stamp, last_stamp;
    uint32_t last_sequence;
};
static int call(int fd,unsigned long code,void *arg) {
    int rc; do {rc=ioctl(fd,code,arg);} while(rc<0&&errno==EINTR); return rc;
}
static uint64_t now_ns(void) {
    struct timespec t; if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;
    return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;
}
static int fail(char *out,size_t size,const char *why) {
    snprintf(out,size,"%s (errno=%d)",why,errno);return -1;
}
int orb_camera_close(void *opaque) {
    struct capture *s=opaque;if(!s)return 0;int rc=0;
    if(s->streaming){enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;if(call(s->fd,VIDIOC_STREAMOFF,&type))rc=-1;}
    for(unsigned i=0;i<s->count;i++)if(s->maps[i].p&&s->maps[i].p!=MAP_FAILED)munmap(s->maps[i].p,s->maps[i].size);
    if(s->fd>=0)close(s->fd);free(s);return rc;
}
void *orb_camera_open(const char *device,uint32_t fourcc,unsigned fps,char *error,size_t size) {
    struct capture *s=calloc(1,sizeof(*s));if(!s){fail(error,size,"Camera allocation failed");return NULL;}s->fd=-1;
    const char *why="Camera open failed";
    if((fourcc!=V4L2_PIX_FMT_YUYV&&fourcc!=V4L2_PIX_FMT_UYVY)||!fps||fps>120){errno=EINVAL;goto bad;}
    s->fd=open(device,O_RDWR|O_NONBLOCK|O_CLOEXEC);if(s->fd<0)goto bad;
    struct v4l2_capability cap={0};why="Not a streaming V4L2 capture device";
    if(call(s->fd,VIDIOC_QUERYCAP,&cap))goto bad;
    uint32_t flags=(cap.capabilities&V4L2_CAP_DEVICE_CAPS)?cap.device_caps:cap.capabilities;
    if(!(flags&V4L2_CAP_VIDEO_CAPTURE)||!(flags&V4L2_CAP_STREAMING)){errno=EINVAL;goto bad;}
    struct v4l2_format f={0};f.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    f.fmt.pix.width=W;f.fmt.pix.height=H;f.fmt.pix.pixelformat=fourcc;f.fmt.pix.field=V4L2_FIELD_NONE;
    why="Exact uncompressed camera format refused";
    if(call(s->fd,VIDIOC_S_FMT,&f))goto bad;s->format=f.fmt.pix;
    if(f.fmt.pix.width!=W||f.fmt.pix.height!=H||f.fmt.pix.pixelformat!=fourcc||f.fmt.pix.field!=V4L2_FIELD_NONE||f.fmt.pix.bytesperline<W*2){errno=EINVAL;goto bad;}
    struct v4l2_streamparm parm={0};parm.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    parm.parm.capture.timeperframe.numerator=1;parm.parm.capture.timeperframe.denominator=fps;
    why="Requested camera interval refused";if(call(s->fd,VIDIOC_S_PARM,&parm))goto bad;
    s->interval=parm.parm.capture.timeperframe;
    if(!s->interval.numerator||!s->interval.denominator||
       (uint64_t)s->interval.numerator*fps!=s->interval.denominator){errno=EINVAL;goto bad;}
    struct v4l2_requestbuffers req={0};req.count=NBUF;req.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;req.memory=V4L2_MEMORY_MMAP;
    why="Bounded camera MMAP buffers unavailable";if(call(s->fd,VIDIOC_REQBUFS,&req))goto bad;
    if(req.count<2||req.count>NBUF){errno=EINVAL;goto bad;}s->count=req.count;
    for(unsigned i=0;i<req.count;i++){
        struct v4l2_buffer b={0};b.type=req.type;b.memory=req.memory;b.index=i;
        if(call(s->fd,VIDIOC_QUERYBUF,&b))goto bad;s->maps[i].size=b.length;
        s->maps[i].p=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,s->fd,b.m.offset);
        if(s->maps[i].p==MAP_FAILED||call(s->fd,VIDIOC_QBUF,&b))goto bad;
    }
    enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;why="Camera STREAMON failed";
    if(call(s->fd,VIDIOC_STREAMON,&type))goto bad;s->streaming=1;return s;
bad: fail(error,size,why);orb_camera_close(s);return NULL;
}
int orb_camera_profile(void *opaque,char *out,size_t size) {
    struct capture *s=opaque;struct v4l2_pix_format *p=&s->format;
    int n=snprintf(out,size,"{\"width\":%u,\"height\":%u,\"fourcc\":%u,\"stride\":%u,\"sizeimage\":%u,"
        "\"colorspace\":%u,\"ycbcr_encoding\":%u,\"quantization\":%u,\"transfer_function\":%u,"
        "\"interval_numerator\":%u,\"interval_denominator\":%u,\"buffers\":%u,\"frames\":%llu,"
        "\"sequence_gaps\":%llu,\"first_timestamp_ns\":%llu,\"last_timestamp_ns\":%llu}",
        p->width,p->height,p->pixelformat,p->bytesperline,p->sizeimage,p->colorspace,p->ycbcr_enc,p->quantization,p->xfer_func,
        s->interval.numerator,s->interval.denominator,s->count,(unsigned long long)s->frames,
        (unsigned long long)s->gaps,(unsigned long long)s->first_stamp,(unsigned long long)s->last_stamp);
    return n>=0&&(size_t)n<size?0:-1;
}
int orb_camera_info(void *opaque,struct orb_camera_info *out) {
    if(!opaque||!out)return -1;struct capture *s=opaque;struct v4l2_pix_format *p=&s->format;
    *out=(struct orb_camera_info){p->width,p->height,p->pixelformat,p->bytesperline,p->sizeimage,
        p->colorspace,p->ycbcr_enc,p->quantization,p->xfer_func,s->interval.numerator,s->interval.denominator,s->count,
        s->frames,s->gaps,s->first_stamp,s->last_stamp};return 0;
}
/* Caller owns both outputs after this function returns; MMAP is requeued only
 * after both copies. Drain at most four queued frames, keeping the newest.
 * Kernel sequence gaps are explicit and are never disguised as consecutive camera frames. */
int orb_camera_read(void *opaque,uint8_t *packed,size_t packed_size,uint8_t *gray,size_t gray_size,
                    struct orb_camera_frame *frame,unsigned timeout_ms,char *meta,size_t meta_size) {
    struct capture *s=opaque;
    if(!s||!frame||!packed||!gray||packed_size!=OW*OH*2||gray_size!=OW*OH||timeout_ms>30000){errno=EINVAL;return fail(meta,meta_size,"Invalid output capacity/timeout");}
    struct pollfd p={s->fd,POLLIN,0};int ready;do {ready=poll(&p,1,(int)timeout_ms);}while(ready<0&&errno==EINTR);
    if(ready<=0||!(p.revents&POLLIN)){if(!ready)errno=ETIMEDOUT;return fail(meta,meta_size,"Camera poll failed");}
    struct v4l2_buffer latest={0};int have=0;
    for(unsigned i=0;i<s->count;i++){
        struct v4l2_buffer b={0};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;b.memory=V4L2_MEMORY_MMAP;
        if(call(s->fd,VIDIOC_DQBUF,&b)){if(errno==EAGAIN)break;goto bad;}
        if(have&&call(s->fd,VIDIOC_QBUF,&latest))goto bad;
        latest=b;have=1;
    }
    if(!have){errno=EIO;goto bad;}
    uint64_t dequeued=now_ns();uint32_t delta=latest.sequence-s->last_sequence;
    uint64_t stamp=(uint64_t)latest.timestamp.tv_sec*1000000000ULL+(uint64_t)latest.timestamp.tv_usec*1000ULL;
    uint64_t required=(uint64_t)s->format.bytesperline*(H-1)+W*2;
    if(latest.index>=s->count||latest.bytesused<required||latest.bytesused>s->maps[latest.index].size||
       (latest.flags&V4L2_BUF_FLAG_ERROR)||
       (latest.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK)!=V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC||
       !stamp||stamp<=s->last_stamp||stamp>dequeued||
       (s->frames&&(!delta||delta>=0x80000000u))){errno=EPROTO;goto bad;}
    const uint8_t *input=s->maps[latest.index].p;
    unsigned y_offset=s->format.pixelformat==V4L2_PIX_FMT_UYVY?1:0;
    for(unsigned y=0;y<OH;y++){
        const uint8_t *row=input+(size_t)y*s->format.bytesperline+CX*2;
        memcpy(packed+(size_t)y*OW*2,row,OW*2);
        for(unsigned x=0;x<OW;x++)gray[(size_t)y*OW+x]=row[x*2+y_offset];
    }
    /* QBUF is an in/out ioctl and may overwrite sequence/flags. Preserve the
     * DQBUF identity before returning ownership to the kernel. */
    uint32_t sequence=latest.sequence,kernel_flags=latest.flags;
    if(call(s->fd,VIDIOC_QBUF,&latest))goto bad;have=0;
    if(!s->frames)s->first_stamp=stamp;else s->gaps+=delta-1;
    s->last_stamp=stamp;s->last_sequence=sequence;s->frames++;
    *frame=(struct orb_camera_frame){stamp,dequeued,s->gaps,sequence,kernel_flags};return 0;
bad:
    if(have)call(s->fd,VIDIOC_QBUF,&latest);
    return fail(meta,meta_size,"Camera dequeue/copy identity failed");
}
int orb_camera_next(void *opaque,uint8_t *packed,size_t packed_size,uint8_t *gray,size_t gray_size,
                    char *meta,size_t meta_size,unsigned timeout_ms) {
    struct orb_camera_frame f;
    if(orb_camera_read(opaque,packed,packed_size,gray,gray_size,&f,timeout_ms,meta,meta_size))return -1;
    int n=snprintf(meta,meta_size,"{\"timestamp_ns\":%llu,\"dequeued_ns\":%llu,\"capture_sequence\":%u,\"sequence_gaps\":%llu,\"kernel_flags\":%u}",
        (unsigned long long)f.timestamp_ns,(unsigned long long)f.dequeued_ns,f.capture_sequence,(unsigned long long)f.sequence_gaps,f.kernel_flags);
    if(n<0||(size_t)n>=meta_size){errno=EOVERFLOW;return fail(meta,meta_size,"Camera metadata overflow");}return 0;
}
