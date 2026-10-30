#define ORB60_FRONT2_TOP 1
#include "fastv2_hls.cpp"

#if !defined(__SYNTHESIS__) && !defined(FASTV2_HLS_CSIM)
extern "C" int next_test_front2_merge(const uint64_t* first, const uint64_t* second,
    const uint8_t* masks, int count, uint64_t* output) {
    hls::stream<CandidatePair2> pairs;
    hls::stream<uint64_t> tokens;
    int expected = 0;
    for (int i = 0; i < count; ++i) {
        pairs.write(CandidatePair2{first[i], second[i], masks[i]});
        expected += int(masks[i]&1) + int((masks[i]>>1)&1);
    }
    pairs.write(CandidatePair2{(UINT64_C(1)<<63)|uint64_t(unsigned(expected)),0,0});
    serialize_front2_pairs(pairs, tokens);
    int n = 0;
    for (;;) {
        const uint64_t value = tokens.read();
        if (value>>63) {assert(int(uint32_t(value))==n); break;}
        output[n++] = value;
    }
    return n;
}
#endif
