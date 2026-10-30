// Read-only reconstruction with the accepted native extractor; no SLAM backend.
#include "ORBextractor.h"
#include <opencv2/core/ocl.hpp>
#include <fstream>
#include <iostream>
#include <memory>
#include <set>
class Counter : public ORB_SLAM3::ORBextractor {
public:
    explicit Counter(int n):ORBextractor(n,1.2f,8,20,7){}
    const std::vector<int>& budgets() const {return mnFeaturesPerLevel;}
};
int main(int argc,char**argv) try {
    if(argc!=4)throw std::runtime_error("input_dir timestamps output_csv required");
    cv::setNumThreads(1);cv::ocl::setUseOpenCL(false);
    Counter normal(1000),initial(5000);std::ifstream stamps(argv[2]);std::ofstream out(argv[3]);
    if(!stamps||!out)throw std::runtime_error("Cannot open input/output");
    out<<"timestamp_ns,role,level,width,height,budget,selected,virtual_grid_cells,virtual_empty_cells\n";
    uint64_t ns;size_t frames=0;
    while(stamps>>ns){
        cv::Mat image=cv::imread(std::string(argv[1])+"/"+std::to_string(ns)+".pgm",0);
        if(image.empty())throw std::runtime_error("Missing original prepared image");
        for(int role:{0,1}){
            Counter& ex=role?initial:normal;std::vector<cv::KeyPoint> keys;cv::Mat desc;std::vector<int> lap{0,1000};
            ex(image,cv::Mat(),keys,desc,lap);const auto scales=ex.GetScaleFactors();
            for(int l=0;l<8;++l){int w=ex.mvImagePyramid[l].cols,h=ex.mvImagePyramid[l].rows,b=ex.budgets()[l];
                int side=std::max(1,int(std::sqrt(double(w-32)*(h-32)/b))),cols=std::max(1,(w-32)/side),rows=std::max(1,(h-32)/side);
                int count=0;std::set<int> occupied;
                for(const auto& k:keys)if(k.octave==l){++count;int x=cvRound(k.pt.x/scales[l])-16,y=cvRound(k.pt.y/scales[l])-16;
                    x=std::max(0,std::min(cols-1,x/side));y=std::max(0,std::min(rows-1,y/side));occupied.insert(y*cols+x);}
                out<<ns<<','<<role<<','<<l<<','<<w<<','<<h<<','<<b<<','<<count<<','<<cols*rows<<','<<(cols*rows-int(occupied.size()))<<'\n';
            }
        }
        out.flush();if(!out)throw std::runtime_error("Failed CSV write");
        if(++frames%50==0)std::cout<<"NATIVE_COUNTS_PROGRESS frames="<<frames<<std::endl;
    }
    if(!stamps.eof()||!frames)throw std::runtime_error("Invalid stamps");
    std::cout<<"NATIVE_COUNTS_PASS frames="<<frames<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}
