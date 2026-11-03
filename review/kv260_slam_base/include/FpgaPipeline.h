// GPL-3.0-or-later. Fixed-credit transport; no CPU feature fallback.
#ifndef ORB_SLAM3_FPGA_PIPELINE_H
#define ORB_SLAM3_FPGA_PIPELINE_H
#include "FpgaORB.h"
#include <condition_variable>
#include <deque>
#include <exception>
#include <mutex>
#include <thread>
namespace ORB_SLAM3 {
class FpgaPipeline : private FpgaORB {
    using Clock=std::chrono::steady_clock;
    struct Frame {
        uint64_t id=0,timestamp=0;
        cv::Mat image;
        uint8_t header[64]={};
        unsigned count=0;
        std::vector<uint8_t> payload;
        Clock::time_point submitted,start,ready;
    };
    std::mutex mutex;
    std::condition_variable changed;
    std::deque<Frame> inputs,pending,results;
    std::thread tx,rx;
    bool stopping=false;
    std::exception_ptr failure;
    unsigned outstanding=0,high=0,input_high=0,result_high=0;
    uint64_t submitted_count=0,sent_count=0,received_count=0,consumed_count=0,last_timestamp=0;
    void check() {
        if(failure)std::rethrow_exception(failure);
        require(!stopping,"pipeline stopped");
    }
    void failed() {
        std::lock_guard<std::mutex> lock(mutex);
        if(!failure)failure=std::current_exception();
        stopping=true;
        ::shutdown(fd,SHUT_RDWR);changed.notify_all();
    }
    void send_loop() {
        try {
            for(;;) {
                Frame f;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    changed.wait(lock,[&]{return stopping||!inputs.empty();});
                    if(stopping)return;
                    f=std::move(inputs.front());inputs.pop_front();
                }
                uint8_t h[64]={};std::memcpy(h,"ORB60NET",8);orb_put32(h+8,0x00400001u);
                orb_put32(h+12,ORB60_FRAME);orb_put64(h+16,f.id);orb_put64(h+24,f.timestamp);
                orb_put32(h+32,960);orb_put32(h+36,720);
                // Both extractors have the identical fixed1000-point profile.
                // Transport role0 is independent of SLAM's future initialization state.
                orb_put32(h+40,0);orb_put32(h+44,1000);orb_put32(h+48,ORB60_IMAGE_BYTES);
                orb_put32(h+56,orb_crc32(f.image.data,ORB60_IMAGE_BYTES));f.start=Clock::now();
                {
                    std::lock_guard<std::mutex> lock(mutex);Frame identity=f;identity.image.release();
                    pending.push_back(std::move(identity));changed.notify_all();
                }
                transfer(h,64,true);transfer(f.image.data,ORB60_IMAGE_BYTES,true);
                {std::lock_guard<std::mutex> lock(mutex);++sent_count;changed.notify_all();}
            }
        }catch(...){failed();}
    }
    void receive_loop() {
        try {
            for(;;) {
                Frame f;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    changed.wait(lock,[&]{return stopping||!pending.empty();});
                    if(stopping)return;
                    f=std::move(pending.front());pending.pop_front();
                }
                auto *h=f.header;transfer(h,64,false);
                require(std::memcmp(h,"ORB60NET",8)==0&&orb_get32(h+8)==0x00400001u
                    &&orb_get32(h+12)==ORB60_RESULT&&orb_get64(h+16)==f.id&&orb_get64(h+24)==f.timestamp
                    &&orb_get32(h+32)==960&&orb_get32(h+36)==720&&orb_get32(h+40)==0,"pipeline reply identity/ABI");
                f.count=orb_get32(h+44);unsigned bytes=orb_get32(h+48);
                require(bytes<=ORB60_RESULT_MAX,"pipeline reply capacity");f.payload.resize(bytes);
                transfer(f.payload.data(),bytes,false);
                require(orb_get32(h+56)==orb_crc32(f.payload.data(),bytes),"pipeline reply CRC");
                require(orb_get32(h+52)==0&&orb_get32(h+60)==0,"hardware error or simulated result refused");
                require(f.count<=1000&&bytes==128+f.count*64+1024,"pipeline result length");f.ready=Clock::now();
                {
                    std::lock_guard<std::mutex> lock(mutex);++received_count;results.push_back(std::move(f));
                    require(results.size()<=3,"result credit overflow");
                    result_high=std::max(result_high,unsigned(results.size()));changed.notify_all();
                }
            }
        }catch(...){failed();}
    }
public:
    explicit FpgaPipeline(const std::string& endpoint) {
        connect(endpoint);(void)orb_crc32(nullptr,0);
        try {tx=std::thread(&FpgaPipeline::send_loop,this);rx=std::thread(&FpgaPipeline::receive_loop,this);}
        catch(...) {abort();throw;}
    }
    ~FpgaPipeline(){abort();}
    void abort() {
        {std::lock_guard<std::mutex> lock(mutex);stopping=true;::shutdown(fd,SHUT_RDWR);changed.notify_all();}
        if(tx.joinable())tx.join();
        if(rx.joinable())rx.join();
    }
    void submit(uint64_t timestamp,const cv::Mat& image) {
        require(image.type()==CV_8UC1&&image.cols==960&&image.rows==720,"pipeline960x720 GRAY8 required");
        std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopping||outstanding<3;});check();
        require(timestamp>last_timestamp,"pipeline timestamps must increase");last_timestamp=timestamp;
        Frame f;f.id=++submitted_count;f.timestamp=timestamp;f.image=image.clone();f.submitted=Clock::now();
        inputs.push_back(std::move(f));++outstanding;high=std::max(high,outstanding);
        input_high=std::max(input_high,unsigned(inputs.size()));changed.notify_all();
    }
    int consume(uint64_t timestamp,int role,ORBextractor *extractor,std::vector<cv::KeyPoint>& keys,
                cv::Mat& descriptors,double& wait_ms,double& decode_ms) {
        auto start=Clock::now();Frame f;
        {
            std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopping||!results.empty();});check();
            require(results.front().timestamp==timestamp&&results.front().id==consumed_count+1,"SLAM frame order mismatch");
            f=std::move(results.front());results.pop_front();++consumed_count;--outstanding;changed.notify_all();
        }
        wait_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
        decode(f.payload,f.count,extractor,keys,descriptors,decode_ms);
        const double network_ms=std::chrono::duration<double,std::milli>(f.ready-f.start).count();
        const double latency_ms=std::chrono::duration<double,std::milli>(Clock::now()-f.submitted).count();
        std::cout<<"FPGA_ORB_NET frame="<<f.id<<" role="<<role<<" count="<<f.count
                 <<" engine_ns="<<orb_get64(f.payload.data()+64)<<" network_ms="<<network_ms
                 <<" wait_ms="<<wait_ms<<" latency_ms="<<latency_ms
                 <<" record_crc="<<orb_crc32(f.payload.data()+128,f.count*64)<<" cpu_orb=0"<<std::endl;
        return int(f.count);
    }
    void finish() {
        {
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock,[&]{return stopping||sent_count==submitted_count;});check();
            require(!outstanding&&submitted_count==received_count&&received_count==consumed_count
                    &&inputs.empty()&&pending.empty()&&results.empty(),"pipeline incomplete drain");
            std::cout<<"FPGA_PIPELINE_SUMMARY sent="<<sent_count<<" received="<<received_count
                     <<" consumed="<<consumed_count<<" max_inflight="<<high<<" max_input="<<input_high
                     <<" max_results="<<result_high<<std::endl;
        }
        abort();
    }
};
}
#endif
