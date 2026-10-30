#pragma once

#ifndef ORB60_SLICE_COMPACT_MODE
#define ORB60_SLICE_COMPACT_MODE 0
#endif
#if ORB60_SLICE_COMPACT_MODE < 0 || ORB60_SLICE_COMPACT_MODE > 3
#error Unsupported Slice compact mode
#endif

// Eight independently owned recurrences. No score mux or update enable spans
// all 204 cells; raster order is retained within each bank, including ties.
constexpr int kScoreBanks = 8;
constexpr int kBankCells = (kGridCells + kScoreBanks - 1) / kScoreBanks;

void route_candidate_banks(hls::stream<uint64_t>& input,
    hls::stream<uint64_t> banks[kScoreBanks], hls::stream<uint32_t>& count,
    int cell_count) {
#pragma HLS INLINE off
#ifndef __SYNTHESIS__
    Point previous = {0,0,0,0}; bool have_previous = false;
#endif
RouteCandidateBanks:
    for (;;) {
#pragma HLS PIPELINE II=1
        const uint64_t token = input.read();
        if (token >> 63) {
            for (int bank=0; bank<kScoreBanks; ++bank) {
#pragma HLS UNROLL
                banks[bank].write(token);
            }
            count.write(uint32_t(token)); break;
        }
#ifndef __SYNTHESIS__
        const Point point=unpack_point(token & ((UINT64_C(1)<<41)-1));
        assert(int((token>>41)&255u)<cell_count && point.score>0);
        assert(!have_previous || !raster_before(point,previous));
        previous=point; have_previous=true;
#endif
        // Constant stream indices keep all stream accesses statically owned.
        switch ((token>>41)&7u) {
        case 0: banks[0].write(token); break;
        case 1: banks[1].write(token); break;
        case 2: banks[2].write(token); break;
        case 3: banks[3].write(token); break;
        case 4: banks[4].write(token); break;
        case 5: banks[5].write(token); break;
        case 6: banks[6].write(token); break;
        default: banks[7].write(token); break;
        }
    }
}

template<int Bank> void reduce_score_bank(hls::stream<uint64_t>& input,
    hls::stream<uint64_t>& winners) {
#pragma HLS INLINE off
    uint8_t scores[kBankCells];
    PackedPoint points[kBankCells];
#pragma HLS ARRAY_PARTITION variable=scores complete
    // 26x41 bits per bank is too small to justify eight BRAM allocations.
#if ORB60_SLICE_COMPACT_MODE == 3
#pragma HLS BIND_STORAGE variable=points type=ram_s2p impl=bram
#else
#pragma HLS BIND_STORAGE variable=points type=ram_s2p impl=lutram
#endif
InitializeBankScores:
    for (int i=0; i<kBankCells; ++i) {
#pragma HLS PIPELINE II=1
        scores[i]=0;
    }
ReduceCandidateTokens:
    for (;;) {
#pragma HLS PIPELINE II=1
        const uint64_t token=input.read();
        if (token>>63) break;
        const int index=int((token>>44)&31u);
        const uint8_t score=uint8_t((token>>22)&255u);
#ifndef __SYNTHESIS__
        assert(((token>>41)&7u)==Bank && index<kBankCells);
#endif
        // Scores are registers; the true same-cell recurrence is preserved.
        if (score>scores[index]) {
            scores[index]=score;
            points[index]=token & ((UINT64_C(1)<<41)-1);
        }
    }
EmitBankWinners:
    for (int i=0; i<kBankCells; ++i) {
#pragma HLS PIPELINE II=1
        winners.write(scores[i] ? uint64_t(points[i]) : UINT64_C(0));
    }
}

uint64_t read_bank_winner(hls::stream<uint64_t> winners[kScoreBanks], int bank) {
#pragma HLS INLINE
    switch (bank) {
    case 0: return winners[0].read();
    case 1: return winners[1].read();
    case 2: return winners[2].read();
    case 3: return winners[3].read();
    case 4: return winners[4].read();
    case 5: return winners[5].read();
    case 6: return winners[6].read();
    default: return winners[7].read();
    }
}

void collect_bank_winners(hls::stream<uint64_t> winners[kScoreBanks],
    PackedPoint points[kGridCells]) {
#pragma HLS INLINE off
CollectBankWinners:
    for (int cell=0; cell<kScoreBanks*kBankCells; ++cell) {
#pragma HLS PIPELINE II=1
        const uint64_t point=read_bank_winner(winners,cell&7);
        // Drain the four padded bank entries too, including capacity errors.
        if (cell<kGridCells) points[cell]=point;
    }
}

void reduce_banked_grid(hls::stream<uint64_t>& input,
    PackedPoint points[kGridCells], hls::stream<uint32_t>& count, int cell_count) {
#pragma HLS INLINE off
    hls::stream<uint64_t> banks[kScoreBanks], winners[kScoreBanks];
#pragma HLS STREAM variable=banks depth=8
#pragma HLS STREAM variable=winners depth=2
#pragma HLS DATAFLOW
    route_candidate_banks(input,banks,count,cell_count);
    reduce_score_bank<0>(banks[0],winners[0]);
    reduce_score_bank<1>(banks[1],winners[1]);
    reduce_score_bank<2>(banks[2],winners[2]);
    reduce_score_bank<3>(banks[3],winners[3]);
    reduce_score_bank<4>(banks[4],winners[4]);
    reduce_score_bank<5>(banks[5],winners[5]);
    reduce_score_bank<6>(banks[6],winners[6]);
    reduce_score_bank<7>(banks[7],winners[7]);
    collect_bank_winners(winners,points);
#ifndef __SYNTHESIS__
    for (int bank=0; bank<kScoreBanks; ++bank)
        assert(banks[bank].empty() && winners[bank].empty());
#endif
}

#if ORB60_SLICE_COMPACT_MODE
constexpr int kTournamentCoordinateBits=ORB60_SLICE_COMPACT_MODE==1?11:10;
constexpr int kTournamentKeyBits=2*kTournamentCoordinateBits+16;
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<kTournamentKeyBits> TournamentPoint;
#else
typedef uint64_t TournamentPoint;
#endif
TournamentPoint compact_tournament_key(uint64_t point,int cell) {
#pragma HLS INLINE
    const unsigned score=unsigned((point>>22)&255u);
    if(!score) return 0;
    const unsigned x=unsigned(point&2047u),y=unsigned((point>>11)&2047u);
    constexpr unsigned mask=(1u<<kTournamentCoordinateBits)-1;
#ifndef __SYNTHESIS__
    assert(x<=mask && y<=mask && cell>=0 && cell<256);
#endif
    // A larger unsigned key means stronger score, then smaller y/x/cell.
    // Tile and the original payload are preserved separately in best_low.
    return TournamentPoint((uint64_t(score)<<(2*kTournamentCoordinateBits+8))|
        (uint64_t(mask-y)<<(kTournamentCoordinateBits+8))|
        (uint64_t(mask-x)<<8)|uint64_t(255-cell));
}
TournamentPoint tournament_winner(TournamentPoint left,TournamentPoint right) {
#pragma HLS INLINE
    // Parallel9-bit comparisons and balanced lexicographic combination avoid
    // the measured wide carry chain between a BRAM read and BRAM write.
    constexpr int chunk_bits=(kTournamentKeyBits+3)/4;
    constexpr unsigned chunk_mask=(1u<<chunk_bits)-1;
    unsigned a[4],b[4];bool equal[4],greater[4];
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=equal complete
#pragma HLS ARRAY_PARTITION variable=greater complete
CompareTournamentChunks:
    for(int chunk=0;chunk<4;++chunk) {
#pragma HLS UNROLL
        a[chunk]=unsigned(uint64_t(left)>>(chunk*chunk_bits))&chunk_mask;
        b[chunk]=unsigned(uint64_t(right)>>(chunk*chunk_bits))&chunk_mask;
        equal[chunk]=a[chunk]==b[chunk];greater[chunk]=a[chunk]>b[chunk];
    }
    const bool lower=greater[1] || (equal[1] && (greater[0] || equal[0]));
    const bool upper=greater[3] || (equal[3] && greater[2]);
    const bool upper_equal=equal[3] && equal[2];
    return upper || (upper_equal && lower)?left:right;
}
#else
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
typedef ap_uint<49> TournamentPoint;
#else
typedef uint64_t TournamentPoint;
#endif

TournamentPoint tournament_winner(TournamentPoint left,TournamentPoint right) {
#pragma HLS INLINE
    const uint64_t mask=(UINT64_C(1)<<41)-1;
    const Point a=unpack_point(uint64_t(left)&mask),b=unpack_point(uint64_t(right)&mask);
    if (!a.score) return right;
    if (!b.score) return left;
    if (stronger(b,a)) return right;
    if (stronger(a,b)) return left;
    // The old full-cell scan retains the lower cell for an exact tie.
    return (uint64_t(left)>>41)<=(uint64_t(right)>>41) ? left : right;
}
#endif
