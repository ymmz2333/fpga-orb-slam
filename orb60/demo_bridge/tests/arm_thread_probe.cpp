#include <cstdio>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <pthread.h>
static void* function(void*){return nullptr;}
int main(){setbuf(stdout,nullptr);pthread_t p{};int rc=pthread_create(&p,nullptr,function,nullptr);std::printf("PTHREAD_CREATE rc=%d\n",rc);if(!rc)pthread_join(p,nullptr);
    try{std::mutex m;std::condition_variable cv;bool done=false;std::thread t([&]{std::lock_guard<std::mutex>l(m);done=true;cv.notify_all();});
        {std::unique_lock<std::mutex>l(m);cv.wait(l,[&]{return done;});}t.join();std::puts("THREAD_CONDITION_PASS");return rc?1:0;
    }catch(const std::exception&e){std::printf("THREAD_FAILED %s\n",e.what());return 1;}}
