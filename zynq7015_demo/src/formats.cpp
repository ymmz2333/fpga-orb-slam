#include "zslam/formats.hpp"
#include "zslam/camera.hpp"
#include <cstring>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <sstream>
#include "zslam/filesystem.hpp"

namespace zslam {
namespace {
uint32_t le32(const uint8_t *p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
int32_t signed32(const uint8_t *p){uint32_t u=le32(p);int32_t v;std::memcpy(&v,&u,4);return v;}
}
void RecordDecodeCache::begin(const Camera &camera){
    std::array<uint64_t,11> signature{{uint64_t(camera.width),uint64_t(camera.height)}};
    std::array<double,9> values{{camera.fx,camera.fy,camera.cx,camera.cy,camera.d[0],camera.d[1],camera.d[2],camera.d[3],camera.d[4]}};
    static_assert(sizeof(double)==sizeof(uint64_t),"Cache signature needs float64");
    std::memcpy(signature.data()+2,values.data(),values.size()*sizeof(double));
    if(!prepared_||signature!=signature_){for(auto &entry:entries_)entry.tag=0;signature_=signature;camera_=camera;prepared_=true;}
}
V2 RecordDecodeCache::get(uint32_t key,V2 raw){
    auto &entry=entries_[(key*2654435761u)>>16];
    if(entry.tag==key+1){hits_++;return entry.uv;}
    misses_++;entry.uv=camera_.undistort(raw);entry.tag=key+1;return entry.uv;
}
Frame decodeRecords(const uint8_t *data,std::size_t bytes,uint64_t id,uint64_t stamp,const Camera &camera,RecordDecodeCache *cache){
    if(bytes%64||bytes/64>max_features||(!data&&bytes)||!stamp)throw std::runtime_error("Invalid ORB record buffer or timestamp");
    if(cache)cache->begin(camera);
    static const unsigned widths[8]={960,800,667,556,463,386,322,268},heights[8]={720,600,500,417,347,289,241,201};
    float scale[8]={1};for(int i=1;i<8;i++)scale[i]=scale[i-1]*1.2f;
    Frame f;f.id=id;f.timestamp_ns=stamp;f.features.reserve(bytes/64);
    for(std::size_t i=0;i<bytes;i+=64){const uint8_t *p=data+i;unsigned x=le32(p),y=le32(p+4),level=le32(p+12),bin=le32(p+16);
        if(level>=8||x>=widths[level]||y>=heights[level]||bin>=32||le32(p+28)!=bin*737280u)throw std::runtime_error("Invalid ORB coordinate/orientation ABI");
        Feature feature;feature.raw={static_cast<float>(x)*scale[level],static_cast<float>(y)*scale[level]};
        feature.uv=cache?cache->get((level<<20)|(y<<10)|x,feature.raw):camera.undistort(feature.raw);feature.level=level;feature.score=le32(p+8);
        std::copy(p+32,p+64,feature.descriptor.begin());
        // Read signed moment fields without unaligned casts or changing their wire bytes.
        (void)signed32(p+20);(void)signed32(p+24);f.features.push_back(feature);
    }
    return f;
}
std::vector<std::string> csvFields(const std::string &line){
    std::vector<std::string> fields;std::string current;bool quote=false;
    for(std::size_t i=0;i<line.size();i++){char c=line[i];
        if(c=='"'){if(quote&&i+1<line.size()&&line[i+1]=='"'){current+='"';i++;}else quote=!quote;}
        else if(c==','&&!quote){fields.push_back(current);current.clear();}else if(c!='\r')current+=c;
    }
    if(quote)throw std::runtime_error("Unclosed CSV quote");fields.push_back(current);return fields;
}
Csv::Csv(const std::string &path):stream_(path){std::string line;if(!stream_||!std::getline(stream_,line))throw std::runtime_error("Cannot read CSV: "+path);
    if(line.size()>=3&&static_cast<unsigned char>(line[0])==0xef)line.erase(0,3);header_=csvFields(line);
}
bool Csv::next(Row &out){std::string line;out.clear();if(!std::getline(stream_,line)){if(!stream_.eof())throw std::runtime_error("CSV read error");return false;}
    auto fields=csvFields(line);if(fields.size()!=header_.size())throw std::runtime_error("CSV field count mismatch");
    for(std::size_t i=0;i<fields.size();i++)if(!out.emplace(header_[i],fields[i]).second)throw std::runtime_error("Duplicate CSV header");return true;
}
uint64_t integer(const Row &row,const std::string &key){const auto &s=row.at(key);if(s.empty()||s[0]=='-')throw std::runtime_error("Expected unsigned integer: "+key);
    std::size_t end=0;uint64_t v=std::stoull(s,&end);if(end!=s.size())throw std::runtime_error("Invalid integer: "+key);return v;
}
double number(const Row &row,const std::string &key){std::size_t end=0;const auto &s=row.at(key);double v=std::stod(s,&end);
    if(end!=s.size()||!std::isfinite(v))throw std::runtime_error("Invalid number: "+key);return v;
}
Pose readTwc(const Row &row){Pose p;for(int r=0;r<3;r++){for(int c=0;c<3;c++)p.r(r,c)=number(row,"twc_"+std::to_string(r)+std::to_string(c));p.t[r]=number(row,"twc_"+std::to_string(r)+"3");}
    for(int c=0;c<4;c++)if(std::abs(number(row,"twc_3"+std::to_string(c))-(c==3))>1e-6)throw std::runtime_error("Invalid homogeneous pose row");
    if(!rigid(p))throw std::runtime_error("Invalid rigid pose");return p.inverse();
}
Camera readCamera(const std::string &path,bool source_geometry){Csv csv(path);Row r;if(!csv.next(r))throw std::runtime_error("Missing camera calibration");Camera c;
    auto width=integer(r,"width"),height=integer(r,"height");if(width>1280||height>800)throw std::runtime_error("Calibration dimensions outside camera bounds");
    c.width=static_cast<int>(width);c.height=static_cast<int>(height);
    c.fx=number(r,"fx");c.fy=number(r,"fy");c.cx=number(r,"cx");c.cy=number(r,"cy");for(int i=0;i<5;i++)c.d[i]=number(r,"d"+std::to_string(i));
    if(c.fx<=0||c.fy<=0||csv.next(r))throw std::runtime_error("Camera needs one valid calibration row");
    if(source_geometry)cameraCrop(c.width,c.height);
    else if(c.width!=960||c.height!=720)throw std::runtime_error("Paired ORB needs one 960x720 calibration");return c;
}
Replay::Replay(const std::string &folder,Camera camera):csv_(folder+"/frames.csv"),records_(folder+"/features.bin",std::ios::binary),camera_(camera){if(!records_)throw std::runtime_error("Cannot open replay features");}
bool Replay::next(Frame &frame){Row r;if(!csv_.next(r)){char tail;if(records_.get(tail))throw std::runtime_error("Extra replay records");return false;}
    uint64_t count=integer(r,"count");if(integer(r,"frame_index")!=index_||integer(r,"record_offset")!=offset_||count>max_features)throw std::runtime_error("Replay identity/count/offset mismatch");
    std::array<uint8_t,64000> bytes{};records_.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(count*64));
    if(records_.gcount()!=static_cast<std::streamsize>(count*64))throw std::runtime_error("Truncated replay records");
    frame=decodeRecords(bytes.data(),static_cast<std::size_t>(count*64),index_,integer(r,"timestamp_ns"),camera_);offset_+=count;index_++;return true;
}
CsvLog::CsvLog(const std::string &path,const std::string &header,unsigned rows,unsigned keep,unsigned precision):
    base_(path),header_(header),limit_(rows),keep_(keep),precision_(precision){
    if(!keep||keep>16||rows>1000000||header.empty()||header.find_first_of("\r\n")!=std::string::npos)throw std::runtime_error("Invalid CSV log bounds/header");
    openPart();
}
void CsvLog::openPart(){
    if(stream_.is_open()){stream_.close();if(!stream_)throw std::runtime_error("CSV close failed before rotation");}
    std::string path=base_;
    if(limit_){fs::path base(base_);std::ostringstream name;name<<base.stem().string()<<".part"<<std::setw(6)<<std::setfill('0')<<part_++<<base.extension().string();path=(base.parent_path()/name.str()).string();}
    if(fs::exists(path))throw std::runtime_error("Refusing to overwrite CSV log: "+path);
    stream_.open(path);if(!stream_)throw std::runtime_error("Cannot create CSV log");
    stream_<<header_<<'\n'<<std::setprecision(precision_);if(!stream_)throw std::runtime_error("CSV header write failed");
    owned_.push_back(path);rows_=0;
    while(limit_&&owned_.size()>keep_){if(!fs::remove(owned_.front()))throw std::runtime_error("Owned CSV retention removal failed");owned_.pop_front();}
}
std::ofstream &CsvLog::row(){
    if(finished_||!stream_)throw std::runtime_error("CSV log already finished or failed");
    if(limit_&&rows_==limit_)openPart();rows_++;return stream_;
}
void CsvLog::finish(){stream_.flush();if(!stream_)throw std::runtime_error("CSV final flush failed");finished_=true;}
namespace {
std::string trajectoryHeader(){std::string value="frame_index,timestamp_ns,map_id,pose_valid,state,features,inliers,points,keyframes,track_ms,map_ms";
    for(int r=0;r<4;r++)for(int c=0;c<4;c++)value+=",twc_"+std::to_string(r)+std::to_string(c);return value;}
}
TrajectoryWriter::TrajectoryWriter(const std::string &path,unsigned rows,unsigned keep):log_(path,trajectoryHeader(),rows,keep,17){}
void TrajectoryWriter::append(const Status &s){auto &stream=log_.row();stream<<s.frame<<','<<s.timestamp_ns<<",0,"<<s.pose_valid<<','<<stateName(s.state)<<','<<s.features<<','<<s.inliers<<','<<s.points<<','<<s.keyframes<<','<<s.track_ms<<','<<s.map_ms;
    Pose twc=s.tcw.inverse();for(int r=0;r<4;r++)for(int c=0;c<4;c++){stream<<',';if(s.pose_valid)stream<<(r==3?(c==3?1.:0.):(c==3?twc.t[r]:twc.r(r,c)));}stream<<'\n';
    if(!stream)throw std::runtime_error("Trajectory write failed");
}
} // namespace zslam
