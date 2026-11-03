// Optional PS scheduling diagnostic. No matching/optimization gates change.
namespace ORB_SLAM3 {
double System::WaitForLocalMapping(unsigned timeout_ms) {
    if(!timeout_ms||timeout_ms>10000)throw std::runtime_error("Invalid bounded mapper wait");
    const auto started=std::chrono::steady_clock::now();
    for(;;) {
        if(mpLocalMapper->isFinished())throw std::runtime_error("Mapper ended during frame processing");
        if(mpLocalMapper->KeyframesInQueue()==0&&mpLocalMapper->AcceptKeyFrames())break;
        if(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count()>timeout_ms)
            throw std::runtime_error("Local mapper did not drain within bounded timeout");
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
}
}
