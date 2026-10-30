#include "FPGA_ORB_HLS/fastv2/next/include/a32_quantize_exact.hpp"
#include <cstdint>
#include <iostream>
#include <stdexcept>

static int old_search(uint32_t angle) {
    const uint32_t rounded=angle+368640u;int lo=0,hi=33;
    for(int k=0;k<6;++k) {const int mid=(lo+hi)>>1;
        if(rounded>=uint32_t(mid)*737280u) lo=mid;else hi=mid;}
    return lo&31;
}
int main() {
    uint64_t checked=0;
    // Independent integer golden for every valid Q16 angle, all32 bins.
    for(uint32_t a=0;a<23592960u;++a) {
        const int golden=int((uint64_t(a)*32+11796480u)/23592960u%32);
        if(orb60_quantize_a32_exact(a)!=golden) throw std::runtime_error("Valid-angle golden mismatch");
        ++checked;
    }
    // Original helper's clamping/wrap semantics outside the CORDIC domain.
    uint32_t state=0x600032u;
    for(unsigned n=0;n<1000000;++n) {
        state=1664525u*state+1013904223u;
        if(orb60_quantize_a32_exact(state)!=old_search(state)) throw std::runtime_error("Full32 search mismatch");
        ++checked;
    }
    for(uint32_t threshold: {0u,368640u,23592960u,UINT32_MAX})
        for(int delta=-2;delta<=2;++delta) {
            const uint32_t a=threshold+uint32_t(delta);
            if(orb60_quantize_a32_exact(a)!=old_search(a)) throw std::runtime_error("Wrap/boundary mismatch");
            ++checked;
        }
    std::cout<<"A32_QUANTIZE_EXACT_PASS angles="<<checked<<" bins=32 full32_search_preserved\n";
}
