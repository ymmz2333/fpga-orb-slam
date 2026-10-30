// Test-only AXIS boundary for the exact production serializer. No new DMA/IP in
// the routed system; generated RTL is never modified to inject four candidates.
#include "merge4.hpp"
#define ORB60_FRONT2_TOP 1
#define ORB60_LAYER_TOP 1
#include "fastv2_hls.cpp"
namespace {
#include "front4_stream.hpp"
}
extern "C" void fastv2_merge4_hls(hls::stream<CandidateQuad>& packets,hls::stream<uint64_t>& tokens) {
#pragma HLS INTERFACE axis port=packets depth=257
#pragma HLS INTERFACE axis port=tokens depth=1025
#pragma HLS AGGREGATE variable=packets compact=bit
#pragma HLS INTERFACE ap_ctrl_hs port=return
    serialize_front4_quads(packets,tokens);
}
