#include "ORBextractor.h"
#include <fstream>
#include <iostream>
using ORB_SLAM3::ORBextractor;
int main(int argc,char** argv) {
    if(argc!=2) return 2;
    std::string root=argv[1];
    std::ofstream angles(root+"/angles.csv"),grid(root+"/grid.csv"),box(root+"/box.csv"),budgets(root+"/budgets.csv");
    if(!angles||!grid||!box||!budgets)return 2;
    angles<<"bins,angle,quantized\n";
    for(int bins:{8,32}) for(float a:{0.f,5.625f,11.25f,22.499f,22.5f,22.501f,45.f,179.9f,337.5f,359.999f})
        angles<<bins<<','<<a<<','<<ORBextractor::DesignQuantize(a,bins)<<'\n';
    grid<<"case_id,x,y,response,selected,side,cols,rows,empty,shortfall\n";
    // Remainder merging, equal-score tie, score truncation, sparse/empty grids.
    for(int test=0;test<4;++test) {
        std::vector<cv::KeyPoint> keys;
        if(test!=3) for(int y=0;y<19;++y) for(int x=0;x<23;++x)
            if(test!=2 || (x==22&&y==18)) keys.emplace_back(float(x),float(y),31,-1,float((x*7+y*3)%13));
        ORBextractor::DesignLayer r;
        auto chosen=ORBextractor::DesignGrid(keys,23,19,test==1?3:17,r);
        if(chosen.empty())grid<<test<<",-1,-1,0,0,"<<r.cell_side<<','<<r.cell_cols<<','<<r.cell_rows<<','<<r.empty_cells<<','<<r.shortfall<<'\n';
        for(const auto& k:chosen)grid<<test<<','<<k.pt.x<<','<<k.pt.y<<','<<k.response<<",1,"<<r.cell_side<<','<<r.cell_cols<<','<<r.cell_rows<<','<<r.empty_cells<<','<<r.shortfall<<'\n';
    }
    box<<"rounding,y,x,value\n";
    cv::Mat image(8,10,CV_8UC1);
    for(int y=0;y<image.rows;++y)for(int x=0;x<image.cols;++x) image.at<uchar>(y,x)=uchar((y*19+x*29+y*x*7)%256);
    for(int rounding:{0,1}) {
        cv::Mat result=ORBextractor::DesignBox2(image,rounding);
        for(int y=0;y<result.rows;++y)for(int x=0;x<result.cols;++x)box<<rounding<<','<<y<<','<<x<<','<<int(result.at<uchar>(y,x))<<'\n';
    }
    budgets<<"n,levels,scale,level,budget\n";
    for(int n:{1000,5000})for(int levels:{1,2,8}) {
        float scale=levels==2?2.f:1.2f; ORBextractor e(n,scale,levels,20,7);
        for(int l=0;l<levels;++l)budgets<<n<<','<<levels<<','<<scale<<','<<l<<','<<e.DesignBudgets()[l]<<'\n';
    }
    std::cout<<"FIXTURE_WRITTEN\n";
}
