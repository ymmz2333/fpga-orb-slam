#pragma once
#include <algorithm>
#include <array>
#include <cstdint>

// Legacy experiments retain their exact 10ns service epochs and PRNG trace.
// Board-spec mode instead has a shared bytes/s DDR budget, and one independent
// 64-bit read AND write beat per HP clock. This is a capacity model, not a DDRC
// bank/refresh/turnaround/PHY simulation or a measured effective-bandwidth claim.
struct DdrTimeBudget {
    static constexpr uint64_t beat_ps=10000;
    static constexpr uint64_t byte_beat_ps=UINT64_C(8000000000000);
    unsigned period_ps,beats;
    uint64_t board_bytes_per_second;
    uint64_t aggregate=0;
    uint64_t phase=0;
    std::array<uint64_t,4> hp{};
    std::array<uint64_t,4> hp_write{};
    DdrTimeBudget(unsigned period,unsigned count,uint64_t board_rate=0):
        period_ps(period),beats(count),board_bytes_per_second(board_rate) {}
    bool board_spec() const { return board_bytes_per_second!=0; }
    uint64_t capacity_bytes_per_second() const {
        return board_spec()?board_bytes_per_second:uint64_t(beats)*800000000;
    }
    uint64_t hp_capacity_bytes_per_second() const {
        return board_spec()?byte_beat_ps/period_ps:800000000;
    }
    unsigned max_beats_per_cycle() const {
        return board_spec()?unsigned(std::min(UINT64_C(8),
            (board_bytes_per_second*period_ps+byte_beat_ps-1)/byte_beat_ps)):beats;
    }
    void advance() {
        if(board_spec()) {
            // Preserve only fractional service credit. Whole unused beats are
            // discarded each cycle; idle time cannot create a later DDR burst.
            phase+=board_bytes_per_second*period_ps;
            aggregate=phase/byte_beat_ps;phase%=byte_beat_ps;
            hp.fill(1);hp_write.fill(1);
            return;
        }
        // Refill at each10ns reference epoch, quantized onto the PL clock.
        // Unused slots do not accumulate into an artificial DDR burst.
        phase+=period_ps;
        if(phase>=beat_ps) {
            phase-=beat_ps;aggregate=uint64_t(beats)*beat_ps;
            hp.fill(beat_ps);
        }
    }
    bool available(unsigned port,bool write=false) const {
        if(board_spec()) return aggregate>=1 && (write?hp_write[port]:hp[port])>=1;
        return aggregate>=beat_ps && hp[port]>=beat_ps;
    }
    void consume(unsigned port,bool write=false) {
        if(board_spec()) {--aggregate;--(write?hp_write[port]:hp[port]);}
        else {aggregate-=beat_ps;hp[port]-=beat_ps;}
    }
    unsigned reference_cycles(unsigned cycles) const {
        return unsigned((uint64_t(cycles)*beat_ps+period_ps-1)/period_ps);
    }
};
