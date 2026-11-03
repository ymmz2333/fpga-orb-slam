// Concurrency protocol unit gate; does not emulate SLAM or board hardware.
#include "KvMapperProgress.h"
#include <chrono>
#include <future>
#include <iostream>
#include <stdexcept>
#include <thread>
namespace {
void require(bool value){if(!value)throw std::runtime_error("Mapper handoff unit failed");}
bool rejected(){try{KvMapperProgress::wait(5);return false;}catch(const std::runtime_error&){return true;}}
}
int main(){try {
    using namespace KvMapperProgress;int a=0,b=0;
    submitted(&a);auto task=std::async(std::launch::async,[]{return wait(1000);});
    require(task.wait_for(std::chrono::milliseconds(5))==std::future_status::timeout);published(&a);require(task.get()>=1);
    auto state=counts();require(state.submitted==1&&state.published==1&&state.pending==0);
    submitted(&a);submitted(&b);published(&a);require(rejected());published(&b);wait(5);
    reset_for_test();published(&a);require(rejected());
    reset_for_test();submitted(&a);submitted(&a);require(rejected());
    reset_for_test();submitted(&a);require(rejected());reset_for_test();
    int handles[65];for(auto& handle:handles)submitted(&handle);require(rejected());reset_for_test();
    // Publication completes before later background work. It must not force
    // the caller to wait for the rest of a local optimization cycle.
    submitted(&a);std::promise<void> published_signal;std::promise<void> finish;
    auto finish_signal=finish.get_future();auto later=std::async(std::launch::async,[&]{published(&a);published_signal.set_value();finish_signal.wait();});
    published_signal.get_future().wait();wait(5);require(later.wait_for(std::chrono::milliseconds(0))==std::future_status::timeout);
    finish.set_value();later.get();
    std::cout<<"MAPPER_PUBLICATION_PROTOCOL_PASS\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
