// Fixed-correspondence solver gate. No RANSAC, feature extraction or map updates.
#include <opencv2/calib3d.hpp>
#include <opencv2/core.hpp>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>

static cv::Mat vector3(const cv::FileNode &node) {
    if (node.size()!=3) throw std::runtime_error("Invalid vector size");
    cv::Mat out(3,1,CV_64F);int i=0;
    for (const auto &value:node) out.at<double>(i++)=static_cast<double>(value);
    return out;
}
int main(int argc,char **argv) {
    try {
        if(argc!=3) throw std::runtime_error("Usage: fixed-pnp CASE.json CASE.csv");
        cv::setNumThreads(1);
        cv::FileStorage fs(argv[1],cv::FileStorage::READ);
        if(!fs.isOpened()) throw std::runtime_error("Cannot open case metadata");
        auto node=fs["k"];cv::Mat k(3,3,CV_64F);int i=0;
        if(node.size()!=3) throw std::runtime_error("Invalid camera matrix");
        for(const auto &row:node) {
            if(row.size()!=3) throw std::runtime_error("Invalid camera row");
            for(const auto &value:row) k.at<double>(i/3,i%3)=static_cast<double>(value),++i;
        }
        cv::Mat rvec=vector3(fs["initial_rvec"]),tvec=vector3(fs["initial_tvec"]);
        std::ifstream input(argv[2]);std::string line;
        if(!std::getline(input,line)) throw std::runtime_error("Missing correspondence header");
        if(!line.empty() && line.back()=='\r')line.pop_back();
        if(line!="point_id,x,y,z,u,v")throw std::runtime_error("Unexpected correspondence format");
        std::vector<cv::Point3d> xyz;std::vector<cv::Point2d> uv;
        while(std::getline(input,line)) {
            std::istringstream row(line);std::string field;double values[6];
            for(int j=0;j<6;j++) {
                if(!std::getline(row,field,','))throw std::runtime_error("Short correspondence row");
                values[j]=std::stod(field);
            }
            xyz.emplace_back(values[1],values[2],values[3]);uv.emplace_back(values[4],values[5]);
        }
        if(xyz.size()<6)throw std::runtime_error("Insufficient fixed inliers");
        if(!cv::solvePnP(xyz,uv,k,cv::noArray(),rvec,tvec,true,cv::SOLVEPNP_ITERATIVE))
            throw std::runtime_error("Fixed-inlier solvePnP failed");
        cv::Mat rcw;cv::Rodrigues(rvec,rcw);cv::Mat rwc=rcw.t(),twc=-rwc*tvec;
        std::cout<<std::setprecision(17)<<"{\"opencv\":\""<<CV_VERSION<<"\",\"twc\":[";
        for(int r=0;r<4;r++) {
            if(r)std::cout<<',';
            std::cout<<'[';
            for(int c=0;c<4;c++) {
                if(c)std::cout<<',';
                std::cout<<(r==3?(c==3?1.:0.):(c==3?twc.at<double>(r):rwc.at<double>(r,c)));
            }
            std::cout<<']';
        }
        std::cout<<"]}\n";return 0;
    } catch(const std::exception &error) {std::cerr<<error.what()<<'\n';return 1;}
}
