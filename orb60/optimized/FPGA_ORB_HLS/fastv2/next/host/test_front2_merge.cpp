#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
extern "C" int next_test_front2_merge(const uint64_t*, const uint64_t*, const uint8_t*, int, uint64_t*);
int main() {
    try {
        constexpr int n=4096;
        for (int pattern=0;pattern<5;++pattern) {
            std::vector<uint64_t> first(n),second(n),wanted,actual(2*n);
            std::vector<uint8_t> masks(n);
            for (int i=0;i<n;++i) {
                first[i]=2*i+1; second[i]=2*i+2;
                masks[i]=pattern<4 ? pattern : ((i*13+(i/7))&3);
                if(masks[i]&1)wanted.push_back(first[i]);
                if(masks[i]&2)wanted.push_back(second[i]);
            }
            int count=next_test_front2_merge(first.data(),second.data(),masks.data(),n,actual.data());
            actual.resize(count);
            if(actual!=wanted)throw std::runtime_error("double-candidate raster merge/count mismatch");
        }
        std::cout<<"FRONT2_MERGE_PASS masks=0,1,2,3,mixed double_candidate_runs=4096\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
