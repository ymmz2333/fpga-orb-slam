/* ACZ7015 S1: PS_MIO47, live device-tree key0, Linux KEY_UP103.
 * Bridges fresh presses to the existing SLAM 'r' control FIFO. No PL/SD changes.
 */
#define _GNU_SOURCE
#include <linux/input.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <stdlib.h>
#define S1_CODE KEY_UP
static volatile sig_atomic_t stopped;
static void stop(int value){(void)value;stopped=1;}
static uint64_t milliseconds(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;}
struct key_state {int down;uint64_t last;};
static int press(struct key_state *s,unsigned type,unsigned code,int value,uint64_t now){
 if(type!=EV_KEY||code!=S1_CODE)return 0;
 if(value==0){s->down=0;return 0;}
 if(value!=1||s->down)return 0;
 s->down=1;if(s->last&&now-s->last<150)return 0;s->last=now;return 1;
}
static int held(int fd){unsigned char bits[(KEY_MAX+8)/8];memset(bits,0,sizeof(bits));if(ioctl(fd,EVIOCGKEY(sizeof(bits)),bits)<0)return -1;return !!(bits[S1_CODE/8]&(1u<<(S1_CODE%8)));}
static int state_file(const char *path,unsigned requests,unsigned resyncs){
 char temp[512];if(snprintf(temp,sizeof(temp),"%s.tmp",path)>=(int)sizeof(temp))return -1;
 FILE *file=fopen(temp,"w");if(!file)return -1;
 int rc=fprintf(file,"{\"button\":\"S1\",\"gpio\":47,\"linux_keycode\":103,\"device_grabbed\":true,\"relocalization_requests\":%u,\"resyncs\":%u,\"last_update_monotonic_ms\":%llu,\"action\":\"reload installed fixed map and start a fresh localization track; preserve stored map\",\"claim\":\"FIFO delivery; verify map hash and localization state\"}\n",requests,resyncs,(unsigned long long)milliseconds());
 if(fclose(file)||rc<0)return -1;return rename(temp,path);
}
static int selftest(void){
 struct key_state s={0,0};unsigned n=0;
 n+=press(&s,EV_KEY,S1_CODE,1,1000);n+=press(&s,EV_KEY,S1_CODE,1,1001);n+=press(&s,EV_KEY,S1_CODE,2,1200);
 n+=press(&s,EV_KEY,KEY_ENTER,1,1201);n+=press(&s,EV_KEY,S1_CODE,0,1202);
 n+=press(&s,EV_KEY,S1_CODE,1,1203);n+=press(&s,EV_KEY,S1_CODE,0,1204);
 n+=press(&s,EV_KEY,S1_CODE,1,1250);n+=press(&s,EV_KEY,S1_CODE,0,1251);
 n+=press(&s,EV_KEY,S1_CODE,1,1400);if(n!=3)return 1;
 s.down=1;if(press(&s,EV_KEY,S1_CODE,1,1600))return 1;
 if(press(&s,EV_KEY,S1_CODE,0,1601)||!press(&s,EV_KEY,S1_CODE,1,1602))return 1;
 int pipes[2];if(pipe(pipes))return 1;char byte=0;if(write(pipes[1],"r",1)!=1||read(pipes[0],&byte,1)!=1||byte!='r')return 1;close(pipes[0]);close(pipes[1]);
 puts("S1_FRESH_PRESS_HOLD_REPEAT_WRONG_KEY_BOUNCE_INITIAL_HELD_FIFO_PASS");return 0;
}
int main(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"--selftest"))return selftest();
 const char *base="/opt/orb-demo/";
 if(argc!=4||strcmp(argv[1],"/dev/input/event0")||strcmp(argv[2],"/run/orb-demo.lock/control.fifo")||strncmp(argv[3],base,strlen(base))||strstr(argv[3],"..")||!strstr(argv[3],"/runs/")){
  fprintf(stderr,"S1 requires the demo control FIFO and scoped demo run status path\n");return 2;}
 int input=open(argv[1],O_RDONLY|O_NONBLOCK|O_CLOEXEC);if(input<0){perror("S1 input");return 1;}
 char name[80]={0};if(ioctl(input,EVIOCGNAME(sizeof(name)-1),name)<0||strcmp(name,"keys")){fprintf(stderr,"S1 device identity mismatch\n");close(input);return 1;}
 int fifo=open(argv[2],O_WRONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);struct stat stat;
 if(fifo<0||fstat(fifo,&stat)||!S_ISFIFO(stat.st_mode)||(stat.st_mode&077)!=0){fprintf(stderr,"S1 dedicated FIFO unavailable\n");close(input);return 1;}
 if(ioctl(input,EVIOCGRAB,1)){perror("S1 exclusive grab");close(input);close(fifo);return 1;}
 struct key_state key={held(input),0};if(key.down<0){close(input);close(fifo);return 1;}
 signal(SIGINT,stop);signal(SIGTERM,stop);signal(SIGPIPE,SIG_IGN);
 unsigned requests=0,resyncs=0;int syncing=0,rc=0;
 if(state_file(argv[3],requests,resyncs)){rc=1;goto finish;}
 while(!stopped){
  struct pollfd p={input,POLLIN,0};int ready=poll(&p,1,1000);if(ready<0){if(errno==EINTR)continue;rc=1;break;}if(!ready)continue;
  if(p.revents&(POLLERR|POLLHUP|POLLNVAL)){rc=1;break;}
  struct input_event events[16];ssize_t bytes=read(input,events,sizeof(events));
  if(bytes<0&&(errno==EAGAIN||errno==EINTR))continue;if(bytes<=0||bytes%(ssize_t)sizeof(events[0])){rc=1;break;}
  for(size_t i=0;i<(size_t)bytes/sizeof(events[0]);i++){
   struct input_event *e=&events[i];
   if(e->type==EV_SYN&&e->code==SYN_DROPPED){syncing=1;continue;}
   if(syncing){if(e->type==EV_SYN&&e->code==SYN_REPORT){key.down=held(input);if(key.down<0){rc=1;break;}syncing=0;resyncs++;if(state_file(argv[3],requests,resyncs)){rc=1;break;}}continue;}
   if(press(&key,e->type,e->code,e->value,milliseconds())){
    if(write(fifo,"r",1)!=1){perror("S1 FIFO delivery");rc=1;break;}
    requests++;if(state_file(argv[3],requests,resyncs)){rc=1;break;}
   }
  }
  if(rc)break;
 }
finish:
 ioctl(input,EVIOCGRAB,0);close(input);close(fifo);return rc;
}
