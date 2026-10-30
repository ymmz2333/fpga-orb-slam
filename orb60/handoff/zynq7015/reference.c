#include "reference.h"
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
static uint32_t little32(const unsigned char *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
int orb60_load_f32_xyz(const char *path,float *xyz,size_t capacity,size_t *count){
    FILE *f=fopen(path,"rb");unsigned char b[12];size_t n=0,got;if(!f)return -1;
    while((got=fread(b,1,12,f))!=0){
        if(got!=12||n>=capacity){fclose(f);return -2;}
        for(unsigned i=0;i<3;i++){uint32_t bits=little32(b+4*i);memcpy(xyz+3*n+i,&bits,4);if(!isfinite(xyz[3*n+i])){fclose(f);return -3;}}
        n++;
    }
    if(ferror(f)){fclose(f);return -4;}fclose(f);*count=n;return 0;
}
unsigned orb60_hamming256(const uint8_t a[32],const uint8_t b[32]){
    unsigned sum=0;for(unsigned i=0;i<32;i++){unsigned v=a[i]^b[i];while(v){v&=v-1;sum++;}}return sum;
}
int orb60_match256(const uint8_t query[32],const uint8_t *train,size_t count,unsigned maximum,unsigned *index,unsigned *distance){
    if(!query||!train||!index||!distance||count<2||count>0xffffffffu||maximum>256)return -1;
    unsigned best=257,second=257,selected=0;
    for(size_t i=0;i<count;i++){
        unsigned d=orb60_hamming256(query,train+32*i);
        if(d<best){second=best;best=d;selected=(unsigned)i;}else if(d<second)second=d;
    }
    if(best>maximum||best*5>=second*4)return 0;
    *index=selected;*distance=best;return 1;
}
int orb60_project(const float p[3],const double r[9],const double t[3],const double k[4],double uv[2]){
    double x=r[0]*p[0]+r[1]*p[1]+r[2]*p[2]+t[0],y=r[3]*p[0]+r[4]*p[1]+r[5]*p[2]+t[1],z=r[6]*p[0]+r[7]*p[1]+r[8]*p[2]+t[2];
    if(!isfinite(z)||z<=1e-6)return 0;
    uv[0]=k[0]*x/z+k[2];uv[1]=k[1]*y/z+k[3];return isfinite(uv[0])&&isfinite(uv[1]);
}
void orb60_gray_rgb565(const uint8_t *gray,uint16_t *pixels,unsigned w,unsigned h){
    for(size_t i=0;i<(size_t)w*h;i++){unsigned v=gray[i];pixels[i]=(uint16_t)((v>>3)<<11|(v>>2)<<5|(v>>3));}
}
void orb60_marker_rgb565(uint16_t *pixels,unsigned w,unsigned h,int x,int y,uint16_t color){
    for(int d=-3;d<=3;d++){
        int xx=x+d,yy=y+d;
        if(xx>=0&&(unsigned)xx<w&&y>=0&&(unsigned)y<h)pixels[(size_t)y*w+(unsigned)xx]=color;
        if(x>=0&&(unsigned)x<w&&yy>=0&&(unsigned)yy<h)pixels[(size_t)yy*w+(unsigned)x]=color;
    }
}
int orb60_line_rgb565(uint16_t *pixels,unsigned w,unsigned h,int x0,int y0,int x1,int y1,uint16_t color){
    if(x0<0||y0<0||x1<0||y1<0||(unsigned)x0>=w||(unsigned)x1>=w||(unsigned)y0>=h||(unsigned)y1>=h)return -1;
    int dx=abs(x1-x0),sx=x0<x1?1:-1,dy=-abs(y1-y0),sy=y0<y1?1:-1,error=dx+dy;
    for(;;){
        pixels[(size_t)y0*w+(unsigned)x0]=color;
        if(x0==x1&&y0==y1)break;
        int twice=2*error;
        if(twice>=dy){error+=dy;x0+=sx;}
        if(twice<=dx){error+=dx;y0+=sy;}
    }
    return 0;
}
int orb60_overlay_records_rgb565(uint16_t *pixels,unsigned w,unsigned h,const uint8_t *records,size_t bytes,unsigned count){
    if(w!=960||h!=720||count>1000||bytes!=(size_t)count*64)return -1;
    float scale[8];scale[0]=1;
    for(unsigned i=1;i<8;i++)scale[i]=scale[i-1]*1.2f;
    for(unsigned i=0;i<count;i++){
        const uint8_t *p=records+i*64;unsigned level=little32(p+12),x=little32(p),y=little32(p+4);
        if(level>=8||x>=960||y>=720)return -2;
        int u=(int)lroundf(x*scale[level]),v=(int)lroundf(y*scale[level]);
        if(u<0||v<0||(unsigned)u>=w||(unsigned)v>=h)return -2;
        orb60_marker_rgb565(pixels,w,h,u,v,0x07e0);
    }
    return 0;
}
