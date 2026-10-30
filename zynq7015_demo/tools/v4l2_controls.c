/* Read-only control inventory. Does not change focus, exposure or stream state. */
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
int main(int argc,char **argv){
    int fd=open(argc>1?argv[1]:"/dev/video0",O_RDWR|O_NONBLOCK),focus=0,count=0;
    struct v4l2_queryctrl q;memset(&q,0,sizeof(q));q.id=V4L2_CTRL_FLAG_NEXT_CTRL;
    if(fd<0){perror("open camera");return 1;}
    while(!ioctl(fd,VIDIOC_QUERYCTRL,&q)){
        struct v4l2_control c;memset(&c,0,sizeof(c));c.id=q.id;
        int rc=ioctl(fd,VIDIOC_G_CTRL,&c);
        printf("id=0x%08x name=%.*s type=%u min=%d max=%d step=%d default=%d flags=0x%x current=%d read_rc=%d\n",q.id,32,q.name,q.type,q.minimum,q.maximum,q.step,q.default_value,q.flags,c.value,rc);
        if((q.id==V4L2_CID_FOCUS_ABSOLUTE||q.id==V4L2_CID_FOCUS_AUTO)&&!(q.flags&V4L2_CTRL_FLAG_DISABLED))focus=1;
        if(++count>256){fprintf(stderr,"Control count bound exceeded\n");close(fd);return 1;}
        q.id|=V4L2_CTRL_FLAG_NEXT_CTRL;
    }
    int err=errno;close(fd);
    if(err!=EINVAL){fprintf(stderr,"Control enumeration failed: %s\n",strerror(err));return 1;}
    printf("READ_ONLY_CONTROL_QUERY controls=%d focus_control_present=%d\n",count,focus);return 0;
}
