// Compare compressed geometry with the immutable scalar baseline tables.
#include "../baseline_include/fastv2_profile_rom.hpp"
#include "geometry_runs.hpp"
#include <iostream>
#include <stdexcept>

int main() {
    try {
        unsigned checked=0;
        for (int level=0;level<8;++level) {
            const auto& p=fastv2_profile::kProfiles[level];
            int ix=fastv2_segment::kPairRunOffsets[level],iy=fastv2_segment::kYRunOffsets[level];
            for (int x=0;x<p.width;x+=2) {
                if (x/2>=fastv2_segment::kPairRunEnds[ix]) ++ix;
                const uint64_t a=fastv2_profile::kAxisXInfo[p.x_info_offset+x];
                const uint64_t b=x+1<p.width ? fastv2_profile::kAxisXInfo[p.x_info_offset+x+1] : 0;
                if (fastv2_segment::kPairRunInfo[ix]!=(a|(b<<30)))
                    throw std::runtime_error("paired geometry changed");
                ++checked;
            }
            for (int y=0;y<p.height;++y) {
                if (y>=fastv2_segment::kYRunEnds[iy]) ++iy;
                if (fastv2_segment::kYRunInfo[iy]!=fastv2_profile::kAxisYInfo[p.y_info_offset+y])
                    throw std::runtime_error("vertical geometry changed");
                ++checked;
            }
        }
        std::cout<<"GEOMETRY_RUNS_FROZEN_EXACT_PASS records="<<checked<<'\n';
        return 0;
    } catch (const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
