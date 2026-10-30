/* GPL-3.0-or-later: internal four-candidate packet and isolated test interface. */
#pragma once
#include <cstdint>
#include "next_stream.hpp"
struct CandidateQuad {uint64_t words[4];uint8_t mask;};
extern "C" void fastv2_merge4_hls(hls::stream<CandidateQuad>& packets,hls::stream<uint64_t>& tokens);
