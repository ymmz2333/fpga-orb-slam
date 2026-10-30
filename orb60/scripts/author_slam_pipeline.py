"""Author the incremental0018 patch against a checkout with0016/0017 applied.

Used once to create the reviewed patch; normal deployment uses install_slam_network.
"""
import argparse
import difflib
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    patches=a.workspace/'rk3588/orbslam3_cpu_baseline/patches'
    # Share exactly the same validation/conversion in synchronous and async modes.
    header=patches/'FpgaORB.h';h=header.read_text()
    if 'static void decode(' not in h:
        start=h.index('            const unsigned budgets[8]')
        end=h.index('            std::cout<<"FPGA_ORB_NET',start)
        body=h[start:end]
        body=body.replace('            ','        ')
        body=body.replace('auto scales=extractor->GetScaleFactors();', 'auto scales=extractor->GetScaleFactors();')
        method='    static void decode(const std::vector<uint8_t>& payload,unsigned count,ORBextractor *extractor,\n' \
               '                       std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,double& decode_ms) {\n' \
               '        require(extractor->GetFeatures()==1000&&extractor->GetLevels()==8&&extractor->GetScaleFactor()==1.2f,"fixed FPGA profile");\n' \
               '        require(count<=1000&&payload.size()==128+count*64+1024,"record length");\n' \
               '        auto start=std::chrono::steady_clock::now();\n'+body.replace('Clock::now()', 'std::chrono::steady_clock::now()')+'    }\n'
        h=h[:start]+'            decode(payload,count,extractor,keys,descriptors,decode_ms);\n'+h[end:]
        h=h.replace('class FpgaORB {','class FpgaORB {\nprotected:',1)
        h=h.replace('public:\n    FpgaORB()',method+'public:\n    FpgaORB()',1)
        h=h.replace('<<" network_ms="<<network_ms<<" cpu_orb=0"',
                    '<<" network_ms="<<network_ms<<" record_crc="<<orb_crc32(payload.data()+128,count*64)<<" cpu_orb=0"')
        header.write_text(h)
    originals={};updated={}
    def replace(name,old,new):
        path=a.source/name;text=updated.get(name,path.read_text());originals.setdefault(name,text)
        assert text.count(old)==1,(name,old);updated[name]=text.replace(old,new)
    replace('include/FeatureIO.h','    static bool FPGAActive();',
            '    static bool FPGAActive();\n    static bool PipelineActive();\n    static void StartPipeline();\n'
            '    static void QueueFrame(uint64_t timestamp,const cv::Mat& image);\n'
            '    static void FinishPipeline();\n    static void AbortPipeline();')
    replace('src/FeatureIO.cc','#include "FpgaORB.h"','#include "FpgaORB.h"\n#include "FpgaPipeline.h"\n#include <memory>')
    replace('src/FeatureIO.cc','void FeatureIO::Configure(',
            'namespace { std::unique_ptr<FpgaPipeline> pipeline; }\nvoid FeatureIO::Configure(')
    replace('src/FeatureIO.cc','selected=="fpga","invalid mode"','selected=="fpga" || selected=="fpga-pipeline","invalid mode"')
    replace('src/FeatureIO.cc','    mode=selected; root=directory;',
            '    pipeline.reset();mode=selected; root=directory;')
    replace('src/FeatureIO.cc','if(mode=="fpga") { require(normal_features==1000',
            'if(FPGAActive()) { require(normal_features==1000')
    replace('src/FeatureIO.cc','bool FeatureIO::FPGAActive() { return mode=="fpga"; }',
            'bool FeatureIO::FPGAActive() { return mode=="fpga" || PipelineActive(); }\n'
            'bool FeatureIO::PipelineActive() { return mode=="fpga-pipeline"; }\n'
            'void FeatureIO::StartPipeline() {\n'
            '    require(PipelineActive()&&!pipeline,"pipeline start order");pipeline.reset(new FpgaPipeline(root));\n}\n'
            'void FeatureIO::QueueFrame(uint64_t timestamp,const cv::Mat& image) {\n'
            '    require(PipelineActive()&&bool(pipeline),"pipeline not configured");pipeline->submit(timestamp,image);\n}\n'
            'void FeatureIO::FinishPipeline() { if(pipeline)pipeline->finish(); }\n'
            'void FeatureIO::AbortPipeline() { if(pipeline)pipeline->abort(); }')
    replace('src/FeatureIO.cc','    if(mode=="fpga") {\n        static FpgaORB receiver;',
            '    if(PipelineActive()) {\n'
            '        mono_left=pipeline->consume(stats.timestamp_ns,role,extractor,keys,descriptors,stats.read_ms,stats.decode_ms);\n'
            '    } else if(mode=="fpga") {\n        static FpgaORB receiver;')
    name='Examples/Monocular/mono_euroc.cc'
    replace(name,'#include<FeatureIO.h>','#include<FeatureIO.h>\n#include<FpgaReplayInput.h>\n#include<memory>')
    replace(name,'    bool bUseViewer = false;','    bool bUseViewer = false, unpaced=false;')
    replace(name,'        else if(argument == "--viewer")',
            '        else if(argument == "--unpaced")\n            unpaced=true;\n        else if(argument == "--viewer")')
    replace(name,'native|dump|inject|fpga]','native|dump|inject|fpga|fpga-pipeline] [--unpaced]')
    replace(name,'    const int num_seq = (argc-3)/2;',
            '    const int num_seq = (argc-3)/2;\n'
            '    if(ORB_SLAM3::FeatureIO::PipelineActive()&&num_seq!=1) throw runtime_error("FPGA pipeline accepts one sequence per connection");')
    replace(name,'    float imageScale = SLAM.GetImageScale();',
            '    float imageScale = SLAM.GetImageScale();\n'
            '    if(ORB_SLAM3::FeatureIO::PipelineActive()&&imageScale!=1.f) throw runtime_error("fixed FPGA image scale must be1");')
    replace(name,'    for (seq = 0; seq<num_seq; seq++)\n    {\n\n        // Main loop',
            '    auto replayStart=std::chrono::steady_clock::now();\n'
            '    for (seq = 0; seq<num_seq; seq++)\n    {\n'
            '        std::unique_ptr<ORB_SLAM3::FpgaReplayInput> input;\n'
            '        if(ORB_SLAM3::FeatureIO::PipelineActive()) input.reset(new ORB_SLAM3::FpgaReplayInput(vstrImageFilenames[seq]));\n\n        // Main loop')
    replace(name,'im = cv::imread(vstrImageFilenames[seq][ni],cv::IMREAD_UNCHANGED);',
            'im = input ? input->get(size_t(ni)) : cv::imread(vstrImageFilenames[seq][ni],cv::IMREAD_UNCHANGED);')
    replace(name,'            if(ttrack<T) {','            if(!unpaced && ttrack<T) {')
    replace(name,'        if(seq < num_seq - 1)', '        if(input) input->finish();\n\n        if(seq < num_seq - 1)')
    replace(name,'    // Stop all threads',
            '    const double replaySeconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-replayStart).count();\n'
            '    cout<<"REPLAY_SUMMARY frames="<<tot_images<<" seconds="<<replaySeconds<<" fps="<<tot_images/replaySeconds<<endl;\n'
            '    // Stop all threads')
    diff=[]
    for name,text in updated.items():
        diff.extend(difflib.unified_diff(originals[name].splitlines(True),text.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    (patches/'0018-fpga-frame-pipeline.patch').write_text(''.join(diff))
    print('AUTHORED0018_INCREMENTAL_PATCH')


if __name__=='__main__':main()
