#pragma once
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <hls_streamofblocks.h>
#else
#include <deque>
#include <memory>
#include <stdexcept>
namespace hls {
template<typename T> class read_lock;
template<typename T> class write_lock;
/** Functional ownership adapter only: finite depth/backpressure is an RTL gate. */
template<typename T, int Depth=2> class stream_of_blocks {
    struct Block { T value; };
    std::deque<std::unique_ptr<Block>> blocks;
    std::unique_ptr<Block> writing;
    bool reading=false;
    friend class read_lock<T>;
    friend class write_lock<T>;
    T& acquire_write() {
        if(writing) throw std::runtime_error("duplicate block write lock");
        writing.reset(new Block{});return writing->value;
    }
    void release_write() {blocks.push_back(std::move(writing));}
    T& acquire_read() {
        if(reading || blocks.empty()) throw std::runtime_error("block read ownership/count error");
        reading=true;return blocks.front()->value;
    }
    void release_read() {reading=false;blocks.pop_front();}
public:
    bool empty() const {return blocks.empty();}
    stream_of_blocks()=default;
    stream_of_blocks(const stream_of_blocks&)=delete;
};
template<typename T> class write_lock {
    stream_of_blocks<T>& channel; T& value;
public:
    explicit write_lock(stream_of_blocks<T>& s):channel(s),value(s.acquire_write()) {}
    ~write_lock() {channel.release_write();}
    operator T&() {return value;}
    write_lock(const write_lock&)=delete;
};
template<typename T> class read_lock {
    stream_of_blocks<T>& channel; T& value;
public:
    explicit read_lock(stream_of_blocks<T>& s):channel(s),value(s.acquire_read()) {}
    ~read_lock() {channel.release_read();}
    operator T&() {return value;}
    read_lock(const read_lock&)=delete;
};
}
#endif
