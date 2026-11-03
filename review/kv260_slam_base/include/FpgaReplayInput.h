// GPL-3.0-or-later. Bounded image producer runs while TrackMonocular consumes.
#ifndef ORB_SLAM3_FPGA_REPLAY_INPUT_H
#define ORB_SLAM3_FPGA_REPLAY_INPUT_H
#include "FeatureIO.h"
#include <opencv2/imgcodecs.hpp>
#include <condition_variable>
#include <deque>
#include <exception>
#include <mutex>
#include <thread>
namespace ORB_SLAM3 {
class FpgaReplayInput {
    std::mutex mutex;std::condition_variable changed;
    std::deque<std::pair<size_t,cv::Mat>> ready;
    std::thread producer;bool stopped=false,done=false;std::exception_ptr failure;
public:
    explicit FpgaReplayInput(const std::vector<std::string>& paths) {
        FeatureIO::StartPipeline(); // After vocabulary/System startup, before producer.
        producer=std::thread([this,&paths]{
            try {
                for(size_t i=0;i<paths.size();++i) {
                    {
                        std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopped||ready.size()<3;});
                        if(stopped)return;
                    }
                    cv::Mat image=cv::imread(paths[i],cv::IMREAD_UNCHANGED);
                    if(image.empty())throw std::runtime_error("FPGA producer failed to load "+paths[i]);
                    size_t base=paths[i].find_last_of('/')+1;
                    uint64_t ts=std::stoull(paths[i].substr(base,paths[i].size()-base-4));
                    FeatureIO::QueueFrame(ts,image);
                    {
                        std::lock_guard<std::mutex> lock(mutex);if(stopped)return;
                        ready.emplace_back(i,std::move(image));changed.notify_all();
                    }
                }
            }catch(...) {std::lock_guard<std::mutex> lock(mutex);failure=std::current_exception();}
            std::lock_guard<std::mutex> lock(mutex);done=true;changed.notify_all();
        });
    }
    cv::Mat get(size_t index) {
        std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return failure||done||!ready.empty();});
        if(failure)std::rethrow_exception(failure);
        if(ready.empty()||ready.front().first!=index)throw std::runtime_error("FPGA image queue order");
        cv::Mat image=std::move(ready.front().second);ready.pop_front();changed.notify_all();return image;
    }
    void finish() {if(producer.joinable())producer.join();FeatureIO::FinishPipeline();}
    ~FpgaReplayInput() {
        {std::lock_guard<std::mutex> lock(mutex);stopped=true;changed.notify_all();}
        FeatureIO::AbortPipeline();if(producer.joinable())producer.join();
    }
};
}
#endif
