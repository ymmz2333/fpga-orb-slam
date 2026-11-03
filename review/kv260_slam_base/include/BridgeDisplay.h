#pragma once
// Decode the SAME immutable PL packet for display; SLAM may clear its current
// key vector during a map reset, which must not replace these input features.
inline std::vector<cv::KeyPoint> BridgeDisplayKeys(const demo::Packet&p){
    if(p.body.size()!=demo::image_bytes+128+p.count*64+1024||p.count>1000)throw std::runtime_error("Display PL record length mismatch");
    const unsigned widths[8]={960,800,667,556,463,386,322,268},heights[8]={720,600,500,417,347,289,241,201};
    float scale[8];scale[0]=1.f;for(unsigned i=1;i<8;i++)scale[i]=scale[i-1]*1.2f;
    std::vector<cv::KeyPoint> keys(p.count);
    for(unsigned i=0;i<p.count;i++){
        const auto*r=p.body.data()+demo::image_bytes+128+i*64;
        const auto x=demo::get32(r),y=demo::get32(r+4),score=demo::get32(r+8),level=demo::get32(r+12),bin=demo::get32(r+16),angle=demo::get32(r+28);
        if(level>=8||x>=widths[level]||y>=heights[level]||!score||score>255||bin>=32||angle!=bin*737280u)throw std::runtime_error("Display PL record ABI mismatch");
        auto&k=keys[i];k.pt=cv::Point2f(float(x)*scale[level],float(y)*scale[level]);k.octave=int(level);k.angle=float(angle)/65536.f;k.size=31.f*scale[level];k.response=float(score);k.class_id=-1;
        if(k.pt.x>=960||k.pt.y>=720)throw std::runtime_error("Display PL scaled coordinate mismatch");
    }
    return keys;
}
