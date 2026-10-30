#define _GNU_SOURCE
#include <sched.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static pid_t number(const char *text){char *end;errno=0;long n=strtol(text,&end,10);if(errno||!*text||*end||n<=1||n>INT_MAX)return -1;return (pid_t)n;}
int main(int argc,char **argv){
 cpu_set_t mask;CPU_ZERO(&mask);
 if(argc==2&&!strcmp(argv[1],"--probe")){
  if(sched_getaffinity(0,sizeof(mask),&mask)){perror("get affinity");return 1;}
  printf("{\"mode\":\"read_only_probe\",\"cpu0\":%d,\"cpu1\":%d,\"allowed_count\":%d}\n",CPU_ISSET(0,&mask),CPU_ISSET(1,&mask),CPU_COUNT(&mask));return 0;
 }
 if(argc!=4||strcmp(argv[1],"--set-capture"))return 2;
 pid_t leader=number(argv[2]),tid=number(argv[3]);if(leader<=1||tid<=1||leader==tid)return 2;
 char path[128],command[4096];snprintf(path,sizeof(path),"/proc/%d/cmdline",leader);
 FILE *file=fopen(path,"rb");if(!file)return 3;size_t count=fread(command,1,sizeof(command)-1,file);fclose(file);
 if(count==0||count==sizeof(command)-1)return 3;
 for(size_t i=0;i<count;i++)if(command[i]==0)command[i]=' ';command[count]=0;
 const char *prefix="./bin/zynq-slam ";
 const char *output="--output /opt/zynq-slam/experiments/slam60_camera_20261024_180726/camera-s1/";
 if(strncmp(command,prefix,strlen(prefix))||!strstr(command,output))return 3;
 snprintf(path,sizeof(path),"/proc/%d/task/%d/status",leader,tid);
 file=fopen(path,"r");if(!file)return 3;int group=-1;while(fgets(command,sizeof(command),file))if(sscanf(command,"Tgid: %d",&group)==1)break;fclose(file);
 if(group!=leader)return 3;
 if(sched_getaffinity(tid,sizeof(mask),&mask)){perror("capture get affinity");return 1;}
 if(CPU_COUNT(&mask)!=1||!CPU_ISSET(0,&mask))return 3;
 CPU_ZERO(&mask);CPU_SET(0,&mask);CPU_SET(1,&mask);
 if(sched_setaffinity(tid,sizeof(mask),&mask)){perror("capture set affinity");return 1;}
 CPU_ZERO(&mask);if(sched_getaffinity(tid,sizeof(mask),&mask))return 1;
 if(CPU_COUNT(&mask)!=2||!CPU_ISSET(0,&mask)||!CPU_ISSET(1,&mask))return 1;
 printf("{\"mode\":\"capture_only_mask3\",\"leader\":%d,\"capture_tid\":%d,\"cpu0\":true,\"cpu1\":true}\n",leader,tid);return 0;
}
