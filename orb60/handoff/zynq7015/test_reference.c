#include "reference.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv){
    if(argc!=2)return 2;
    char path[1024];assert(snprintf(path,sizeof(path),"%s/map-reader-fixture.bin",argv[1])>0);
    const unsigned char bytes[12]={0,0,0,0,0,0,128,63,0,0,0,64};
    FILE *file=fopen(path,"wb");assert(file);assert(fwrite(bytes,1,12,file)==12);assert(!fclose(file));
    float xyz[3];size_t count=0;assert(!orb60_load_f32_xyz(path,xyz,1,&count));assert(count==1&&xyz[0]==0&&xyz[1]==1&&xyz[2]==2);
    assert(orb60_load_f32_xyz(path,xyz,0,&count)==-2);
    file=fopen(path,"wb");assert(file);assert(fwrite(bytes,1,11,file)==11);assert(!fclose(file));
    assert(orb60_load_f32_xyz(path,xyz,1,&count)==-2);
    unsigned char invalid[12]={0,0,192,127};file=fopen(path,"wb");assert(file);assert(fwrite(invalid,1,12,file)==12);assert(!fclose(file));
    assert(orb60_load_f32_xyz(path,xyz,1,&count)==-3);
    unsigned char a[32]={0},b[32];memset(b,255,32);assert(orb60_hamming256(a,b)==256);b[0]=0;assert(orb60_hamming256(a,b)==248);
    unsigned char train[64]={0};memset(train+32,255,32);unsigned match=99,distance=99;
    assert(orb60_match256(a,train,2,64,&match,&distance)==1&&match==0&&distance==0);
    memset(train,0,64);assert(orb60_match256(a,train,2,64,&match,&distance)==0);
    const double r[9]={1,0,0,0,1,0,0,0,1},t[3]={0,0,0},k[4]={100,100,50,40};double uv[2];float p[3]={1,2,5};
    assert(orb60_project(p,r,t,k,uv));assert(fabs(uv[0]-70)<1e-12&&fabs(uv[1]-80)<1e-12);p[2]=-1;assert(!orb60_project(p,r,t,k,uv));
    unsigned char gray[3]={0,128,255};uint16_t colors[3];orb60_gray_rgb565(gray,colors,3,1);assert(colors[0]==0&&colors[1]==0x8410&&colors[2]==0xffff);
    uint16_t guard[27]={0};orb60_marker_rgb565(guard+1,5,5,0,0,0x1234);assert(guard[0]==0&&guard[26]==0);
    assert(!orb60_line_rgb565(guard+1,5,5,0,0,4,4,0xabcd));for(int i=0;i<5;i++)assert(guard[1+6*i]==0xabcd);
    assert(orb60_line_rgb565(guard+1,5,5,-1,0,4,4,1)==-1);assert(guard[0]==0&&guard[26]==0);
    static uint16_t canvas[960*720];unsigned char record[64]={5,0,0,0,7,0,0,0};record[12]=1;
    assert(!orb60_overlay_records_rgb565(canvas,960,720,record,64,1));assert(canvas[8*960+6]==0x07e0);
    record[12]=8;assert(orb60_overlay_records_rgb565(canvas,960,720,record,64,1)==-2);
    assert(orb60_overlay_records_rgb565(canvas,960,720,record,63,1)==-1);
    puts("PORTABLE_C_READER_HAMMING_PROJECTION_RGB565_TRAJECTORY_PASS");return 0;
}
