#pragma once

#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <hls_stream.h>
#else
#include <deque>
#include <stdexcept>
namespace hls {
/** Host-only functional stream; finite FIFO timing requires RTL co-simulation. */
template <typename T> class stream {
    std::deque<T> values;
public:
    /**
     * @brief Append one functional token to the host stream.
     * @param value Token to publish to the single downstream consumer.
     * @note This unbounded host adapter does not model hardware backpressure.
     */
    void write(const T& value) { values.push_back(value); }
    /**
     * @brief Consume one token and fail deterministically on a count mismatch.
     * @return Oldest available token.
     * @throws std::runtime_error If the producer emitted too few tokens.
     */
    T read() {
        if (values.empty()) throw std::runtime_error("next stream token underflow");
        T value = values.front(); values.pop_front(); return value;
    }
    /**
     * @brief Check whether all functional tokens have been consumed.
     * @return True when no pending token remains.
     */
    bool empty() const { return values.empty(); }
    bool read_nb(T& value) {
        if (values.empty()) return false;
        value = read(); return true;
    }
};
} // namespace hls
#endif
