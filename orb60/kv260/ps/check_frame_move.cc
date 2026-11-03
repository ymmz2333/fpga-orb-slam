// Component fixture only. The probe header exposes fields without adding data.
// Compare every non-static Frame field, including private pose and IMU state.
#include "FrameProbe.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <type_traits>
#include <utility>
using ORB_SLAM3::Frame;
extern "C" size_t frame_actual_size();
extern "C" size_t frame_actual_alignment();
extern "C" size_t frame_actual_grid_offset();
extern "C" size_t frame_actual_descriptor_offset();
namespace {
void check(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
struct Writer {
    std::ostringstream out{std::ios::binary};
    template<class T> typename std::enable_if<std::is_arithmetic<T>::value>::type num(T x){out.write(reinterpret_cast<const char*>(&x),sizeof(x));}
    template<class T> void ptr(T* x){num(reinterpret_cast<uintptr_t>(x));}
    void string(const std::string& s){num(uint64_t(s.size()));out.write(s.data(),s.size());}
    void value(const cv::KeyPoint& k){num(k.pt.x);num(k.pt.y);num(k.size);num(k.angle);num(k.response);num(k.octave);num(k.class_id);}
    void value(const cv::Point2f& p){num(p.x);num(p.y);}
    template<class T> typename std::enable_if<std::is_arithmetic<T>::value>::type value(T x){num(x);}
    template<class T> void value(T* p){ptr(p);}
    template<class T> void eigen(const T& a){num(int(a.rows()));num(int(a.cols()));for(int r=0;r<a.rows();++r)for(int c=0;c<a.cols();++c)num(a(r,c));}
    void value(const Eigen::Vector3f& a){eigen(a);}
    template<class T> void vec(const std::vector<T>& v){num(uint64_t(v.size()));for(const auto& x:v)value(x);}
    template<class Map> void map(const Map& m){num(uint64_t(m.size()));for(const auto& p:m){value(p.first);value(p.second);}}
    void value(const std::vector<unsigned int>& v){vec(v);}
    void mat(const cv::Mat& m){num(m.rows);num(m.cols);num(m.type());for(int r=0;r<m.rows;++r)out.write(reinterpret_cast<const char*>(m.ptr(r)),m.cols*m.elemSize());}
    void bias(const ORB_SLAM3::IMU::Bias& b){num(b.bax);num(b.bay);num(b.baz);num(b.bwx);num(b.bwy);num(b.bwz);}
};
std::string snapshot(const Frame& f){
    Writer w;
    w.eigen(f.mTcw.matrix());w.eigen(f.mRwc);w.eigen(f.mOw);w.eigen(f.mRcw);w.eigen(f.mtcw);w.num(f.mbHasPose);
    w.eigen(f.mTlr.matrix());w.eigen(f.mTrl.matrix());w.eigen(f.mRlr);w.eigen(f.mtlr);w.eigen(f.mVw);w.num(f.mbHasVelocity);
    w.ptr(f.mpcpi);w.ptr(f.mpORBvocabulary);w.ptr(f.mpORBextractorLeft);w.ptr(f.mpORBextractorRight);w.num(f.mTimeStamp);
    w.mat(f.mK);w.eigen(f.mK_);w.mat(f.mDistCoef);w.num(f.mbf);w.num(f.mb);w.num(f.mThDepth);w.num(f.N);
    w.vec(f.mvKeys);w.vec(f.mvKeysRight);w.vec(f.mvKeysUn);w.vec(f.mvpMapPoints);w.vec(f.mvuRight);w.vec(f.mvDepth);
    w.map(f.mBowVec);w.map(f.mFeatVec);w.mat(f.mDescriptors);w.mat(f.mDescriptorsRight);w.vec(f.mvbOutlier);w.num(f.mnCloseMPs);
    for(int i=0;i<FRAME_GRID_COLS;++i)for(int j=0;j<FRAME_GRID_ROWS;++j)w.vec(f.mGrid[i][j]);
    w.bias(f.mPredBias);w.bias(f.mImuBias);w.eigen(f.mImuCalib.mTcb.matrix());w.eigen(f.mImuCalib.mTbc.matrix());
    w.eigen(f.mImuCalib.Cov.diagonal());w.eigen(f.mImuCalib.CovWalk.diagonal());w.num(f.mImuCalib.mbIsSet);
    w.ptr(f.mpImuPreintegrated);w.ptr(f.mpLastKeyFrame);w.ptr(f.mpPrevFrame);w.ptr(f.mpImuPreintegratedFrame);w.num(f.mnId);w.ptr(f.mpReferenceKF);
    w.num(f.mnScaleLevels);w.num(f.mfScaleFactor);w.num(f.mfLogScaleFactor);w.vec(f.mvScaleFactors);w.vec(f.mvInvScaleFactors);w.vec(f.mvLevelSigma2);w.vec(f.mvInvLevelSigma2);
    w.map(f.mmProjectPoints);w.map(f.mmMatchedInImage);w.string(f.mNameFile);w.num(f.mnDataset);
#ifdef REGISTER_TIMES
    w.num(f.mTimeORB_Ext);w.num(f.mTimeStereoMatch);
#endif
    w.num(f.mbIsSet);w.num(f.mbImuPreintegrated);w.ptr(f.mpMutexImu);w.ptr(f.mpCamera);w.ptr(f.mpCamera2);
    w.num(f.Nleft);w.num(f.Nright);w.num(f.monoLeft);w.num(f.monoRight);w.vec(f.mvLeftToRightMatch);w.vec(f.mvRightToLeftMatch);w.vec(f.mvStereo3Dpoints);
    for(int i=0;i<FRAME_GRID_COLS;++i)for(int j=0;j<FRAME_GRID_ROWS;++j)w.vec(f.mGridRight[i][j]);
    w.mat(f.imgLeft);w.mat(f.imgRight);w.eigen(f.T_test.matrix());
    return w.out.str();
}
void fill(Frame& f,int seed){
    const int counts[]={0,280,942,1000};const int n=counts[seed%4];
    f.mpcpi=nullptr;f.mpORBvocabulary=nullptr;f.mpORBextractorLeft=nullptr;f.mpORBextractorRight=nullptr;
    f.mTimeStamp=1.+seed*.033333333;f.mK=(cv::Mat_<float>(3,3)<<910,0,485,0,914,336,0,0,1);
    f.mK_<<910,0,485,0,914,336,0,0,1;f.mDistCoef=(cv::Mat_<float>(1,5)<<.001f,-.002f,.003f,-.004f,.005f);
    f.mbf=40;f.mb=.044f;f.mThDepth=35;f.N=n;
    f.Nleft=(seed%3==0&&n)?n/2:-1;f.Nright=f.Nleft<0?-1:n-f.Nleft;f.monoLeft=n/3;f.monoRight=n/4;
    f.mvKeys.clear();f.mvKeysRight.clear();f.mvKeysUn.clear();f.mvpMapPoints.clear();f.mvuRight.clear();f.mvDepth.clear();f.mvbOutlier.clear();
    f.mvLeftToRightMatch.clear();f.mvRightToLeftMatch.clear();f.mvStereo3Dpoints.clear();
    f.mDescriptors=cv::Mat(n,32,CV_8UC1);f.mDescriptorsRight=cv::Mat(n/3,32,CV_8UC1);
    for(int i=0;i<n;++i){
        cv::KeyPoint k(float((i*17+seed)%960),float((i*31+seed)%720),31.f,float(i%32)*11.25f,float(i%255),i%8,i);
        f.mvKeys.push_back(k);k.pt.x+=.125f;f.mvKeysUn.push_back(k);
        if(i<n/3)f.mvKeysRight.push_back(k);
        f.mvpMapPoints.push_back(reinterpret_cast<ORB_SLAM3::MapPoint*>(uintptr_t(i%7?0x10000+16*i:0)));
        f.mvuRight.push_back(i%2?-1.f:float(i));f.mvDepth.push_back(float(i+1)*.01f);f.mvbOutlier.push_back(i%9==0);
        f.mvLeftToRightMatch.push_back(i%3?i:-1);f.mvRightToLeftMatch.push_back(i%4?i:-1);
        f.mvStereo3Dpoints.emplace_back(float(i)*.01f,float(i)*-.02f,float(i)*.03f);
    }
    for(int i=0;i<n*32;++i)f.mDescriptors.data[i]=uint8_t(i*13+seed);
    for(int i=0;i<(n/3)*32;++i)f.mDescriptorsRight.data[i]=uint8_t(i*7+seed);
    f.mBowVec.clear();f.mFeatVec.clear();f.mmProjectPoints.clear();f.mmMatchedInImage.clear();
    for(int i=0;i<16;++i){f.mBowVec[i]=double(i+seed)/41.;f.mFeatVec[i]={unsigned(i),unsigned(i+1)};f.mmProjectPoints[i]=cv::Point2f(i+.25f,seed+.5f);f.mmMatchedInImage[i]=cv::Point2f(i+.5f,seed+.25f);}
    for(int i=0;i<FRAME_GRID_COLS;++i)for(int j=0;j<FRAME_GRID_ROWS;++j){
        auto& a=f.mGrid[i][j];auto& b=f.mGridRight[i][j];a.clear();b.clear();
        if(n&&((i*48+j+seed)%3==0)){a.push_back((i*17+j)%n);a.push_back((i*3+j+1)%n);}
        if(f.Nleft>0&&((i+j+seed)%5==0))b.push_back((i*7+j)%n);
    }
    f.mnCloseMPs=n/5;f.mPredBias=ORB_SLAM3::IMU::Bias(1,2,3,4,5,6);f.mImuBias=ORB_SLAM3::IMU::Bias(-1,-2,-3,-4,-5,-6);
    f.mImuCalib.Set(Sophus::SE3f(Eigen::Quaternionf::Identity(),Eigen::Vector3f(.1f,.2f,.3f)),.01f,.02f,.03f,.04f);
    f.mpImuPreintegrated=nullptr;f.mpLastKeyFrame=nullptr;f.mpPrevFrame=nullptr;f.mpImuPreintegratedFrame=nullptr;f.mnId=seed;f.mpReferenceKF=nullptr;
    f.mnScaleLevels=8;f.mfScaleFactor=1.2f;f.mfLogScaleFactor=std::log(1.2f);f.mvScaleFactors.clear();f.mvInvScaleFactors.clear();f.mvLevelSigma2.clear();f.mvInvLevelSigma2.clear();
    float scale=1;for(int i=0;i<8;++i){f.mvScaleFactors.push_back(scale);f.mvInvScaleFactors.push_back(1/scale);f.mvLevelSigma2.push_back(scale*scale);f.mvInvLevelSigma2.push_back(1/(scale*scale));scale*=1.2f;}
    f.mNameFile="owned-frame-"+std::to_string(seed);f.mnDataset=3;
    f.mTlr=Sophus::SE3f(Eigen::Quaternionf::Identity(),Eigen::Vector3f(.01f,.02f,.03f));f.mTrl=f.mTlr.inverse();f.mRlr=f.mTlr.rotationMatrix();f.mtlr=f.mTlr.translation();
    f.SetPose(Sophus::SE3f(Eigen::Quaternionf::Identity(),Eigen::Vector3f(seed*.001f,.2f,-.3f)));f.SetVelocity(Eigen::Vector3f(1,2,3));
    f.mbIsSet=true;f.mbImuPreintegrated=seed%2;f.mpMutexImu=nullptr;f.mpCamera=nullptr;f.mpCamera2=nullptr;
    f.imgLeft=cv::Mat(16,24,CV_8UC1,cv::Scalar(seed)).clone();f.imgRight=cv::Mat(16,24,CV_8UC1,cv::Scalar(seed+1)).clone();
    f.T_test=Sophus::SE3d(Eigen::Quaterniond::Identity(),Eigen::Vector3d(.01,.02,.03));
#ifdef REGISTER_TIMES
    f.mTimeORB_Ext=.1;f.mTimeStereoMatch=.2;
#endif
}
volatile uint64_t benchmark_sink=0;
}
int main(int argc,char** argv){try{
    check(argc==3,"Semantic output and benchmark iteration count required");
    check(frame_actual_size()==sizeof(Frame)&&frame_actual_alignment()==alignof(Frame),"Probe/header ABI size/alignment mismatch");
    Frame offset_probe;
    auto offset=[&](const void* p){return size_t(static_cast<const char*>(p)-reinterpret_cast<const char*>(&offset_probe));};
    check(frame_actual_grid_offset()==offset(&offset_probe.mGrid)&&frame_actual_descriptor_offset()==offset(&offset_probe.mDescriptors),"Probe/header member offsets differ");
    std::ofstream out(argv[1],std::ios::binary);unsigned transferred=0,cases=0;
    for(int i=0;i<64;++i)for(int copy_temporary=0;copy_temporary<2;++copy_temporary){
        Frame dest;
        {
            Frame source;fill(source,i);
            if(copy_temporary){
                Frame temp(source);auto* storage=temp.mvKeys.data();dest=std::move(temp);
#if FRAME_MOVE_CANDIDATE
                check(dest.mvKeys.empty()||dest.mvKeys.data()==storage,"Temporary feature storage was copied");++transferred;
#endif
                const auto before=snapshot(dest);fill(temp,71);check(snapshot(dest)==before,"Reusing moved-from temporary modified destination");
            }else{
                auto* storage=source.mvKeys.data();dest=std::move(source);
#if FRAME_MOVE_CANDIDATE
                check(dest.mvKeys.empty()||dest.mvKeys.data()==storage,"Source feature storage was copied");++transferred;
#endif
                const auto before=snapshot(dest);fill(source,73);check(snapshot(dest)==before,"Reusing moved-from source modified destination");
            }
        }
        const auto content=snapshot(dest);uint64_t length=content.size();out.write(reinterpret_cast<const char*>(&length),8);out.write(content.data(),content.size());++cases;
    }
    out.close();check(bool(out),"Incomplete semantic fixture output");
    const int iterations=std::stoi(argv[2]);check(iterations>=0&&iterations<=1000,"Bounded benchmark iterations required");
    std::vector<double> elapsed;
    if(iterations){Frame base;fill(base,59);Frame dest;
        base.mDescriptorsRight.release();base.mvKeysRight.clear();base.mvStereo3Dpoints.clear();base.mvLeftToRightMatch.clear();base.mvRightToLeftMatch.clear();base.imgLeft.release();base.imgRight.release();
        for(int repeat=0;repeat<9;++repeat){const auto start=std::chrono::steady_clock::now();
            for(int n=0;n<iterations;++n){Frame temp(base);dest=std::move(temp);benchmark_sink+=dest.mvKeys.size()+dest.mGrid[0][0].size();}
            elapsed.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/iterations);
        }
        std::sort(elapsed.begin(),elapsed.end());
    }
    std::cout<<"{\"status\":\"FRAME_ASSIGNMENT_FIXTURE_RECORDED\",\"cases\":"<<cases<<",\"candidate\":"<<(FRAME_MOVE_CANDIDATE?"true":"false")
             <<",\"storage_transfer_checks\":"<<transferred<<",\"sizeof_frame\":"<<sizeof(Frame)<<",\"alignment\":"<<alignof(Frame)
             <<",\"assignment_with_copy_constructor_ms_median\":"<<(elapsed.empty()?0:elapsed[4])<<",\"benchmark_iterations\":"<<iterations<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
