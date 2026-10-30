/* GPL-3.0-or-later: read-only manual-burst direction experiment. */
#pragma once
#include <cstdint>

#ifndef ORB60_DESCRIPTOR_PREFETCH
#define ORB60_DESCRIPTOR_PREFETCH 0
#endif
#if ORB60_DESCRIPTOR_PREFETCH != 0 && ORB60_DESCRIPTOR_PREFETCH != 2 && ORB60_DESCRIPTOR_PREFETCH != 4 && ORB60_DESCRIPTOR_PREFETCH != 8
#error "Descriptor prefetch must be 0 (original loader), 2, 4 or 8"
#endif

#if ORB60_DESCRIPTOR_PREFETCH && (defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM))
#include <hls_burst_maxi.h>
typedef hls::burst_maxi<uint64_t> DescriptorReadPort;
#elif ORB60_DESCRIPTOR_PREFETCH
#include <deque>
#include <memory>
#include <stdexcept>
// Functional ownership model only. Finite adapter credits/backpressure are RTL
// gates. Copies share the request queue, as the two DATAFLOW actors share a port.
class DescriptorReadPort {
    struct Request {size_t offset;unsigned words;};
    struct State {
        const uint64_t* memory;
        std::deque<Request> requests;
        unsigned beat=0;
        explicit State(const uint64_t* p):memory(p) {}
        ~State() {if(!requests.empty()) std::terminate();}
    };
    std::shared_ptr<State> state;
public:
    DescriptorReadPort(const uint64_t* p):state(new State(p)) {}
    void read_request(size_t offset,unsigned words) {
        if(!words) throw std::runtime_error("empty descriptor read request");
        state->requests.push_back({offset,words});
    }
    uint64_t read() {
        if(state->requests.empty()) throw std::runtime_error("descriptor read without request");
        const Request& request=state->requests.front();
        const uint64_t word=state->memory[request.offset+state->beat++];
        if(state->beat==request.words) {state->beat=0;state->requests.pop_front();}
        return word;
    }
};
#else
typedef const uint64_t* DescriptorReadPort;
#endif
