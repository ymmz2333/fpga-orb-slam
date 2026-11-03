// Codec-only synthetic fixtures; no SLAM, ORB or DPU acceptance is inferred.
#include <opencv2/imgcodecs.hpp>
#include <opencv2/core.hpp>
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <vector>
uint32_t bmp_rng=7015260;
uint8_t next_byte(){bmp_rng^=bmp_rng<<13;bmp_rng^=bmp_rng>>17;bmp_rng^=bmp_rng<<5;return uint8_t(bmp_rng);}
int main(int argc,char** argv){try {
    if(argc!=2)return 2;
    std::vector<double> jpeg_ms,bmp_ms;
    for(int k=0;k<20;++k) {
        cv::Mat image(720,960,k<18?CV_8UC3:CV_8UC1);
        for(int r=0;r<image.rows;++r)for(int c=0;c<image.cols*image.channels();++c)
            image.ptr<uint8_t>(r)[c]=k%3==0?uint8_t(r+c):k%3==1?uint8_t(c%3==0?255:0):next_byte();
        std::vector<uint8_t> packet,legacy;
        const auto a=std::chrono::steady_clock::now();
        if(!cv::imencode(".jpg",image,legacy,{cv::IMWRITE_JPEG_QUALITY,80}))return 3;
        const auto b=std::chrono::steady_clock::now();
        if(!cv::imencode(".bmp",image,packet)||packet.size()>4*1024*1024||packet[0]!='B'||packet[1]!='M')return 4;
        const auto d=std::chrono::steady_clock::now();
        auto decoded=cv::imdecode(packet,cv::IMREAD_UNCHANGED);
        if(decoded.size()!=image.size()||decoded.type()!=image.type()||cv::norm(image,decoded,cv::NORM_INF)!=0)return 5;
        jpeg_ms.push_back(std::chrono::duration<double,std::milli>(b-a).count());bmp_ms.push_back(std::chrono::duration<double,std::milli>(d-b).count());
        if(k<3) {
            const auto name=std::string(argv[1])+"/case"+std::to_string(k);
            std::ofstream raw(name+".bgr",std::ios::binary),bmp(name+".bmp",std::ios::binary);
            raw.write(reinterpret_cast<char*>(image.data),image.total()*image.elemSize());bmp.write(reinterpret_cast<char*>(packet.data()),packet.size());
            if(!raw||!bmp)return 6;
        }
    }
    std::sort(jpeg_ms.begin(),jpeg_ms.end());std::sort(bmp_ms.begin(),bmp_ms.end());
    std::cout<<"{\"status\":\"NATIVE_BMP_LOSSLESS_CODEC_PASS\",\"cases\":20,\"color_cases\":18,\"gray_cases\":2,\"width\":960,\"height\":720,\"jpeg_median_ms\":"<<(jpeg_ms[9]+jpeg_ms[10])/2<<",\"bmp_median_ms\":"<<(bmp_ms[9]+bmp_ms[10])/2<<",\"scope\":\"Synthetic codec component only; no whole FPS or hardware inference acceptance\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
