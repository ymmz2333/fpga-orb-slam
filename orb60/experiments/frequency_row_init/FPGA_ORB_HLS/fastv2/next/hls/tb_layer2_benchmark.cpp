// Functional/cycle bench only; no PS firmware is modified or timed here.
#include "fastv2.hpp"
#include "layer2.hpp"
#include "image_test_reference.hpp"
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>

template<typename T>
static std::vector<T> read_binary(const std::string& path, size_t count) {
    std::ifstream input(path, std::ios::binary);
    std::vector<T> result(count);
    if (!input.read(reinterpret_cast<char*>(result.data()), count*sizeof(T)) || input.peek()!=EOF)
        throw std::runtime_error("invalid vector: "+path);
    return result;
}

int main(int argc, char** argv) {
    try {
        using namespace next_image_test;
        if (argc!=2) throw std::runtime_error("expected vector directory");
        const std::string directory=argv[1];
        std::ifstream meta(directory+"/cases.bin",std::ios::binary);
        uint32_t header[4]={};
        if (!meta.read(reinterpret_cast<char*>(header),sizeof(header)) || header[0]!=0x60b20001 ||
            header[1]!=1 || header[2]!=3 || header[3]!=24) throw std::runtime_error("invalid case header");
        for (unsigned frame=0;frame<header[2];++frame) {
            auto image=read_binary<uint64_t>(directory+"/f"+std::to_string(frame)+"_l0_input.bin",kPortWords);
            uint64_t cycles=0; unsigned selected_count=0,candidate_count=0;
            for (int level=0;level<8;++level) {
                uint32_t control[8]={};
                if (!meta.read(reinterpret_cast<char*>(control),sizeof(control)) || control[0]!=frame ||
                    control[1]!=unsigned(level) || control[2]!=unsigned(kWidths[level]) ||
                    control[3]!=unsigned(kHeights[level])) throw std::runtime_error("invalid case control");
                const std::string prefix=directory+"/f"+std::to_string(frame)+"_l"+std::to_string(level);
                const auto input_ref=read_binary<uint64_t>(prefix+"_input.bin",kPortWords);
                const auto blur_ref=read_binary<uint64_t>(prefix+"_blur.bin",kPortWords);
                const auto resize_ref=read_binary<uint64_t>(prefix+"_resize.bin",kPortWords);
                const auto points_ref=read_binary<uint64_t>(prefix+"_points.bin",2000);
                const auto summary_ref=read_binary<uint64_t>(prefix+"_summary.bin",8);
                if (std::memcmp(image.data(),input_ref.data(),kWidths[level]*kHeights[level]))
                    throw std::runtime_error("previous Resize is not next layer input");
                const auto image_before=image;
                std::vector<uint64_t> blur(kPortWords,kPoison),next(kPortWords,kPoison),points(2000);
                std::memset(points.data(),0xa5,16000);
                uint64_t summary[8]={},stats[8]={};
                const int status=fastv2_layer2_hls(image.data(),blur.data(),next.data(),points.data(),summary,stats,
                    level,control[4],control[5],control[6],control[7],1000);
                orb60::LayerStats counters; std::memcpy(&counters,stats,64);
                fastv2::Result result; std::memcpy(&result,summary,64);
                const unsigned bytes=((kWidths[level]*kHeights[level]+7)/8)*8;
                const unsigned next_bytes=level<7 ? ((kWidths[level+1]*kHeights[level+1]+7)/8)*8 : 0;
                if (status || blur!=blur_ref || next!=resize_ref || points!=points_ref || image!=image_before ||
                    std::memcmp(summary,summary_ref.data(),64) || counters.version!=orb60::kLayerVersion ||
                    counters.status || counters.level!=unsigned(level) || counters.input_read_bytes!=bytes ||
                    counters.blur_write_bytes!=bytes || counters.resize_write_bytes!=next_bytes ||
                    counters.dataflow_cycles<1 || counters.dataflow_cycles>=4000000)
                    throw std::runtime_error("exact image/point/summary/counter mismatch: "+prefix);
                cycles+=counters.dataflow_cycles; selected_count+=result.selected_count; candidate_count+=result.candidate_count;
                std::cout<<"LAYER2_BENCH_LAYER frame="<<frame<<" level="<<level<<" cycles="<<counters.dataflow_cycles
                    <<" candidates="<<result.candidate_count<<" selected="<<result.selected_count<<'\n';
                if(level<7) image.swap(next);
            }
            std::cout<<"LAYER2_BENCH_FRAME frame="<<frame<<" dataflow_cycles="<<cycles
                <<" candidates="<<candidate_count<<" selected="<<selected_count<<'\n';
        }
        if(meta.peek()!=EOF) throw std::runtime_error("trailing control records");
        std::cout<<"LAYER2_BENCH_EXACT_PASS cases="<<header[3]<<'\n';
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<"LAYER2_BENCH_FAIL "<<error.what()<<'\n'; return 1;
    }
}
