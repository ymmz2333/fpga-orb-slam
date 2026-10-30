/* GPL-3.0-or-later: exact signed FAST with explicit arithmetic boundaries. */
void fast_differences(uint8_t center,const uint8_t ring[16],ScoreSigned bright[16],ScoreSigned dark[16]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=1 max=1
#pragma HLS ARRAY_PARTITION variable=ring complete
#pragma HLS ARRAY_PARTITION variable=bright complete
#pragma HLS ARRAY_PARTITION variable=dark complete
    for(int i=0;i<16;++i) {
#pragma HLS UNROLL
        bright[i]=ScoreSigned(int(ring[i])-int(center));
        dark[i]=ScoreSigned(int(center)-int(ring[i]));
    }
}
template<int Step> void fast_arc_minimum(const ScoreSigned input[16],ScoreSigned output[16]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=1 max=1
#pragma HLS ARRAY_PARTITION variable=input complete
#pragma HLS ARRAY_PARTITION variable=output complete
    for(int i=0;i<16;++i) {
#pragma HLS UNROLL
        const ScoreSigned a=input[i],b=input[(i+Step)&15],c=input[(i+2*Step)&15];
        const ScoreSigned ab=a<b?a:b;output[i]=ab<c?ab:c;
    }
}
void fast_arc_response(const ScoreSigned bright[16],const ScoreSigned dark[16],ScoreSigned response[16]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=1 max=1
#pragma HLS ARRAY_PARTITION variable=bright complete
#pragma HLS ARRAY_PARTITION variable=dark complete
#pragma HLS ARRAY_PARTITION variable=response complete
    for(int i=0;i<16;++i) {
#pragma HLS UNROLL
        response[i]=bright[i]>dark[i]?bright[i]:dark[i];
    }
}
