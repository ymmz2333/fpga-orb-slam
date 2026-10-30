// Exercise the C++ DDR/ownership model using pin stubs, independently of HLS.
#define main unused_native_frame_main
#include "native_frame.cpp"
#undef main

int main() {
    try {
        Simulation sim(1,27,6073);
        // Paired HP0 masters contend, but must read the same common memory bytes.
        Bytes pattern(128);for(unsigned i=0;i<128;++i) pattern[i]=uint8_t(i*17+3);
        sim.put(0x1ff8,pattern);
        for(unsigned p: {0u,4u}) {
            sim.ports[p].read_ranges={{0x1ff8,0x2078}};
            sim.dut.m_ARADDR[p]=0x1ff8;sim.dut.m_ARLEN[p]=0;
            sim.dut.m_ARSIZE[p]=3;sim.dut.m_ARBURST[p]=1;sim.dut.m_ARID[p]=1;
            sim.dut.m_ARVALID[p]=1;sim.dut.m_RREADY[p]=0;
        }
        bool accepted[2]={};
        for(unsigned t=0;t<100 && (!accepted[0] || !accepted[1]);++t) {
            sim.tick();
            for(unsigned k=0;k<2;++k) if(sim.dut.m_ARVALID[k*4] && sim.dut.m_ARREADY[k*4]) {
                accepted[k]=true;sim.dut.m_ARVALID[k*4]=0;
            }
        }
        require(accepted[0]&&accepted[1],"Model AR queue test");
        for(unsigned t=0;t<100 && (!sim.ports[0].rvalid || !sim.ports[4].rvalid);++t) sim.tick();
        uint64_t expected=0;for(unsigned i=0;i<8;++i) expected|=uint64_t(pattern[i])<<(8*i);
        for(unsigned p: {0u,4u}) require(sim.ports[p].rvalid && sim.ports[p].rdata==expected && sim.ports[p].rlast && sim.ports[p].rid==1,"Model read payload");
        for(unsigned t=0;t<17;++t) {
            sim.tick();require(sim.ports[0].rdata==expected && sim.ports[4].rdata==expected,"Stalled R payload");
        }
        sim.dut.m_RREADY[0]=sim.dut.m_RREADY[4]=1;sim.tick();
        require(sim.idle(0)&&sim.idle(1),"Model read completion");
        // Four-byte transfer in the upper bus lanes with masked write and B delay.
        sim.ports[7].write_ranges={{0x3004,0x3008}};
        sim.dut.m_AWADDR[7]=0x3004;sim.dut.m_AWLEN[7]=0;sim.dut.m_AWSIZE[7]=2;
        sim.dut.m_AWBURST[7]=1;sim.dut.m_AWID[7]=1;sim.dut.m_AWVALID[7]=1;
        for(unsigned t=0;sim.dut.m_AWVALID[7];++t) {
            require(t<100,"Model AW timeout");sim.tick();if(sim.dut.m_AWREADY[7]) sim.dut.m_AWVALID[7]=0;
        }
        sim.dut.m_WDATA[7]=UINT64_C(0xdeadbeef01020304);sim.dut.m_WSTRB[7]=0xf0;
        sim.dut.m_WLAST[7]=1;sim.dut.m_WVALID[7]=1;sim.dut.m_BREADY[7]=0;
        for(unsigned t=0;sim.dut.m_WVALID[7];++t) {
            require(t<100,"Model W timeout");sim.tick();if(sim.dut.m_WREADY[7]) sim.dut.m_WVALID[7]=0;
        }
        require(sim.word(0x3004)==0xdeadbeef && sim.word(0x3000)==0,"Narrow write lane mask");
        // Keep the original400ns observation window at every fabric clock.
        // Forty clocks at166.667MHz would end before the maximum310ns B delay.
        for(unsigned t=0;t<sim.service_time.reference_cycles(40);++t) sim.tick();
        require(!sim.idle(1) && sim.dut.m_BVALID[7] && sim.dut.m_BID[7]==1,"Delayed B outstanding barrier");
        sim.dut.m_BREADY[7]=1;sim.tick();require(sim.idle(1),"Final B response");
        bool rejected=false;
        try { sim.boundary(0x1ff8,1,3,1,0,false); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"Cross-4KB burst accepted");
        rejected=false;
        try { sim.boundary(0x1000,0,3,1,0,false); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"Out-of-owned-range read accepted");
        require(sim.ports[0].read_bytes==8 && sim.ports[4].read_bytes==8 && sim.ports[7].write_bytes==4,"Model byte counters");
        require(sim.ports[0].activity[0]==1 && sim.ports[0].activity[2]==1 && sim.ports[0].read_highwater==1,
                "Model real outstanding/read handshake counters");
        require(sim.ports[0].activity[12]==sim.ports[0].activity[10] &&
                sim.ports[0].activity[10]>sim.ports[0].activity[15],
                "Pending-read mean must include stalled valid R, not only waiting-for-data cycles");
        require(sim.ports[7].activity[1]==1 && sim.ports[7].activity[3]==1 && sim.ports[7].activity[4]==1 &&
                sim.ports[7].activity[9]>0 && sim.ports[7].write_highwater==1,"Model delayed B counters");
        require(sim.ddr_activity[2]==2 && sim.ddr_activity[3]==1 && sim.hp_service_beats[0]==2 &&
                sim.hp_service_beats[2]==1,"Model HP/DDR effective service counters");
        // Fixed extremes establish the configured 400/600 ns minimum before
        // arbitration, independently of the pseudo-random delay distribution.
        for(unsigned delay: {40u,60u}) {
            Simulation slow(1,0,6011,delay,delay);
            slow.put(0x4000,pattern);slow.ports[0].read_ranges={{0x4000,0x4080}};
            slow.dut.m_ARADDR[0]=0x4000;slow.dut.m_ARLEN[0]=0;slow.dut.m_ARSIZE[0]=3;
            slow.dut.m_ARBURST[0]=1;slow.dut.m_ARVALID[0]=1;slow.dut.m_RREADY[0]=0;
            slow.tick();require(slow.dut.m_ARREADY[0],"Fixed delay AR acceptance");
            const auto accepted_cycle=slow.cycles;slow.dut.m_ARVALID[0]=0;
            const unsigned wait=slow.service_time.reference_cycles(delay);
            for(unsigned t=0;t<wait;++t) {slow.tick();require(!slow.ports[0].rvalid,"R before configured first-read delay");}
            for(unsigned t=0;!slow.ports[0].rvalid;++t) {require(t<3,"Quantized first R timeout");slow.tick();}
            require(slow.cycles>=accepted_cycle+wait+1 && slow.cycles<=accepted_cycle+wait+2,"Configured first R service");
            require(slow.ports[0].reads.size()==1 && slow.ports[0].read_highwater==1,"RVALID double counted outstanding");
            slow.dut.m_RREADY[0]=1;slow.tick();require(slow.idle(0),"Fixed delay response completion");
        }
        // Saturated contenders prove identical bytes/s at both accelerator clocks.
        for(unsigned period: {10000u,8000u,7000u,6667u,6000u,5000u}) for(unsigned beats: {1u,2u}) {
            DdrTimeBudget time(period,beats);unsigned served=0;
            std::array<unsigned,4> hp_count{};
            for(unsigned tick=0;tick<10000;++tick) {
                time.advance();unsigned used=0;
                for(unsigned port=0;port<4 && used<beats;++port) if(time.available(port)) {
                    time.consume(port);++served;++hp_count[port];++used;
                }
                require(served<=uint64_t(tick+1)*period*beats/10000,"Aggregate bytes/s exceeds reference rate");
            }
            require(served==uint64_t(10000)*period*beats/10000,"Normalized DDR saturation rate");
            for(auto count:hp_count) require(count<=uint64_t(10000)*period/10000,"HP bytes/s exceeds reference rate");
            for(unsigned delay: {0u,5u,40u,60u,31u}) {
                const auto actual=uint64_t(time.reference_cycles(delay))*period;
                require(actual>=delay*10000 && actual<delay*10000+period,"Response-ns clock quantization");
            }
        }
        // Board-spec budgets: mixed reads/writes share the physical DDR limit,
        // but each HP direction can transfer independently at its own clock.
        for(unsigned period: {10000u,8000u,7000u,6667u,6000u,5000u}) for(uint64_t rate: {UINT64_C(4266666664),UINT64_C(1000000000)}) {
            DdrTimeBudget time(period,4,rate);uint64_t served=0;
            std::array<uint64_t,8> channel_count{};
            for(unsigned tick=0;tick<30000;++tick) {
                time.advance();unsigned used=0;
                for(unsigned n=0;n<8;++n) {
                    const unsigned channel=(tick+n)%8,port=channel/2;const bool write=channel&1;
                    if(time.available(port,write)) {
                        time.consume(port,write);++served;++channel_count[channel];++used;
                        require(!time.available(port,write),"HP direction granted twice in a cycle");
                    }
                }
                require(used<=time.max_beats_per_cycle(),"Board DDR per-cycle budget exceeded");
                require(served<=rate*uint64_t(tick+1)*period/DdrTimeBudget::byte_beat_ps,
                        "Board shared read/write bytes/s exceeds physical capacity");
            }
            require(served==rate*UINT64_C(30000)*period/DdrTimeBudget::byte_beat_ps,"Board DDR saturation rate");
            for(auto count:channel_count) require(count<=30000,"HP direction exceeds clock-rate capacity");
            for(unsigned t=0;t<10000;++t) time.advance();
            require(time.aggregate<=time.max_beats_per_cycle(),"Idle service credit accumulated");
        }
        Simulation board(4,0,6001,0,0,UINT64_C(4266666664));
        board.put(0x6000,pattern);board.ports[0].read_ranges={{0x6000,0x6080}};
        board.ports[4].read_ranges={{0x6000,0x6080}};board.ports[4].write_ranges={{0x7000,0x7008}};
        board.ports[0].reads.push_back({0x6000,1,3,0,board.cycles});
        board.ports[4].reads.push_back({0x6000,1,3,0,board.cycles});
        board.ports[4].writes.push_back({0x7000,1,3,0,board.cycles});
        board.dut.m_WDATA[4]=UINT64_C(0x123456789abcdef0);board.dut.m_WSTRB[4]=255;
        board.dut.m_WLAST[4]=1;board.dut.m_WVALID[4]=1;
        board.tick();
        require(board.hp_read_service_beats[0]==1 && board.hp_write_service_beats[0]==1,
                "Board HP read and write did not coexist; or readers escaped shared HP limit");
        require(board.ports[0].rvalid!=board.ports[4].rvalid,"Two readers granted on one HP in one cycle");
        require(board.dut.m_WREADY[4] && board.word(0x7000)==0x9abcdef0,"Board parallel write payload");
        board.dut.m_WVALID[4]=0;board.tick();
        require(board.ports[0].rvalid && board.ports[4].rvalid,"Second HP reader did not progress");
        const auto board_r0=board.ports[0].rdata,board_r4=board.ports[4].rdata;
        for(unsigned t=0;t<17;++t) {
            board.tick();require(board.ports[0].rdata==board_r0 && board.ports[4].rdata==board_r4,
                                 "Board R payload changed under backpressure");
        }
        board.dut.m_RREADY[0]=board.dut.m_RREADY[4]=board.dut.m_BREADY[4]=1;
        for(unsigned t=0;!board.idle(0) || !board.idle(1);++t) {
            require(t<100,"Board final-response drain timeout");board.tick();
        }
        std::cout<<"NATIVE_DDR_MODEL_PASS LEGACY_AND_BOARD_SPEC"<<std::endl;return 0;
    } catch(const std::exception& error) { std::cerr<<error.what()<<std::endl;return 1; }
}
