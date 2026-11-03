#include <ap_int.h>
#include <fstream>
#include <iostream>
#include <string>
#include <cmath>
#include <stdint.h>
extern "C" unsigned point_project_hls(const ap_uint<128>*,const ap_uint<128>*,ap_uint<256>*,ap_uint<256>*,unsigned,unsigned);
template<int W> void load(std::string path,ap_uint<W>* data,unsigned n) {
    std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("missing vector "+path);
    for(unsigned i=0;i<n;i++)for(int j=0;j<W/32;j++){uint32_t x;f.read((char*)&x,4);if(!f)throw std::runtime_error("truncated vector");data[i].range(j*32+31,j*32)=x;}
}
static float f32(uint32_t u){union{uint32_t u;float f;}x;x.u=u;return x.f;}
int main(int argc,char**argv) {
    if(argc!=3)return 2;std::string root=argv[1];std::ifstream list(root+"/"+argv[2]+".txt");
    ap_uint<128>* in=new ap_uint<128>[172800];ap_uint<256>* out=new ap_uint<256>[172800];
    ap_uint<256>* expected=new ap_uint<256>[172800];ap_uint<128> config[6];ap_uint<256> stats[1],gold[1];
    std::string name;unsigned count,cap,stored,written;unsigned tests=0;
    while(list>>name>>count>>cap>>stored>>written){
        load(root+"/"+name+"_samples.bin",in,stored);load(root+"/"+name+"_config.bin",config,6);
        load(root+"/"+name+"_points.bin",expected,written);load(root+"/"+name+"_stats.bin",gold,1);
        unsigned status=point_project_hls(in,config,out,stats,count,cap);
        if(stats[0]!=gold[0] || status!=gold[0].range(127,96).to_uint()){std::cerr<<name<<" stats mismatch\n";return 1;}
        for(unsigned i=0;i<written;i++)for(int j=0;j<8;j++){
            uint32_t a=out[i].range(32*j+31,32*j),b=expected[i].range(32*j+31,32*j);
            if(j>=6 ? a!=b : (!std::isfinite(f32(a)) || std::fabs(f32(a)-f32(b))>3e-5f+3e-5f*std::fabs(f32(b)))){
                std::cerr<<name<<" point "<<i<<" field "<<j<<" mismatch\n";return 1;
            }
        }
        tests++;std::cout<<"POINT_CASE_PASS "<<name<<" "<<written<<"\n";
    }
    if(!tests)return 1;std::cout<<"POINT_PROJECT_GOLDEN_PASS "<<tests<<"\n";delete[]in;delete[]out;delete[]expected;return 0;
}
