#include <ap_int.h>
#include <stdint.h>

static float unpack(ap_uint<32> bits) {
    union { uint32_t u; float f; } x; x.u=bits.to_uint(); return x.f;
}
static ap_uint<32> pack(float value) {
    union { uint32_t u; float f; } x; x.f=value; return x.u;
}
static bool finite32(float value) { return (pack(value).range(30,23)!=255); }

// Input: float depth, RGB little endian, u|v<<16, mask (word3 bit0).
// Output: local XYZ, world XYZ, RGB, original v*960+u. Stable compaction.
extern "C" unsigned point_project_hls(const ap_uint<128>* samples,
    const ap_uint<128>* config, ap_uint<256>* points, ap_uint<256>* stats,
    unsigned count, unsigned capacity) {
#pragma HLS INTERFACE m_axi port=samples offset=slave bundle=input_mem depth=172800 max_read_burst_length=32 num_read_outstanding=8
#pragma HLS INTERFACE m_axi port=config offset=slave bundle=input_mem depth=6
#pragma HLS INTERFACE m_axi port=points offset=slave bundle=output_mem depth=172800 max_write_burst_length=32 num_write_outstanding=8
#pragma HLS INTERFACE m_axi port=stats offset=slave bundle=output_mem depth=1
#pragma HLS INTERFACE s_axilite port=samples bundle=control
#pragma HLS INTERFACE s_axilite port=config bundle=control
#pragma HLS INTERFACE s_axilite port=points bundle=control
#pragma HLS INTERFACE s_axilite port=stats bundle=control
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=capacity bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    unsigned error=0, valid=0, written=0, seen=0;
    float c[24];
#pragma HLS ARRAY_PARTITION variable=c complete
    if (count>172800 || capacity>172800) error=2;
    if (!error) {
        for (unsigned i=0;i<6;i++) {
#pragma HLS PIPELINE II=1
            ap_uint<128> word=config[i];
            for (unsigned j=0;j<4;j++) {
#pragma HLS UNROLL
                c[4*i+j]=unpack(word.range(j*32+31,j*32));
            }
        }
        for (unsigned i=0;i<21;i++) {
#pragma HLS UNROLL
            if (!finite32(c[i])) error=4;
        }
    }
    if (!error) for (unsigned i=0;i<count;i++) {
#pragma HLS PIPELINE II=1
        ap_uint<128> s=samples[i];
        unsigned u=s.range(79,64), v=s.range(95,80);
        float z=unpack(s.range(31,0));
        bool good=s[96] && u<960 && v<720 && finite32(z) && z>0;
        float x=((c[0]*float(u)+c[1]*float(v))+c[2])*z;
        float y=((c[3]*float(u)+c[4]*float(v))+c[5])*z;
        float lz=((c[6]*float(u)+c[7]*float(v))+c[8])*z;
        float wx=((c[9]*x+c[10]*y)+c[11]*lz)+c[12];
        float wy=((c[13]*x+c[14]*y)+c[15]*lz)+c[16];
        float wz=((c[17]*x+c[18]*y)+c[19]*lz)+c[20];
        good=good && finite32(x) && finite32(y) && finite32(lz) && finite32(wx) && finite32(wy) && finite32(wz);
        seen++;
        if (good) {
            valid++;
            if (written<capacity) {
                ap_uint<256> out=0;
                out.range(31,0)=pack(x);out.range(63,32)=pack(y);out.range(95,64)=pack(lz);
                out.range(127,96)=pack(wx);out.range(159,128)=pack(wy);out.range(191,160)=pack(wz);
                out.range(223,192)=s.range(63,32)&0xffffff;
                out.range(255,224)=v*960+u;
                points[written++]=out;
            } else error|=1;
        }
    }
    ap_uint<256> report=0;
    report.range(31,0)=seen;report.range(63,32)=valid;report.range(95,64)=written;
    report.range(127,96)=error;report.range(159,128)=0x50434c31;report.range(191,160)=1;
    stats[0]=report;
    return error;
}
