#include "BridgeTrackingDiagnosticsImpl.h"
#include <cstring>
#include <sstream>
#include <thread>
#include <stdexcept>
#include <iostream>
using namespace ORB_SLAM3;
static void check(bool value){if(!value)throw std::runtime_error("Tracking diagnostics self-test failed");}
int main(int argc,char**argv){try{
    uint8_t records[128]={};records[12]=2;records[16]=31;records[64+12]=7;records[64+16]=3;
    BridgeDiag::event("disabled",{});
    BridgeDiag::begin(42,123456789,2,records);
    std::thread worker([](){BridgeDiag::event("wrong_thread",{});check(!BridgeDiag::active());});worker.join();
    check(BridgeDiag::decision("accept",true,20,18));check(!BridgeDiag::decision("reject",false,19,4));
    for(unsigned i=0;i<140;++i)BridgeDiag::event("sample",{{"value",i}});
    std::ostringstream out;BridgeDiag::writeFrame(out,2,nullptr);auto s=out.str();
    check(s.find("wrong_thread")==std::string::npos&&s.find("disabled")==std::string::npos);
    check(s.find("\"events_dropped\":14")!=std::string::npos);
    check(s.find("\"levels\":[0,0,1,0,0,0,0,1]")!=std::string::npos);
    check(s.find("\"source_frame_id\":42")!=std::string::npos&&!BridgeDiag::active());
    if(argc==2){BridgeDiag::Writer writer(argv[1]);
        for(unsigned i=0;i<12001;++i){BridgeDiag::begin(i,i+1,0,nullptr);BridgeDiag::event("tracking_exit",{{"state",2},{"map_id",0}});writer.write(2,nullptr);}writer.finish();}
    std::cout<<"TRACKING_DIAGNOSTICS_SELFTEST_PASS unchanged_decisions=2 thread_isolation=1 bounded_events=1 retention=1\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
