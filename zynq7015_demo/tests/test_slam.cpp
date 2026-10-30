#include "zslam/slam.hpp"
#include "zslam/formats.hpp"
#include "zslam/ports.hpp"
#include "zslam/pipeline.hpp"
#include "zslam/async_stage.hpp"
#include "zslam/motion.hpp"
#include <chrono>
#include "zslam/filesystem.hpp"
#include <fstream>
#include <iostream>
#include <iomanip>
#include <limits>
#include <cstring>
#include <stdexcept>

namespace zslam {
// Fixtures use production mutation/matching paths. No test-only runtime branch.
struct RetrievalTestAccess {
    static Ref add(Slam &s,V3 p,const Descriptor &d,uint64_t frame){return s.addPoint(p,d,frame);}
    static std::vector<Observation> query(const Slam &s,const Frame &f,Status &profile){return s.matchMap(f,Pose{},true,&profile);}
    static void choices(Slam &s,Ref ref,const Descriptor &d){
        s.keys_.clear();s.map_[ref.slot].sight_count=0;
        for(unsigned i=0;i<2;i++){Frame f;f.id=i;Feature feature;feature.descriptor=d;f.features.push_back(feature);
            s.addKeyframe(f,Pose{},std::vector<Ref>{ref});}
        s.updateDescriptor(ref);
    }
    static void move(Slam &s,Ref ref,V3 xyz){s.map_[ref.slot].xyz=xyz;}
    static bool sameIndex(const Slam &a,const Slam &b){return a.retrieval_bits_==b.retrieval_bits_&&a.retrieval_descriptors_==b.retrieval_descriptors_&&a.retrieval_slots_==b.retrieval_slots_&&a.retrieval_heads_==b.retrieval_heads_&&a.retrieval_links_==b.retrieval_links_;}
    static std::size_t hashScratch(const Slam &s){return s.retrieval_hashes_.capacity()*sizeof(uint16_t);}
};
}

using namespace zslam;
namespace {
void check(bool yes,const char *message){if(!yes)throw std::runtime_error(message);}
template<class F>void rejected(F f,const char *message){bool threw=false;try{f();}catch(const std::exception&){threw=true;}check(threw,message);}
void cameraFrames(const fs::path &fixtures,const fs::path &output){
    auto read=[](const fs::path &path){std::ifstream in(path,std::ios::binary);if(!in)throw std::runtime_error("Missing camera fixture: "+path.string());return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)),{});};
    struct Case {const char *name;unsigned width,height;};
    std::vector<uint8_t> sample;
    for(auto c:{Case{"1280x720_RGB_2",1280,720},Case{"1280x800_L_0",1280,800},Case{"960x720_RGB_1",960,720},Case{"1024x768_RGB_0",1024,768}}){
        auto jpeg=read(fixtures/(std::string(c.name)+".jpg")),expected=read(fixtures/(std::string(c.name)+".gray"));
        for(bool partial:{false,true}){
        MjpegGrayDecoder decoder(c.width,c.height,partial);GrayFrame result;
        check(decoder.scratchBytes()==std::size_t(partial?960:c.width)*c.height,"JPEG scratch must equal the selected bounded width and all source rows");
        for(unsigned repeat=0;repeat<4;repeat++){decoder.decode(jpeg.data(),jpeg.size(),result);check(result.width==960&&result.height==720&&result.pixels==expected,"JPEG gray/crop pixels must exactly equal independent Pillow luminance reference");}
        auto broken=jpeg;broken.resize(broken.size()/2);broken.push_back(255);broken.push_back(217);
        rejected([&]{decoder.decode(broken.data(),broken.size(),result);},"Truncated entropy data with EOI must fail");
        rejected([&]{decoder.decode(jpeg.data(),jpeg.size()-2,result);},"Missing JPEG EOI must fail");
        auto wrong=jpeg;for(std::size_t p=0;p+9<wrong.size();p++)if(wrong[p]==255&&wrong[p+1]==192){wrong[p+5]=255;wrong[p+6]=255;wrong[p+7]=255;wrong[p+8]=255;break;}
        rejected([&]{decoder.decode(wrong.data(),wrong.size(),result);},"Oversized JPEG header must fail before image allocation");
        decoder.decode(jpeg.data(),jpeg.size(),result);check(result.pixels==expected,"JPEG decoder must recover after a rejected frame");
        }
        if(c.width==1280&&c.height==720)sample=std::move(jpeg);
    }
    MjpegGrayDecoder decoder(1280,720);GrayFrame result;
    rejected([&]{decoder.decode(nullptr,0,result);},"Null/empty JPEG rejected");
    rejected([&]{decoder.decode(sample.data(),MjpegGrayDecoder::max_compressed_bytes+1,result);},"Oversized payload rejected before reading it");
    rejected([&]{MjpegGrayDecoder bad(640,480);},"Unsupported source geometry must not silently scale");
    MjpegGrayDecoder narrow(960,720);
    rejected([&]{narrow.decode(sample.data(),sample.size(),result);},"JPEG must match negotiated size");
    for(const char *name:{"progressive.jpg","cmyk.jpg"}){auto bytes=read(fixtures/name);rejected([&]{narrow.decode(bytes.data(),bytes.size(),result);},"Non-camera JPEG coding/colorspace rejected");}
    for(unsigned step:{1u,2u}){
        unsigned width=1280,height=800,stride=width*step+37;std::vector<uint8_t> bytes(stride*height,211);
        for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++)bytes[y*stride+x*step]=uint8_t(x*3+y*17);
        auto encoding=step==1?CameraEncoding::Grey:CameraEncoding::Yuyv;
        unpackCameraGray(bytes.data(),bytes.size(),stride,width,height,encoding,result);
        for(unsigned y=0;y<720;y++)for(unsigned x=0;x<960;x++)check(result.pixels[y*960+x]==uint8_t((x+160)*3+(y+40)*17),"Padded YUYV/GREY must preserve the cropped luminance bytes");
        rejected([&]{unpackCameraGray(bytes.data(),stride*(height-1)+width*step-1,stride,width,height,encoding,result);},"Last active row must not be truncated");
        rejected([&]{unpackCameraGray(bytes.data(),bytes.size(),width*step-1,width,height,encoding,result);},"Short stride rejected");
    }
    Camera source;source.width=1280;source.height=800;source.fx=700;source.fy=705;source.cx=640;source.cy=400;source.d={{.01,-.02,.03,-.04,.05}};
    auto cropped=croppedCamera(source,1280,800);check(cropped.width==960&&cropped.height==720&&cropped.cx==480&&cropped.cy==360&&cropped.fx==source.fx&&cropped.fy==source.fy&&cropped.d==source.d,"Crop must shift principal point only");
    rejected([&]{croppedCamera(cropped,1280,800);},"Old recording or already cropped calibration cannot silently describe a larger camera image");
    auto file=output/"camera_source.csv";{std::ofstream out(file);out<<"width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4\n1280,800,700,705,640,400,0,0,0,0,0\n";}
    check(readCamera(file.string(),true).width==1280,"Source calibration geometry must be retained until explicit crop");
    rejected([&]{readCamera(file.string());},"Raw/replay ORB calibration remains960x720");
    CameraSequence sequence;check(sequence.accept(0xfffffffeu,1)==0xfffffffeull&&sequence.accept(0xffffffffu,2)==0xffffffffull&&sequence.accept(0u,3)==0x100000000ull&&sequence.accept(2u,4)==0x100000002ull&&sequence.gaps()==1,"Frame identity must extend wrap and count real gaps");
    rejected([&]{sequence.accept(2u,5);},"Duplicate driver sequence rejected");rejected([&]{sequence.accept(1u,5);},"Backward driver sequence rejected");rejected([&]{sequence.accept(3u,4);},"Repeated timestamp rejected");
    CameraCaptureProfile profile;profile.width=1280;profile.height=720;profile.frames=4;profile.first_timestamp_ns=1;profile.last_timestamp_ns=100000001;writeCameraReport(profile,(output/"camera.json").string());
    auto shots_folder=output/"calibration-shots";CalibrationRecorder shots(shots_folder.string(),3,2);GrayFrame gray;gray.width=960;gray.height=720;gray.pixels.resize(960*720);
    for(unsigned i=0;i<8;i++){gray.id=100+i;gray.timestamp_ns=1+uint64_t(i)*33333333;std::fill(gray.pixels.begin(),gray.pixels.end(),uint8_t(i));check(shots.consider(gray)==(i==0||i==2||i==4),"Calibration capture interval and shot bound must be exact");}
    check(shots.saved()==3,"Calibration capture cannot grow beyond requested count");
    rejected([&]{shots.consider(gray);},"Calibration cannot accept repeated frame identity even after reaching its bound");shots.finish();
    rejected([&]{shots.consider(gray);},"Finished calibration recorder must reject writes");
    Csv index((shots_folder/"index.csv").string());Row row;
    for(unsigned i:{0u,2u,4u}){check(index.next(row)&&integer(row,"frame_index")==100+i&&integer(row,"timestamp_ns")==1+uint64_t(i)*33333333,"Calibration index must preserve original frame and timestamp");
        auto image=read(shots_folder/row.at("file"));std::string header="P5\n960 720\n255\n";check(image.size()==header.size()+960*720&&std::memcmp(image.data(),header.data(),header.size())==0,"Calibration PGM header and byte count");
        for(std::size_t p=header.size();p<image.size();p++)check(image[p]==i,"Calibration PGM must preserve every decoded gray pixel");}
    check(!index.next(row),"Calibration index must stop at its fixed shot bound");
    rejected([&]{CalibrationRecorder duplicate(shots_folder.string(),3,2);},"Existing calibration data cannot be overwritten");
    rejected([&]{CalibrationRecorder invalid((output/"too-many-shots").string(),61,30);},"Calibration maximum is60 frames");
    rejected([&]{CalibrationRecorder invalid((output/"bad-interval").string(),3,0);},"Calibration interval must be positive");
    check(cameraFocusScore(gray)==0,"A constant image must have zero focus variance");
    GrayFrame sharp=gray,blur=gray;
    for(unsigned y=0;y<720;y++)for(unsigned x=0;x<960;x++)sharp.pixels[y*960+x]=((x/8+y/8)&1)?224:32;
    for(unsigned y=1;y<719;y++)for(unsigned x=1;x<959;x++){
        unsigned sum=0;for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++)sum+=sharp.pixels[(y+dy)*960+x+dx];blur.pixels[y*960+x]=uint8_t(sum/9);
    }
    auto original=sharp.pixels;double score=cameraFocusScore(sharp);
    check(score>cameraFocusScore(blur)&&sharp.pixels==original,"Focus guide must distinguish blur without changing image bytes");
    rejected([&]{GrayFrame bad;cameraFocusScore(bad);},"Focus guide rejects invalid pixel bounds");
    Frame preview_frame;preview_frame.id=sharp.id;Status no_pose;no_pose.mapping=false;Timings preview_timing;preview_timing.preview=true;preview_timing.focus_score=score;
    Dashboard focus_ui,normal_ui;focus_ui.draw(&sharp,preview_frame,SceneSnapshot{},no_pose,preview_timing);
    Timings normal_timing;normal_ui.draw(&sharp,preview_frame,SceneSnapshot{},no_pose,normal_timing);
    for(unsigned y=124;y<652;y++)for(unsigned x=32;x<736;x++)check(focus_ui.pixels[y*1280+x]==normal_ui.pixels[y*1280+x],"Focus preview preserves every displayed camera pixel");
    rejected([&]{Status false_pose=no_pose;false_pose.pose_valid=true;focus_ui.draw(&sharp,preview_frame,SceneSnapshot{},false_pose,preview_timing);},"Uncalibrated preview must never present a valid pose");
    focus_ui.draw(&sharp,preview_frame,SceneSnapshot{},no_pose,normal_timing);
    check(focus_ui.pixels==normal_ui.pixels,"Returning from focus preview restores the original UI exactly");
    std::cout<<"CAMERA_MJPEG_INDEPENDENT_PIXELS_CROP_STRIDE_CORRUPTION_LIMITS_IDENTITY_PASS\n";
}
unsigned rng=1729;
unsigned randomWord(){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
void spatialBins(){
    const unsigned saved_rng=rng;
    std::vector<V2> points={{0,0},{31.999,32},{32,31.999},{959.999,735.999},{960,736},{-1,-1},{std::numeric_limits<double>::quiet_NaN(),4}};
    for(unsigned i=0;i<2000;i++)points.push_back({double(randomWord()%112000)/100-80,double(randomWord()%88000)/100-80});
    SpatialBins bins;bins.build(static_cast<unsigned>(points.size()),[&](unsigned i){return points[i];});
    std::vector<V2> queries={{0,0},{32,32},{959,719},{960,736},{-20,5}};
    for(unsigned i=0;i<80;i++)queries.push_back(points[i]);
    for(V2 center:queries)for(double radius:{0.,1.,24.,72.,128.}){
        std::vector<unsigned> actual,expected;
        bins.visit(center,radius,[&](unsigned i){double x=points[i].x-center.x,y=points[i].y-center.y;if(x*x+y*y<=radius*radius)actual.push_back(i);});
        for(unsigned i=0;i<points.size();i++){auto p=points[i];double x=p.x-center.x,y=p.y-center.y;
            if(p.x>=0&&p.x<960&&p.y>=0&&p.y<736&&x*x+y*y<=radius*radius)expected.push_back(i);}
        std::sort(actual.begin(),actual.end());check(actual==expected,"CSR circle candidates must equal exhaustive bounded image search without duplicates");
    }
    bins.build(0,[](unsigned){return V2{};});unsigned count=0;bins.visit({0,0},128,[&](unsigned){count++;});check(!count,"Rebuilt empty index must not retain old entries");
    rng=saved_rng;
    std::cout<<"SPATIAL_BINS_EXHAUSTIVE_BOUNDARY_NAN_REBUILD_PASS\n";
}
double randomUnit(){return double(randomWord()%100000)/100000.;}
Descriptor descriptor(){Descriptor d;for(auto &v:d)v=static_cast<uint8_t>(randomWord());return d;}
Camera camera(){Camera c;c.fx=700;c.fy=705;c.cx=480;c.cy=360;c.d.fill(0);return c;}
struct Scene {std::vector<V3> xyz;std::vector<Descriptor> descriptors;};
Scene scene(unsigned count){Scene s;for(unsigned i=0;i<count;i++){s.xyz.push_back({(randomUnit()-.5)*4,(randomUnit()-.5)*3,4+randomUnit()*5});s.descriptors.push_back(descriptor());}return s;}
Frame frame(const Camera &c,const Scene &s,Pose p,unsigned id){Frame f;f.id=id;f.timestamp_ns=1000000000ull+id*33333334ull;
    for(unsigned i=0;i<s.xyz.size();i++){V3 q=p.apply(s.xyz[i]);if(q.z<=0)continue;V2 uv=c.project(q);if(uv.x<5||uv.x>=955||uv.y<5||uv.y>=715)continue;Feature feature;feature.raw=feature.uv=uv;feature.descriptor=s.descriptors[i];feature.score=100;f.features.push_back(feature);}return f;
}
void geometry(){Camera c=camera();Scene s=scene(140);Pose truth{rotation({.03,-.02,.01}),{-.2,.1,.04}},estimate{rotation({.025,-.01,.015}),{-.1,.08,.03}};
    std::vector<Observation> obs;for(unsigned i=0;i<s.xyz.size();i++)obs.push_back({s.xyz[i],c.project(truth.apply(s.xyz[i])),i,i});
    for(unsigned i=0;i<14;i++){obs[i].uv.x+=150;obs[i].uv.y-=100;}
    std::vector<unsigned> inliers;check(optimizePose(c,obs,estimate,inliers,40,16),"Robust pose optimization");check(norm(estimate.center()-truth.center())<.01,"Pose translation accuracy");
    M3 delta=estimate.r*transpose(truth.r);check(delta(0,0)+delta(1,1)+delta(2,2)>2.9999,"Pose rotation accuracy");check(inliers.size()==126,"Outliers must be rejected");
    Pose global;global.t={20,-10,8};
    for(unsigned i=14;i<70;i++)obs[i].uv={randomUnit()*960,randomUnit()*720};
    check(robustPose(c,obs,global,inliers,40,1732),"P3P recovery without nearby pose and with 50 percent outliers");
    check(norm(global.center()-truth.center())<.01&&inliers.size()==70,"P3P consensus/refinement accuracy");
    auto degenerate=obs;for(auto &o:degenerate)o.xyz={1,1,1};
    check(!robustPose(c,degenerate,global,inliers,40),"Coincident P3P points must fail");
    Pose second{rotation({.005,.025,-.004}),{-.5,.02,.01}};std::vector<V2>a,b;for(auto xyz:s.xyz){a.push_back(c.project(xyz));b.push_back(c.project(second.apply(xyz)));}
    for(unsigned i=0;i<8;i++)b[i]={100+randomUnit()*700,100+randomUnit()*500};std::vector<V3> points;Pose recovered;
    check(initializeTwoViews(c,a,b,recovered,inliers,points),"Monocular two-view initialization");
    check(dot(unit(recovered.center()),unit(second.center()))>.995,"Initialization translation direction");check(inliers.size()>100,"Initialization geometric support");
    for(unsigned i=0;i<inliers.size();i++){check(distance(c.project(points[i]),a[inliers[i]])<3,"First-view reprojection");check(distance(c.project(recovered.apply(points[i])),b[inliers[i]])<3,"Second-view reprojection");}
    check(!initializeTwoViews(c,a,a,recovered,inliers,points),"Stationary initialization must fail");
    std::cout<<"GEOMETRY_POSE_TRIANGULATION_RANSAC_PASS\n";
}
void decodeCache(){
    RecordDecodeCache cache;Camera c;std::vector<uint8_t> bytes(1000*64);
    auto make=[&](unsigned base,bool pyramid){const unsigned widths[8]={960,800,667,556,463,386,322,268},heights[8]={720,600,500,417,347,289,241,201};
        auto word=[](uint8_t *p,uint32_t value){for(unsigned k=0;k<4;k++)p[k]=uint8_t(value>>(8*k));};
        for(unsigned i=0;i<1000;i++){auto p=bytes.data()+i*64;unsigned index=base+i,level=pyramid?index%8:0;
            unsigned x=index%widths[level],y=(index/widths[level])%heights[level];
            if(pyramid){x=(index/8)&1?widths[level]-1:0;y=(index/16)&1?heights[level]-1:0;}
            word(p,x);word(p+4,y);word(p+8,index);word(p+12,level);word(p+16,index%32);word(p+20,uint32_t(0-index));word(p+24,index);word(p+28,(index%32)*737280u);
            for(unsigned j=0;j<32;j++)p[32+j]=uint8_t(index*31+j*11);
        }
    };
    auto compare=[&](const Camera &cam){auto plain=decodeRecords(bytes.data(),bytes.size(),7,11,cam),cached=decodeRecords(bytes.data(),bytes.size(),7,11,cam,&cache);
        check(plain.id==cached.id&&plain.timestamp_ns==cached.timestamp_ns&&plain.features.size()==cached.features.size(),"Cached record identity");
        for(unsigned i=0;i<plain.features.size();i++){const auto &a=plain.features[i],&b=cached.features[i];
            check(a.raw.x==b.raw.x&&a.raw.y==b.raw.y&&std::memcmp(&a.uv.x,&b.uv.x,sizeof(double))==0&&std::memcmp(&a.uv.y,&b.uv.y,sizeof(double))==0&&a.level==b.level&&a.score==b.score&&a.descriptor==b.descriptor,"Cached coordinates must be bit-identical with unchanged descriptor/order");}
    };
    // More unique level0 keys than slots force collision/eviction, followed by
    // old-key revisits and all pyramid extrema. No geometry fixture RNG changes.
    for(unsigned base=0;base<70000;base+=1000){make(base,false);compare(c);compare(c);}
    make(0,false);compare(c);make(0,true);compare(c);compare(c);
    check(cache.hits()>0&&cache.misses()>65536&&cache.reservedBytes()<=2*1024*1024,"Cache must remain bounded through hits, collisions and replacement");
    for(unsigned field=0;field<9;field++){Camera changed=c;std::array<double*,9> values{{&changed.fx,&changed.fy,&changed.cx,&changed.cy,&changed.d[0],&changed.d[1],&changed.d[2],&changed.d[3],&changed.d[4]}};*values[field]+=.001;compare(changed);}
    compare(c);Camera minus_zero=c;minus_zero.d[4]=-0.;auto misses=cache.misses();compare(minus_zero);check(cache.misses()>misses,"Signed-zero calibration change must invalidate by bits");
    Camera size=c;size.width++;size.height++;compare(size);
    bytes[0]=255;bytes[1]=255;rejected([&](){decodeRecords(bytes.data(),bytes.size(),7,11,c,&cache);},"Cache must not bypass malformed coordinate checks");
    std::cout<<"DECODE_CACHE_70000_KEYS_COLLISION_REVISIT_ALL_LEVELS_BIT_EXACT_CALIBRATION_INVALIDATION_PASS\n";
}
void records(){Camera c=camera();std::array<uint8_t,64> bytes{};bytes[0]=5;bytes[4]=7;bytes[12]=1;auto f=decodeRecords(bytes.data(),64,0,1,c);
    check(f.features.size()==1&&std::abs(f.features[0].raw.x-6)<1e-6,"Wire float32 pyramid scaling");check(decodeRecords(nullptr,0,0,1,c).features.empty(),"Empty record frame");
    rejected([&](){decodeRecords(bytes.data(),63,0,1,c);},"Truncated feature accepted");bytes[12]=8;rejected([&](){decodeRecords(bytes.data(),64,0,1,c);},"Bad octave accepted");
    Descriptor a{},b{};b.fill(255);check(hamming(a,b)==256,"Hamming256");check(csvFields("a,\"b,c\",\"d\"\"e\"")==std::vector<std::string>({"a","b,c","d\"e"}),"CSV escaping");
    for(unsigned trial=0;trial<1000;trial++){a=descriptor();b=descriptor();unsigned expected=0;
        for(unsigned i=0;i<32;i++)for(unsigned bit=0;bit<8;bit++)expected+=((a[i]^b[i])>>bit)&1;
        check(hamming(a,b)==expected,"Packed NEON Hamming must equal bitwise reference");}
    std::cout<<"WIRE_BOUNDS_EMPTY_ENDIAN_HAMMING_PASS\n";
}
void mapping(const zslam::fs::path &output){Camera c=camera();Config config;config.max_points=400;config.max_keyframes=6;config.max_trajectory=16;config.keyframe_interval=3;config.local_ba_iterations=1;
    Slam slam(c,config);Scene s=scene(160);auto first=slam.process(frame(c,s,Pose{},0));check(!first.pose_valid,"First monocular frame has no pose");
    Pose pose;pose.t={-.5,0,0};auto initialized=slam.process(frame(c,s,pose,1));check(initialized.pose_valid&&initialized.points>=100,"Fresh mapping must initialize without supplied map");
    for(unsigned i=2;i<24;i++){pose.t={-.5-.015*(i-1),.002*std::sin(double(i)),0};auto result=slam.process(frame(c,s,pose,i));check(result.pose_valid,"Tracking changing frames");check(result.points<=config.max_points&&result.keyframes<=config.max_keyframes,"Bounded map/keyframes");}
    Frame empty;empty.id=24;empty.timestamp_ns=1000000000ull+24*33333334ull;auto lost=slam.process(empty);check(!lost.pose_valid&&lost.state==State::Lost,"Loss must invalidate pose");
    auto recovered=slam.process(frame(c,s,pose,25));check(recovered.pose_valid&&recovered.state==State::Relocalized,"Recover from stored keyframes");check(slam.trajectory().size()==config.max_trajectory,"Bounded trajectory");
    unsigned attempts=0;for(unsigned id=30;id<36;id++){Frame missing;missing.id=id;missing.timestamp_ns=1000000000ull+id*33333334ull;auto r=slam.process(missing);check(!r.pose_valid,"Repeated losses cannot reuse a valid pose");attempts+=r.recovery_attempted;}
    check(attempts==4,"Repeated failed recovery must obey its bounded interval");
    bool found=false;for(unsigned id=36;id<39;id++)found|=slam.process(frame(c,s,pose,id)).pose_valid;check(found,"Rate-limited recovery must resume within three frames");
    std::string map=(output/"roundtrip.zmap").string();slam.save(map);Slam loaded(c,config);loaded.load(map);loaded.setMapping(false);
    auto result=loaded.process(frame(c,s,pose,26));check(result.pose_valid&&result.points==recovered.points,"Persisted map localization");
    rejected([&](){slam.save(map);},"Existing map overwritten");rejected([&](){loaded.process(frame(c,s,pose,26));},"Duplicate frame accepted");
    {std::ifstream in(map,std::ios::binary);std::vector<char> data((std::istreambuf_iterator<char>(in)),{});data[30]^=1;std::ofstream bad(output/"corrupt.zmap",std::ios::binary);bad.write(data.data(),static_cast<std::streamsize>(data.size()));}
    rejected([&](){loaded.load((output/"corrupt.zmap").string());},"Corrupt map accepted");check(loaded.points().size()==result.points,"Failed load must preserve active map");
    Dashboard ui;GrayFrame gray;gray.pixels.resize(960*720);for(unsigned y=0;y<720;y++)for(unsigned x=0;x<960;x++)gray.pixels[y*960+x]=static_cast<uint8_t>((x/16+y/16)%2?120:45);
    auto last=frame(c,s,pose,27);Timings timing;ui.draw(&gray,last,loaded,result,timing);ui.savePpm((output/"dashboard_synthetic.ppm").string());check(ui.pixels.size()==1280*720,"Dashboard buffer size");
    V3 cloud_center{};auto cloud=loaded.points();for(const auto &point:cloud)cloud_center=cloud_center+point.xyz;cloud_center=cloud_center/static_cast<double>(cloud.size());
    auto frustumX=[&](double center_x){Status view=result;view.pose_valid=true;view.tcw=Pose{};view.tcw.t=-(cloud_center+V3{center_x,0,0});ui.draw(&gray,last,loaded,view,timing);
        Dashboard fresh;fresh.draw(&gray,last,loaded,view,timing);check(ui.pixels==fresh.pixels,"Cached cloud and moving frustum must equal fresh full redraw");
        double sum=0;unsigned count=0;for(unsigned y=124;y<526;y++)for(unsigned x=780;x<1251;x++)if(ui.pixels[y*1280+x]==0xfe88){sum+=x;count++;}
        check(count>0,"Test frustum must be visible");return sum/count;};
    double left_frustum=frustumX(-.4),right_frustum=frustumX(.4);
    check(right_frustum>left_frustum,"Positive world X must project toward screen right");
    SceneSnapshot frozen(loaded);Status frozen_status=result;Dashboard frozen_before;frozen_before.draw(&gray,last,frozen,frozen_status,timing);
    loaded.reset();Dashboard frozen_after;frozen_after.draw(&gray,last,frozen,frozen_status,timing);
    check(frozen_before.pixels==frozen_after.pixels,"Render snapshot must remain immutable after SLAM resets on its owner thread");
    Status cleared;ui.draw(&gray,last,loaded,cleared,timing);Dashboard fresh;fresh.draw(&gray,last,loaded,cleared,timing);
    check(ui.pixels==fresh.pixels,"Reset must invalidate cached cloud and erase old cloud/trajectory/frustum");
    std::cout<<"FRESH_MAPPING_TRACKING_LOSS_RELOCALIZATION_BOUNDS_MAP_CRC_UI_PASS\n";
}
struct CameraContext {std::vector<uint8_t> pixels;unsigned releases=0;};
int acquire(void *p,zslam_camera_frame *f){auto *c=static_cast<CameraContext*>(p);*f={c->pixels.data(),c->pixels.size(),960,720,960,1,1000000000,7};return 1;}
void release(void *p,uint64_t lease){check(lease==7,"Lease identity");static_cast<CameraContext*>(p)->releases++;}
void ports(){CameraContext ctx;ctx.pixels.resize(960*720,77);auto camera=externalCamera({&ctx,acquire,release});GrayFrame f;check(camera->next(f)&&f.pixels[0]==77&&ctx.releases==1,"External camera ownership");
    ctx.pixels.resize(1);rejected([&](){camera->next(f);},"Invalid external camera accepted");check(ctx.releases==2,"Invalid acquired frame lease leaked");
    rejected([](){externalDisplay({nullptr,nullptr});},"Incomplete HDMI callback accepted");std::cout<<"CAMERA_HDMI_CALLBACK_OWNERSHIP_PASS\n";
}
void grayPool(){
    auto pool=std::make_shared<GrayBufferPool>();std::vector<std::vector<uint8_t>> leases;
    for(unsigned i=0;i<GrayBufferPool::capacity;i++){leases.push_back(pool->acquire());leases.back()[0]=uint8_t(i+1);}
    rejected([&](){pool->acquire();},"Pool must reject an eleventh outstanding lease");
    auto address=leases.back().data();pool->release(std::move(leases.back()));leases.pop_back();
    auto again=pool->acquire();check(again.data()==address&&again[0]==10,"Pool reuses allocation without per-frame zero fill");pool->release(std::move(again));
    for(unsigned i=0;i<leases.size();i++){check(leases[i][0]==i+1,"Returning one buffer must not mutate another lease");pool->release(std::move(leases[i]));}
    struct Source final:CameraSource {unsigned id=0;bool next(GrayFrame &f)override{
        if(id==240)return false;check(f.pixels.size()==960*720,"Capture must receive a complete reusable buffer");
        f.id=id;std::fill(f.pixels.begin(),f.pixels.end(),uint8_t(id++));return true;}} source;
    FramePipeline pipe(source,[](const GrayFrame &g){Frame f;f.id=g.id;return f;},0,false,1,pool);
    PipelineFrame f;unsigned count=0;while(pipe.next(f)){
        check(f.gray.id==count&&f.features.id==count,"Reused pipeline preserves identity and order");
        for(auto byte:f.gray.pixels)check(byte==uint8_t(count),"Owned gray bytes must survive asynchronous ORB and capture");
        pool->release(std::move(f.gray.pixels));count++;
    }
    check(count==240&&pool->reservedBytes()==6912000,"Reusable pipeline EOF and fixed allocation bound");
    std::cout<<"GRAY_POOL_BOUNDED_OWNERSHIP_NO_EARLY_REUSE_240_FRAMES_PASS\n";
}
void pipeline(){
    {std::vector<unsigned> order;AsyncStage<unsigned> consumer([&](unsigned &&v){order.push_back(v);});
        for(unsigned i=0;i<37;i++)consumer.submit(i);consumer.finish();check(order.size()==37,"Render queue finish must drain");
        for(unsigned i=0;i<37;i++)check(order[i]==i,"Render queue must preserve frame identity");}
    {AsyncStage<unsigned> consumer([](unsigned &&v){if(v==5)throw std::runtime_error("Injected display failure");});
        rejected([&](){for(unsigned i=0;i<30;i++)consumer.submit(i);consumer.finish();},"Display exception must reach producer without full-queue deadlock");}
    {AsyncStage<unsigned> consumer([](unsigned &&){std::this_thread::sleep_for(std::chrono::milliseconds(1));});consumer.submit(1);}
    struct Source final:CameraSource {unsigned next_id=0,count;explicit Source(unsigned n):count(n){}
        bool next(GrayFrame &f)override{if(next_id==count)return false;f.id=next_id++;f.timestamp_ns=f.id+1;f.pixels.assign(1,static_cast<uint8_t>(f.id));return true;}};
    auto extract=[](const GrayFrame &g){Frame f;f.id=g.id;f.timestamp_ns=g.timestamp_ns;return f;};
    {Source source(37);FramePipeline pipe(source,extract,0);PipelineFrame f;unsigned count=0;
        while(pipe.next(f)){check(f.gray.id==count&&f.features.id==count&&f.features.timestamp_ns==count+1,"Pipeline FIFO identity");count++;std::this_thread::yield();}
        check(count==37,"Pipeline EOF must drain every queued frame");}
    {Source source(37);FramePipeline pipe(source,extract,7);PipelineFrame f;unsigned count=0;while(pipe.next(f))count++;check(count==7,"Pipeline limit must not over-extract");}
    {Source source(100000);FramePipeline pipe(source,extract,0);std::this_thread::sleep_for(std::chrono::milliseconds(5));}
    {Source source(100);FramePipeline pipe(source,[](const GrayFrame &g){if(g.id==5)throw std::runtime_error("Injected ORB fault");return Frame{};},0);
        rejected([&](){PipelineFrame f;while(pipe.next(f)){};},"Pipeline worker exception must reach consumer");}
    std::cout<<"PIPELINE_ORDER_EOF_LIMIT_FULL_QUEUE_CANCEL_EXCEPTION_PASS\n";
}
void preview(){
    GrayFrame gray;gray.pixels.resize(960*720);for(unsigned i=0;i<gray.pixels.size();i++)gray.pixels[i]=static_cast<uint8_t>((i*37+i/960*13)%256);
    Dashboard ui;Slam slam(camera());ui.draw(&gray,Frame{},slam,Status{},Timings{});
    for(unsigned y=0;y<528;y++)for(unsigned x=0;x<704;x++){
        unsigned v=gray.pixels[(y*720/528)*960+x*960/704];uint16_t expected=static_cast<uint16_t>(((v>>3)<<11)|((v>>2)<<5)|(v>>3));
        check(ui.pixels[(y+124)*1280+x+32]==expected,"Preview sampling/RGB565 must match every scalar pixel");
    }
    for(auto &pixel:gray.pixels)pixel=255-pixel;ui.draw(&gray,Frame{},slam,Status{},Timings{});
    for(unsigned y=0;y<528;y++)for(unsigned x=0;x<704;x++){
        unsigned v=gray.pixels[(y*720/528)*960+x*960/704];uint16_t expected=static_cast<uint16_t>(((v>>3)<<11)|((v>>2)<<5)|(v>>3));
        check(ui.pixels[(y+124)*1280+x+32]==expected,"Incremental preview must erase all previous image pixels");
    }
    std::cout<<"PREVIEW_ALL_371712_PIXELS_AND_RIGHTWARD_FRUSTUM_PASS\n";
}
void trajectoryProjection(){
    SceneSnapshot scene;auto fillCloud=[&](){scene.points.clear();for(unsigned i=0;i<80;i++)scene.points.push_back({{(double(i%10)-4.5)*.08,(double(i/10)-3.5)*.08,4+double(i%3)*.03},i+1,10});};fillCloud();
    auto sample=[](uint64_t id){return TrackSample{id,1000000000ull+id*33333333ull,{.08*std::sin(double(id)*.017),.06*std::cos(double(id)*.019),3.8},id%11!=0};};
    for(unsigned i=0;i<4096;i++)scene.trajectory.push_back(sample(i));
    Dashboard cached(true),full(false),defaults;check(cached.trajectoryCacheBytes()>0&&cached.trajectoryCacheBytes()<=512*1024&&full.trajectoryCacheBytes()==0&&defaults.trajectoryCacheBytes()==0,"Projection cache allocation must stay fixed, optional and disabled by default");
    Status status;status.pose_valid=true;status.state=State::Tracking;Timings timing;Frame frame;
    for(unsigned step=0;step<36;step++){
        if(step&&step<22){scene.trajectory.erase(scene.trajectory.begin());scene.trajectory.push_back(sample(4095+step));}
        if(step==8)scene.trajectory[17].center.x+=.12;
        if(step==10)scene.trajectory[21].timestamp_ns++;
        if(step==12)scene.trajectory[19].valid=!scene.trajectory[19].valid;
        if(step==16)scene.points[0].xyz.x+=.05;
        if(step==18)scene.points[3].observations=2;
        if(step==20)scene.trajectory[0].frame+=4096;
        if(step==22)scene.trajectory.clear();
        if(step==24)for(unsigned i=0;i<64;i++){auto p=sample(i);p.center.y+=.02;scene.trajectory.push_back(p);}
        if(step==26)scene.trajectory[3].frame=scene.trajectory[5].frame;
        if(step==28)scene.trajectory[7].center={1e8,-1e8,-1e8};
        if(step==30)scene.trajectory[9].valid=false;
        if(step==32)scene.points.clear();
        if(step==34)fillCloud();
        status.tcw.t={-.02*std::sin(step*.1),0,-3.8};status.points=unsigned(scene.points.size());
        cached.draw(nullptr,frame,scene,status,timing);full.draw(nullptr,frame,scene,status,timing);
        check(cached.pixels==full.pixels,"Every UI pixel must equal uncached projection during ring eviction, history edit, loss, viewpoint/color change, reset and collision");
        if(step==1)check(cached.lastProfile().trajectory_hits==4095&&cached.lastProfile().trajectory_misses==1,"Rolling4096 history must reuse exactly4095 immutable projections");
        if(step==16)check(cached.lastProfile().trajectory_hits==0,"Changed cloud viewpoint must invalidate all old projections");
    }
    std::cout<<"TRAJECTORY_CACHE_ALL_PIXELS_RING4096_HISTORY_EDIT_LOSS_VIEWPOINT_RESET_COLLISION_PASS\n";
}
void retrievalInvalidation(const zslam::fs::path &root){
    Config exact_config;exact_config.precise_retrieval_invalidation=true;exact_config.max_points=96;exact_config.max_keyframes=4;
    Config legacy_config=exact_config;legacy_config.precise_retrieval_invalidation=false;
    Camera c=camera();Slam exact(c,exact_config),legacy(c,legacy_config);
    std::vector<Ref> exact_refs,legacy_refs;std::vector<Descriptor> descriptors;Frame f;f.timestamp_ns=1;
    // Local seed cannot alter pre-existing geometry/mapping fixtures.
    uint32_t seed=0x714c9e35u;auto word=[&](){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;};
    for(unsigned i=0;i<96;i++){
        Descriptor d;for(auto &byte:d)byte=uint8_t(word());d[0]=uint8_t(i);descriptors.push_back(d);
        V3 xyz{(double(i%12)-5.5)*.24,(double(i/12)-3.5)*.24,6+double(i%5)*.1};
        exact_refs.push_back(RetrievalTestAccess::add(exact,xyz,d,10));legacy_refs.push_back(RetrievalTestAccess::add(legacy,xyz,d,10));
        Feature feature;feature.raw=feature.uv=c.project(xyz);feature.descriptor=d;if(i%7==0)feature.descriptor[31]^=1;f.features.push_back(feature);
    }
    // Competing duplicate features exercise deterministic candidate tie order.
    for(unsigned i=0;i<8;i++)f.features.push_back(f.features[i]);
    auto compare=[&](unsigned exact_builds,unsigned legacy_builds){
        Status a,b;auto left=RetrievalTestAccess::query(exact,f,a),right=RetrievalTestAccess::query(legacy,f,b);
        check(left.size()==right.size(),"Retrieval invalidation modes must return the same match count");
        for(unsigned i=0;i<left.size();i++){const auto &x=left[i],&y=right[i];
            check(x.feature==y.feature&&x.landmark==y.landmark&&x.xyz.x==y.xyz.x&&x.xyz.y==y.xyz.y&&x.xyz.z==y.xyz.z&&x.uv.x==y.uv.x&&x.uv.y==y.uv.y,"Retrieval candidates, tie order and current geometry must be identical");}
        check(a.retrieval_builds==exact_builds&&b.retrieval_builds==legacy_builds&&a.retrieval_queries==1&&b.retrieval_queries==1,"Only real descriptor/slot changes should rebuild the precise index");
        check(a.retrieval_build_cpu_ms>=0&&a.retrieval_query_cpu_ms>=0&&b.retrieval_build_cpu_ms>=0&&b.retrieval_query_cpu_ms>=0,"Retrieval CPU counters must be nonnegative");
        return left;
    };
    check(compare(1,1).size()>=90,"Retrieval fixture needs meaningful unique descriptor matches");compare(0,0);
    Descriptor replacement{};replacement.fill(0x4f);
    check(RetrievalTestAccess::add(exact,{.2,.1,6},replacement,20).slot==~0u&&RetrievalTestAccess::add(legacy,{.2,.1,6},replacement,20).slot==~0u,"A full recently observed map must reject insertion");
    compare(0,1);
    RetrievalTestAccess::choices(exact,exact_refs[0],descriptors[0]);RetrievalTestAccess::choices(legacy,legacy_refs[0],descriptors[0]);compare(0,1);
    Descriptor changed=descriptors[0];for(auto &byte:changed)byte^=0x5a;
    RetrievalTestAccess::choices(exact,exact_refs[0],changed);RetrievalTestAccess::choices(legacy,legacy_refs[0],changed);f.features[0].descriptor=changed;compare(1,1);compare(0,0);
    // Global index caches descriptors/slots. Returned XYZ must stay fresh even
    // when BA changes geometry without changing the descriptor index.
    V3 moved{.07,.11,5.5};RetrievalTestAccess::move(exact,exact_refs[0],moved);RetrievalTestAccess::move(legacy,legacy_refs[0],moved);
    auto moved_matches=compare(0,0);bool found=false;for(const auto &m:moved_matches)if(m.feature==0){found=true;check(m.xyz.x==moved.x&&m.xyz.y==moved.y&&m.xyz.z==moved.z,"Reused retrieval must read current map XYZ");}check(found,"Changed descriptor must remain retrievable");
    auto new_exact=RetrievalTestAccess::add(exact,{.2,.1,6},replacement,200),new_legacy=RetrievalTestAccess::add(legacy,{.2,.1,6},replacement,200);
    check(new_exact.slot==exact_refs[0].slot&&new_legacy.slot==legacy_refs[0].slot&&new_exact.generation!=exact_refs[0].generation,"Actual stale-slot replacement must occur");
    f.features[0].descriptor=replacement;compare(1,1);compare(0,0);
    auto map=(root/"retrieval.zmap").string();exact.save(map);exact.load(map);legacy.load(map);compare(1,1);compare(0,0);
    rejected([&](){exact.load(map+".missing");},"Failed map load must report failure");compare(0,0);
    exact.reset();legacy.reset();check(compare(1,1).empty(),"Reset must remove cached matches");compare(0,0);
    RetrievalTestAccess::add(exact,{0,0,6},replacement,1);RetrievalTestAccess::add(legacy,{0,0,6},replacement,1);check(!compare(1,1).empty(),"Insertion after reset must invalidate the empty index");
    std::cout<<"RETRIEVAL_EXACT_ORDER_FULL_MAP_UNCHANGED_CHANGED_DESCRIPTOR_SLOT_GEOMETRY_LOAD_RESET_PASS\n";
}
void csvRetention(const zslam::fs::path &root){
    auto folder=root/"csv_retention";zslam::fs::create_directory(folder);
    auto path=(folder/"log.csv").string();{std::ofstream unrelated(folder/"log.part999999.csv");unrelated<<"keep me\n";}
    CsvLog log(path,"frame,value",2,2);for(unsigned i=0;i<7;i++)log.row()<<i<<','<<i*3<<'\n';log.finish();
    check(!zslam::fs::exists(folder/"log.part000000.csv")&&!zslam::fs::exists(folder/"log.part000001.csv"),"Old owned segments must rotate out");
    std::vector<unsigned> actual;for(const char *name:{"log.part000002.csv","log.part000003.csv"}){Csv csv((folder/name).string());Row row;while(csv.next(row)){
        unsigned frame=unsigned(integer(row,"frame"));check(integer(row,"value")==frame*3,"CSV payload across rotation");actual.push_back(frame);}}
    check(actual==std::vector<unsigned>({4,5,6}),"Retention must preserve the final bounded rows with headers");
    {std::ifstream unrelated(folder/"log.part999999.csv");std::string text;std::getline(unrelated,text);check(text=="keep me","Never remove unrelated matching filenames");}
    rejected([&](){log.row();},"Appending after final flush must fail");
    rejected([&](){CsvLog overwrite((folder/"log.part999999.csv").string(),"x");},"Existing CSV must not be overwritten");
    rejected([&](){CsvLog invalid((folder/"bad.csv").string(),"x",2,0);},"Zero retained segments must fail");
    TrajectoryWriter trajectory((folder/"trajectory.csv").string(),2,2);for(unsigned i=0;i<7;i++){Status s;s.frame=i;s.timestamp_ns=i+1;s.pose_valid=i%2;trajectory.append(s);}trajectory.finish();
    Csv csv((folder/"trajectory.part000003.csv").string());Row row;check(csv.next(row)&&integer(row,"frame_index")==6&&integer(row,"pose_valid")==0&&row.at("twc_03").empty(),"Rotation must retain an invalid pose as invalid with blank transform");
    check(!csv.next(row),"Last trajectory segment has only its one final row");
    std::cout<<"CSV_RETENTION_ROWS_HEADERS_POSE_VALIDITY_FOREIGN_FILE_NO_OVERWRITE_PASS\n";
}
void rawFiles(const zslam::fs::path &root){
    auto path=(root/"input.gray8").string();std::vector<uint8_t> bytes(960*720);for(unsigned i=0;i<bytes.size();i++)bytes[i]=static_cast<uint8_t>(i*13);
    {std::ofstream file(path,std::ios::binary);for(unsigned frame=0;frame<2;frame++)file.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());}
    {auto source=rawCamera(path);GrayFrame f;for(unsigned i=0;i<2;i++){check(source->next(f)&&f.id==i&&f.timestamp_ns>0&&f.pixels==bytes,"Raw file identity and every byte");}check(!source->next(f),"Raw source EOF");}
    {std::ofstream file(root/"truncated.gray8",std::ios::binary);file.put('x');}
    {auto source=rawCamera((root/"truncated.gray8").string());GrayFrame f;rejected([&](){source->next(f);},"Truncated raw source must fail");}
    std::cout<<"RAW_FILE_BYTES_SEQUENCE_EOF_TRUNCATION_PASS\n";
}
void anchors(const zslam::fs::path &root){
    auto folder=root/"anchor_input";zslam::fs::create_directory(folder);Camera c=camera();Scene s=scene(100);
    std::ofstream points(folder/"points.csv"),descriptors(folder/"representative_descriptors.bin",std::ios::binary),keys(folder/"keyframes.csv"),observations(folder/"observations.csv"),obsdesc(folder/"observation_descriptors.bin",std::ios::binary);
    points<<std::setprecision(17)<<"point_id,x,y,z,observations\n";keys<<std::setprecision(17)<<"keyframe_id,slam_frame_id,fx,fy";
    for(int r=0;r<4;r++)for(int col=0;col<4;col++)keys<<",twc_"<<r<<col;keys<<'\n';
    observations<<std::setprecision(17)<<"keyframe_id,point_id,descriptor_row,raw_u,raw_v,u,v,octave\n";
    for(unsigned i=0;i<s.xyz.size();i++){V3 p=s.xyz[i];points<<i+1<<','<<p.x<<','<<p.y<<','<<p.z<<",3\n";descriptors.write(reinterpret_cast<const char*>(s.descriptors[i].data()),32);}
    unsigned row=0;
    for(unsigned k=0;k<3;k++){
        Pose p;p.t={-.25*k,0,0};Pose twc=p.inverse();keys<<k+1<<','<<k<<','<<c.fx<<','<<c.fy;
        for(int r=0;r<4;r++)for(int col=0;col<4;col++)keys<<','<<(r==3?(col==3?1.:0.):(col==3?twc.t[r]:twc.r(r,col)));keys<<'\n';
        for(unsigned i=0;i<s.xyz.size();i++){V2 uv=c.project(p.apply(s.xyz[i]));observations<<k+1<<','<<i+1<<','<<row++<<','<<uv.x<<','<<uv.y<<','<<uv.x<<','<<uv.y<<",0\n";obsdesc.write(reinterpret_cast<const char*>(s.descriptors[i].data()),32);}
    }
    points.close();descriptors.close();keys.close();observations.close();obsdesc.close();
    {Config probe_config;probe_config.max_points=200;probe_config.max_keyframes=6;Slam probe(c,probe_config);
        auto query=frame(c,s,Pose{},0);probe.importHandoff(folder.string());Status before,after;
        auto old_matches=RetrievalTestAccess::query(probe,query,before);probe.importHandoff(folder.string());auto new_matches=RetrievalTestAccess::query(probe,query,after);
        check(before.retrieval_builds==1&&after.retrieval_builds==1&&old_matches.size()>80&&old_matches.size()==new_matches.size(),"Re-import must replace a warm retrieval index");
        for(unsigned i=0;i<old_matches.size();i++){const auto &a=old_matches[i],&b=new_matches[i];check(a.feature==b.feature&&a.landmark==b.landmark&&a.xyz.x==b.xyz.x&&a.xyz.y==b.xyz.y&&a.xyz.z==b.xyz.z,"Re-imported retrieval order and geometry must match");}}
    Config config;config.max_points=200;config.max_keyframes=6;config.keyframe_interval=2;Slam slam(c,config);slam.importHandoff(folder.string());
    for(unsigned i=0;i<20;i++){Pose p;p.t={-.5-.01*i,0,0};check(slam.process(frame(c,s,p,i)).pose_valid,"Anchored map tracking with mapping enabled");}
    auto cloud=slam.points();check(cloud.size()>=s.xyz.size(),"Imported points retained");
    for(unsigned i=0;i<s.xyz.size();i++)check(norm(cloud[i].xyz-s.xyz[i])<1e-14,"Imported anchor coordinates must not move");
    auto file=(root/"anchored.zmap").string();slam.save(file);std::ifstream input(file,std::ios::binary);std::vector<uint8_t> data((std::istreambuf_iterator<char>(input)),{});
    check(data[8]==2,"Anchor map version");for(unsigned i=0;i<s.xyz.size();i++)check(data[100+i*69+68]==1,"Anchor flag must persist");
    Slam loaded(c,config);loaded.load(file);Pose p;p.t={-.7,0,0};check(loaded.process(frame(c,s,p,21)).pose_valid,"Anchored map reload and localization");
    std::cout<<"IMPORTED_ANCHORS_IMMUTABLE_DURING_MAPPING_AND_PERSISTENCE_PASS\n";
}
void reviewMotion(const fs::path &root){
    auto close=[](Pose a,Pose b){double error=norm(a.t-b.t);for(unsigned i=0;i<9;i++)error+=std::abs(a.r.a[i]-b.r.a[i]);return error<1e-9;};
    for(Pose step:{Pose{M3{},V3{.2,-.1,.04}},Pose{rotation({.12,-.08,.03}),{-.2,.04,.1}},Pose{rotation({1e-10,-2e-10,3e-10}),{.1,.2,-.1}}}){
        Pose half,twice;check(scaleRigidMotion(step,.5,half)&&scaleRigidMotion(step,2,twice),"Bounded SE3 powers must exist");
        check(close(half*half,step)&&close(twice,step*step),"SE3 powers must preserve rotation/translation coupling");
        check(rigid(half)&&rigid(twice),"Scaled prediction must remain rigid");
    }
    Pose bad;check(!scaleRigidMotion(Pose{},9,bad)&&!scaleRigidMotion(Pose{},-.1,bad)&&!scaleRigidMotion(Pose{},std::numeric_limits<double>::quiet_NaN(),bad),"Unbounded/nonfinite prediction ratio rejected");
    Pose halfturn{rotation({pi,0,0}),{.1,0,0}};check(!scaleRigidMotion(halfturn,.5,bad),"Ambiguous near-pi log must fall back rather than invent an axis");
    uint32_t saved=rng;rng=0x73258a91u;Camera c=camera();Scene s=scene(350);rng=saved;
    Config options;options.mapping=false;options.max_points=400;options.max_keyframes=4;
    Config old=options;old.time_aware_motion=false;
    Slam timed(c,options),legacy(c,old),ids(c,options),rotating(c,options);
    for(unsigned i=0;i<s.xyz.size();i++)for(Slam *slam:{&timed,&legacy,&ids,&rotating})RetrievalTestAccess::add(*slam,s.xyz[i],s.descriptors[i],0);
    auto observation=[&](unsigned id,unsigned tick){Pose pose;pose.t={-.12*tick,0,0};Frame f=frame(c,s,pose,id);f.timestamp_ns=1000000000ull+uint64_t(tick)*33333334ull;return f;};
    for(unsigned i=0;i<3;i++){auto f=observation(i,i);check(timed.process(f).pose_valid&&legacy.process(f).pose_valid,"Constant-velocity setup must track");}
    auto a=timed.process(observation(8,8)),b=legacy.process(observation(8,8));
    check(a.pose_valid&&b.pose_valid&&a.local_inliers>100&&!a.recovery_attempted&&b.recovery_attempted,"Timestamp-aware gap prediction must avoid the reproduced unnecessary global recovery");
    check(std::abs(a.prediction_ratio-6)<1e-9&&a.dropped==5,"Prediction scale must use actual successful-pose time spacing");
    check(norm(a.tcw.t-V3{-.96,0,0})<1e-5,"Gap tracking must preserve pose accuracy");
    for(auto pair:{std::pair<unsigned,unsigned>{0,0},{7,1},{12,2}})check(ids.process(observation(pair.first,pair.second)).pose_valid,"Sparse identity setup");
    auto identity_gap=ids.process(observation(99,3));check(identity_gap.pose_valid&&!identity_gap.recovery_attempted&&std::abs(identity_gap.prediction_ratio-1)<1e-9,"Frame ID gaps cannot replace the timestamp velocity model");
    Pose delta{rotation({.002,.006,-.001}),{-.12,.005,.002}},truth;
    for(unsigned tick=0;tick<=8;tick++){
        if(tick)truth=delta*truth;if(tick>2&&tick<8)continue;
        auto f=frame(c,s,truth,tick);auto result=rotating.process(f);check(result.pose_valid,"Rotating constant-twist fixture must track");
        if(tick==8)check(!result.recovery_attempted&&result.local_inliers>100&&norm(result.tcw.t-truth.t)<1e-5,"Rotational gap prediction must retain geometry and avoid recovery");
    }
    auto before=timed.points();timed.resetTracking();auto after=timed.points();
    check(before.size()==after.size()&&timed.trajectory().empty()&&!timed.mapping(),"Localization reset must retain map and clear only tracking/history");
    for(unsigned i=0;i<before.size();i++)check(before[i].id==after[i].id&&norm(before[i].xyz-after[i].xyz)==0,"Localization reset must preserve every landmark");
    auto same_view=observation(9,8);same_view.timestamp_ns+=33333334;auto relocated=timed.process(same_view);
    check(relocated.pose_valid&&relocated.state==State::Relocalized&&relocated.prediction_ratio==0,"Retained fixed map must relocalize after reset");
    rejected([&]{timed.process(same_view);},"Tracking reset cannot erase monotonic input identity");
    auto next=same_view;next.id=10;next.timestamp_ns+=33333334;check(timed.process(next).pose_valid,"Resume tracking after reset");
    next.id=100;next.timestamp_ns+=1000000000;auto stale=timed.process(next);check(stale.pose_valid&&stale.prediction_ratio==0,"Long gaps must not extrapolate stale velocity");
    Frame missing;missing.id=101;missing.timestamp_ns=next.timestamp_ns+33333334;auto lost=timed.process(missing);check(!lost.pose_valid&&lost.state==State::Lost,"Time-aware prediction must keep LOST invalid");
    timed.reset();next.id=102;next.timestamp_ns+=2000000000;auto waiting=timed.process(next);check(waiting.state==State::Waiting&&waiting.points==0&&!waiting.pose_valid,"Explicit full reset still clears a localization map");
    (void)root;std::cout<<"TIME_AWARE_SE3_TRANSLATION_ROTATION_GAPS_ID_RESET_LOST_PASS\n";
}
void reviewRetrieval(){
    Camera c=camera();uint32_t seed=0x529ad713u;auto word=[&](){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;};
    for(unsigned count:{0u,1u,96u,3000u}){
        Config config;config.max_points=std::max(80u,count);config.max_keyframes=4;Config old=config;old.cached_retrieval_build=false;
        Slam cached(c,config),legacy(c,old);Frame query;query.timestamp_ns=1;
        for(unsigned i=0;i<count;i++){Descriptor d;for(auto &byte:d)byte=static_cast<uint8_t>(word());V3 xyz{double(i%17)*.02,double(i%11)*.02,6};
            RetrievalTestAccess::add(cached,xyz,d,0);RetrievalTestAccess::add(legacy,xyz,d,0);
            if(i<96){Feature f;f.raw=f.uv=c.project(xyz);f.descriptor=d;if(i%5==0)f.descriptor[31]^=1;query.features.push_back(f);}
        }
        for(unsigned i=0,n=std::min(8u,unsigned(query.features.size()));i<n;i++)query.features.push_back(query.features[i]);
        for(unsigned repeat=0;repeat<2;repeat++){
            Status a,b;auto x=RetrievalTestAccess::query(cached,query,a),y=RetrievalTestAccess::query(legacy,query,b);
            check(RetrievalTestAccess::sameIndex(cached,legacy),"Every selected bit, slot, descriptor, head and bucket entry must equal the original index");
            check(a.retrieval_builds==(repeat?0:1)&&b.retrieval_builds==a.retrieval_builds&&x.size()==y.size(),"Build reuse may not change query count or invalidation");
            for(unsigned i=0;i<x.size();i++)check(x[i].feature==y[i].feature&&x[i].landmark==y[i].landmark&&norm(x[i].xyz-y[i].xyz)==0&&distance(x[i].uv,y[i].uv)==0,"Hash reuse must retain all candidates, ties, ordering and geometry");
        }
        check(RetrievalTestAccess::hashScratch(cached)<=config.max_points*2u,"Cached hashes must remain bounded to one uint16 per configured landmark slot");
    }
    Config maximum;maximum.max_points=50000;Slam bounded(c,maximum);
    check(RetrievalTestAccess::hashScratch(bounded)<=100000,"Maximum configured map cannot grow hash scratch beyond100000B");
    std::cout<<"RETRIEVAL_BUILD_ALL_BITS_BUCKETS_ORDER_EMPTY_SINGLE_96_3000_PASS\n";
}
void reviewAffinity(){
    auto legacy=cpuPlan("legacy",true),nodisplay=cpuPlan("legacy",false),automatic=cpuPlan("capture-auto",true),dedicated=cpuPlan("capture-dedicated",true);
    check(legacy.capture==1&&legacy.slam==1&&legacy.orb==2&&legacy.render==2&&nodisplay.capture==2,"Legacy CPU assignment remains available for controlled A/B");
    check(automatic.capture==3&&automatic.slam==1&&automatic.orb==2&&automatic.render==2,"Migratable capture plan must expose both target CPUs");
    check(dedicated.capture==1&&dedicated.slam==2&&dedicated.orb==2&&dedicated.render==2,"Dedicated decode plan must separate capture from SLAM/UI/control");
    rejected([]{cpuPlan("invalid",true);},"Unknown policy must not silently select a CPU");check(!setCpuMask(0),"Empty CPU mask must never change scheduling");
    ThreadAffinityRecord record;record.begin(3,false);auto s=record.snapshot();check(!s.applied&&s.requested_mask==0,"Diagnostic record must not claim unapplied affinity");
    std::cout<<"CPU_POLICY_MASKS_LEGACY_AUTO_DEDICATED_RECORD_PASS\n";
}
void reviewRawIndex(const fs::path &root){
    auto path=root/"indexed.gray8",index=root/"raw_index.csv";std::vector<uint8_t> gray(960*720,0x31);
    {std::ofstream out(path,std::ios::binary);for(unsigned i=0;i<2;i++)out.write(reinterpret_cast<const char*>(gray.data()),gray.size());}
    auto write=[&](uint64_t stamp,unsigned offset,bool extra=false){std::ofstream out(index);out<<"frame_index,timestamp_ns,byte_offset,bytes\n0,1000000001,0,691200\n1,"<<stamp<<','<<offset<<",691200\n";if(extra)out<<"2,1100000000,1382400,691200\n";};
    write(1046712345,691200);{auto source=rawCamera(path.string(),30,index.string());GrayFrame f;check(source->next(f)&&f.id==0&&f.timestamp_ns==1000000001&&f.pixels==gray,"RAW index first identity/pixels");check(source->next(f)&&f.id==1&&f.timestamp_ns==1046712345&&f.pixels==gray,"RAW must retain irregular integer nanoseconds exactly");check(!source->next(f),"RAW indexed EOF");}
    write(1000000001,691200);{auto source=rawCamera(path.string(),30,index.string());GrayFrame f;source->next(f);rejected([&]{source->next(f);},"Repeated RAW timestamp rejected");}
    write(1046712345,691201);{auto source=rawCamera(path.string(),30,index.string());GrayFrame f;source->next(f);rejected([&]{source->next(f);},"RAW byte offset mismatch rejected");}
    write(1046712345,691200,true);{auto source=rawCamera(path.string(),30,index.string());GrayFrame f;source->next(f);source->next(f);rejected([&]{source->next(f);},"Extra index rows rejected");}
    {std::ofstream out(index);out<<"frame_index,timestamp_ns,byte_offset,bytes\n0,1000000001,0,691200\n";}
    {auto source=rawCamera(path.string(),30,index.string());GrayFrame f;source->next(f);rejected([&]{source->next(f);},"Missing RAW timestamp row rejected");}
    std::cout<<"RAW_MANIFEST_INTEGER_TIME_ID_OFFSET_EOF_REJECTION_PASS\n";
}
}
int main(int argc,char **argv){try{if(argc!=2)throw std::runtime_error("Test needs isolated output directory");
    auto root=zslam::fs::path(argv[1])/("test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));zslam::fs::create_directories(root);
    cameraFrames(fs::path(argv[0]).parent_path()/"test-fixtures/camera",root);records();decodeCache();spatialBins();geometry();mapping(root);ports();pipeline();grayPool();preview();trajectoryProjection();retrievalInvalidation(root);csvRetention(root);rawFiles(root);anchors(root);reviewMotion(root);reviewRetrieval();reviewAffinity();reviewRawIndex(root);std::cout<<"ALL_TESTS_PASS output="<<root.string()<<'\n';return 0;
}catch(const std::exception &e){std::cerr<<"TEST_FAILED "<<e.what()<<'\n';return 1;}}
