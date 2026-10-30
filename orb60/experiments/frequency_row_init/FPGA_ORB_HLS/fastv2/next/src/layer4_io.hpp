/* GPL-3.0-or-later: overlap fixed DDR blocks and streaming through two credits. */
typedef uint64_t LayerWordBlock[64];

void load_layer_blocks(const uint64_t* image,hls::stream_of_blocks<LayerWordBlock>& blocks,int pixels) {
#pragma HLS INLINE off
    const int count=(pixels+7)/8;
    for(int base=0;base<count;base+=64) {
        const int n=count-base<64?count-base:64;
        hls::write_lock<LayerWordBlock> lock(blocks);LayerWordBlock& block=lock;
        std::memcpy(block,image+base,size_t(unsigned(n)&127u)*8);
    }
}
void emit_layer_blocks(hls::stream_of_blocks<LayerWordBlock>& blocks,hls::stream<uint64_t>& words,int pixels) {
#pragma HLS INLINE off
    const int count=(pixels+7)/8;
    for(int base=0;base<count;base+=64) {
        const int n=count-base<64?count-base:64;
        hls::read_lock<LayerWordBlock> lock(blocks);LayerWordBlock& block=lock;
EmitLayerReadWords:
        for(int i=0;i<n;++i) {
#pragma HLS PIPELINE II=1
            words.write(block[i]);
        }
    }
}
void layer4_read_dataflow(const uint64_t* image,hls::stream<uint64_t>& words,int pixels) {
#pragma HLS INLINE off
    hls::stream_of_blocks<LayerWordBlock> blocks;
#pragma HLS BIND_STORAGE variable=blocks type=ram_s2p impl=bram
#pragma HLS DATAFLOW
    load_layer_blocks(image,blocks,pixels);emit_layer_blocks(blocks,words,pixels);
}
template<int Tag> void collect_layer_blocks(hls::stream<uint64_t>& words,hls::stream_of_blocks<LayerWordBlock>& blocks,int pixels) {
#pragma HLS INLINE off
    const int count=(pixels+7)/8;
    for(int base=0;base<count;base+=64) {
        const int n=count-base<64?count-base:64;
        hls::write_lock<LayerWordBlock> lock(blocks);LayerWordBlock& block=lock;
CollectLayerBlocks:
        for(int i=0;i<n;++i) {
#pragma HLS PIPELINE II=1
            block[i]=words.read();
        }
    }
}
template<int Tag> void flush_layer_blocks(hls::stream_of_blocks<LayerWordBlock>& blocks,uint64_t* output,int pixels,hls::stream<uint8_t>& done) {
#pragma HLS INLINE off
    const int count=(pixels+7)/8;
    for(int base=0;base<count;base+=64) {
        const int n=count-base<64?count-base:64;
        hls::read_lock<LayerWordBlock> lock(blocks);LayerWordBlock& block=lock;
        std::memcpy(output+base,block,size_t(unsigned(n)&127u)*8);
    }
    done.write(1);
}
template<int Tag> void layer4_write_dataflow(hls::stream<uint64_t>& words,uint64_t* output,int pixels,hls::stream<uint8_t>& done) {
#pragma HLS INLINE off
    hls::stream_of_blocks<LayerWordBlock> blocks;
#pragma HLS BIND_STORAGE variable=blocks type=ram_s2p impl=bram
#pragma HLS DATAFLOW
    collect_layer_blocks<Tag>(words,blocks,pixels);flush_layer_blocks<Tag>(blocks,output,pixels,done);
}
