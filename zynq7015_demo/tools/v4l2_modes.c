/* Read-only camera capability/format inventory; never starts or changes a stream. */
#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>

static int query(int fd,unsigned long request,void *arg) {
    int result;do {result=ioctl(fd,request,arg);}while(result<0&&errno==EINTR);return result;
}
static void quoted(const unsigned char *s,unsigned limit) {
    putchar('"');for(unsigned i=0;i<limit&&s[i];i++) {
        unsigned ch=s[i];if(ch=='"'||ch=='\\'){putchar('\\');putchar((int)ch);}
        else if(ch<32||ch>126)printf("\\u%04x",ch);else putchar((int)ch);
    }putchar('"');
}
static void fourcc(uint32_t value) {
    unsigned char name[5]={(unsigned char)value,(unsigned char)(value>>8),(unsigned char)(value>>16),(unsigned char)(value>>24),0};quoted(name,4);
}
int main(int argc,char **argv) {
    const char *path=argc>1?argv[1]:"/dev/video0";
    int fd=open(path,O_RDWR|O_NONBLOCK);if(fd<0){perror("open camera");return 1;}
    struct v4l2_capability cap;memset(&cap,0,sizeof(cap));
    if(query(fd,VIDIOC_QUERYCAP,&cap)){perror("camera capability");close(fd);return 1;}
    printf("{\"read_only\":true,\"driver\":");quoted(cap.driver,sizeof(cap.driver));printf(",\"card\":");quoted(cap.card,sizeof(cap.card));
    printf(",\"bus_info\":");quoted(cap.bus_info,sizeof(cap.bus_info));printf(",\"capabilities\":%u,\"device_caps\":%u",cap.capabilities,cap.device_caps);
    struct v4l2_format current;memset(&current,0,sizeof(current));current.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if(!query(fd,VIDIOC_G_FMT,&current)) {
        printf(",\"current\":{\"fourcc\":");fourcc(current.fmt.pix.pixelformat);
        printf(",\"width\":%u,\"height\":%u,\"stride\":%u,\"sizeimage\":%u,\"colorspace\":%u,\"ycbcr_enc\":%u,\"quantization\":%u,\"xfer_func\":%u}",
            current.fmt.pix.width,current.fmt.pix.height,current.fmt.pix.bytesperline,current.fmt.pix.sizeimage,current.fmt.pix.colorspace,current.fmt.pix.ycbcr_enc,current.fmt.pix.quantization,current.fmt.pix.xfer_func);
    }
    printf(",\"formats\":[");unsigned formats=0;
    for(unsigned i=0;i<64;i++) {
        struct v4l2_fmtdesc f;memset(&f,0,sizeof(f));f.index=i;f.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
        if(query(fd,VIDIOC_ENUM_FMT,&f)){if(errno==EINVAL)break;perror("enumerate format");close(fd);return 1;}
        if(formats++)putchar(',');printf("{\"fourcc\":");fourcc(f.pixelformat);printf(",\"description\":");quoted(f.description,sizeof(f.description));
        printf(",\"flags\":%u,\"sizes\":[",f.flags);unsigned sizes=0;
        for(unsigned j=0;j<64;j++) {
            struct v4l2_frmsizeenum size;memset(&size,0,sizeof(size));size.index=j;size.pixel_format=f.pixelformat;
            if(query(fd,VIDIOC_ENUM_FRAMESIZES,&size)){if(errno==EINVAL)break;perror("enumerate size");close(fd);return 1;}
            if(sizes++)putchar(',');
            if(size.type==V4L2_FRMSIZE_TYPE_DISCRETE)printf("{\"width\":%u,\"height\":%u}",size.discrete.width,size.discrete.height);
            else {printf("{\"type\":%u,\"min_width\":%u,\"max_width\":%u,\"min_height\":%u,\"max_height\":%u}",size.type,size.stepwise.min_width,size.stepwise.max_width,size.stepwise.min_height,size.stepwise.max_height);break;}
        }
        printf("],\"intervals_1280x720\":[");unsigned intervals=0;
        for(unsigned j=0;j<64;j++) {
            struct v4l2_frmivalenum rate;memset(&rate,0,sizeof(rate));rate.index=j;rate.pixel_format=f.pixelformat;rate.width=1280;rate.height=720;
            if(query(fd,VIDIOC_ENUM_FRAMEINTERVALS,&rate)){if(errno==EINVAL)break;perror("enumerate rate");close(fd);return 1;}
            if(intervals++)putchar(',');
            if(rate.type==V4L2_FRMIVAL_TYPE_DISCRETE)printf("{\"numerator\":%u,\"denominator\":%u}",rate.discrete.numerator,rate.discrete.denominator);
            else {printf("{\"type\":%u}",rate.type);break;}
        }
        printf("]}");
    }
    printf("]}\n");close(fd);return formats?0:1;
}
