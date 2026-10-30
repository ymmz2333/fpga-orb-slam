// Authored computer testbench. All image/descriptor arithmetic executes in HLS RTL.
#include "Vorb60_frame_top.h"
#include "verilated.h"
#include "frame_registers.hpp"
#include "ddr_time.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs=std::filesystem;
// This Windows runtime requires the legacy time callback at link time.
// Supply it explicitly; timeprecision is1ps, clock comes from accepted HLS.
uint64_t native_time_ps=0;
double sc_time_stamp() { return static_cast<double>(native_time_ps); }
fs::path diagnostic_directory;
void require(bool test,const std::string& message) { if(!test) throw std::runtime_error(message); }
using Bytes=std::vector<uint8_t>;
Bytes load(const fs::path& path) {
    std::ifstream file(path,std::ios::binary);
    require(bool(file),"Missing input: "+path.string());
    return Bytes(std::istreambuf_iterator<char>(file),{});
}
constexpr unsigned WIDTH[8]={960,800,667,556,463,386,322,268};
constexpr unsigned HEIGHT[8]={720,600,500,417,347,289,241,201};
constexpr unsigned BUDGET[8]={217,181,151,126,105,87,73,60};
constexpr unsigned IMAGE_BYTES=691200, FRAME_BYTES=64000;
constexpr unsigned RAW[3]={0x100ff8,0x1b0ff8,0x260ff8};
constexpr unsigned BLUR[2]={0x310ff8,0x3c0ff8};
constexpr unsigned FEATURES=0x530ff8;
unsigned point_addr(unsigned level) { return 0x470ff8+0x4000*level; }
unsigned summary_addr(unsigned level) { return 0x500fc0+0x80*level; }
unsigned layer_stats(unsigned level) { return 0x510fc0+0x80*level; }
unsigned desc_stats(unsigned level) { return 0x520fc0+0x80*level; }
unsigned rounded(unsigned n) { return (n+7)/8*8; }
unsigned pixels(unsigned level) { return WIDTH[level]*HEIGHT[level]; }

struct Range { unsigned first,last; };
bool inside(unsigned address,unsigned size,const std::vector<Range>& ranges) {
    for(auto r:ranges) if(address>=r.first && uint64_t(address)+size<=r.last) return true;
    return false;
}
struct Burst { unsigned address,left,size,id; uint64_t eligible; };
struct Response { unsigned id; uint64_t eligible; };
constexpr unsigned AXI_METRIC_COUNT=16;
constexpr const char* AXI_METRIC_NAMES[AXI_METRIC_COUNT]={
    "accepted_ar","accepted_aw","accepted_r","accepted_w","accepted_b",
    "ar_blocked_cycles","aw_blocked_cycles","r_blocked_cycles","w_blocked_cycles","b_blocked_cycles",
    "read_pending_cycles","write_pending_cycles","read_outstanding_cycle_sum","write_outstanding_cycle_sum","idle_cycles","read_wait_for_data_cycles"};
struct Port {
    std::deque<Burst> reads,writes;
    std::deque<Response> responses;
    bool rvalid=false,rlast=false;
    uint64_t rdata=0;
    unsigned rid=0;
    uint64_t read_bytes=0,write_bytes=0,read_bursts=0,write_bursts=0,contention=0;
    std::vector<Range> read_ranges,write_ranges;
    std::array<uint64_t,6> ar_hold{},aw_hold{},w_hold{};
    bool ar_stalled=false,aw_stalled=false,w_stalled=false;
    std::array<uint64_t,AXI_METRIC_COUNT> activity{};
    unsigned read_highwater=0,write_highwater=0;
};
struct LiteSample {
    bool aw,w,b,ar,r;
    unsigned data;
};

// Eight AXI masters, one byte-addressed DDR, four paired HP arbitration groups.
// A DDR beat is serviced once when its R payload is prepared or W is accepted.
// RVALID remains stable during downstream backpressure. Outstanding requests
// are ordered per master; queues deliberately allow the HLS outstanding depth.
class Simulation {
public:
    Vorb60_frame_top dut;
    Bytes memory=Bytes(0x800000),shadow=Bytes(0x800000);
    std::array<Port,8> ports;
    std::array<LiteSample,2> lite{};
    std::array<bool,2> active{},done{};
    std::array<uint64_t,2> started{},finished{};
    uint64_t cycles=0,overlap=0;
#ifdef ORB60_NATIVE_PROFILE
    std::array<uint64_t,PROFILE_COUNT> profile_cycles{};
    std::array<int,PROFILE_FIFO_COUNT> fifo_level{};
    std::array<unsigned,PROFILE_FIFO_COUNT> fifo_highwater{};
#endif
    unsigned beat_budget,stall_percent,state,round_robin=0;
    unsigned read_delay_min,read_delay_max;
    DdrTimeBudget service_time;
    // Service counts read payload preparation and accepted W beats. R channel
    // handshakes are separately counted and may lag payload preparation.
    std::array<uint64_t,4> ddr_activity{}; // used cycles, idle cycles, R beats, W beats
    std::array<uint64_t,4> hp_service_beats{};
    std::array<uint64_t,4> hp_read_service_beats{},hp_write_service_beats{};
    static constexpr unsigned hp[8]={0,3,1,2,0,1,3,2};

    Simulation(unsigned beats,unsigned stalls,unsigned seed,unsigned read_min=0,unsigned read_max=5,uint64_t board_rate=0):
        beat_budget(beats),stall_percent(stalls),state(seed),read_delay_min(read_min),read_delay_max(read_max),service_time(CLOCK_PERIOD_PS,beats,board_rate) {
        require(beats>=1 && beats<=4 && stalls<=90,"Invalid memory model configuration");
        require(board_rate<=UINT64_C(8000000000),"DDR board capacity exceeds supported model range");
        beat_budget=service_time.max_beats_per_cycle();
        require(read_min<=read_max && read_max<=10000,"Invalid initial read delay");
        dut.clk=0;dut.rst_n=0;
        for(unsigned c=0;c<2;++c) {
            dut.c_AWVALID[c]=dut.c_WVALID[c]=dut.c_ARVALID[c]=0;
            dut.c_BREADY[c]=dut.c_RREADY[c]=1;dut.c_WSTRB[c]=15;
        }
        for(unsigned i=0;i<8;++i) {
            dut.m_RVALID[i]=dut.m_BVALID[i]=dut.m_WREADY[i]=0;
            dut.m_ARREADY[i]=dut.m_AWREADY[i]=0;
            dut.m_RDATA[i]=dut.m_RID[i]=dut.m_RLAST[i]=dut.m_RRESP[i]=0;
            dut.m_BID[i]=dut.m_BRESP[i]=0;
        }
        for(unsigned i=0;i<10;++i) {
            native_time_ps+=CLOCK_PERIOD_PS/2;dut.clk=0;dut.eval();
            native_time_ps+=CLOCK_PERIOD_PS-CLOCK_PERIOD_PS/2;dut.clk=1;dut.eval();
        }
        dut.clk=0;dut.rst_n=1;dut.eval();
        for(unsigned i=0;i<10;++i) tick();
    }
    unsigned random() { state^=state<<13;state^=state>>17;state^=state<<5;return state; }
    bool allow() { return random()%100>=stall_percent; }
    bool idle(unsigned core) const {
        for(unsigned i=core*4;i<core*4+4;++i) {
            const auto& p=ports[i];
            if(!p.reads.empty() || p.rvalid || !p.writes.empty() || !p.responses.empty()) return false;
        }
        return true;
    }
    void boundary(unsigned a,unsigned length,unsigned size,unsigned burst,unsigned port,bool write) {
        require(size<=3 && burst==1,"Unsupported AXI size/burst");
        unsigned amount=(length+1)*(1u<<size);
        require(a%(1u<<size)==0,"Unaligned AXI request");
        require((a&4095)+amount<=4096,"AXI request crosses 4 KB");
        require(uint64_t(a)+amount<=memory.size(),"AXI outside modeled DDR");
        require(inside(a,amount,write?ports[port].write_ranges:ports[port].read_ranges),
                "AXI ownership violation on port "+std::to_string(port)+" address "+std::to_string(a));
    }
    void hold(bool valid,bool ready,std::array<uint64_t,6> payload,
              bool& stalled,std::array<uint64_t,6>& previous,const char* name,unsigned port) {
        require(!stalled || (valid && payload==previous),std::string(name)+" changed under stall on "+std::to_string(port));
        stalled=valid && !ready;previous=payload;
    }
    void tick() {
        require(cycles<60000000,"Frame simulation watchdog");
        native_time_ps+=CLOCK_PERIOD_PS/2;
        dut.clk=0;
        for(unsigned i=0;i<8;++i) {
            auto& p=ports[i];
            dut.m_ARREADY[i]=p.reads.size()<8 && allow();
            dut.m_AWREADY[i]=p.writes.size()+p.responses.size()<8 && allow();
            dut.m_WREADY[i]=0;
            dut.m_BVALID[i]=!p.responses.empty() && p.responses.front().eligible<=cycles;
            dut.m_BID[i]=p.responses.empty()?0:p.responses.front().id;
            dut.m_RVALID[i]=p.rvalid;dut.m_RDATA[i]=p.rdata;
            dut.m_RLAST[i]=p.rlast;dut.m_RID[i]=p.rid;
        }
        dut.eval();
        std::array<bool,4> used_hp{};
        std::array<bool,4> used_hp_write{};
        std::array<bool,16> eligible{},granted{};
        for(unsigned i=0;i<8;++i) {
            auto& p=ports[i];
            eligible[2*i]=!p.rvalid && !p.reads.empty() && p.reads.front().eligible<=cycles;
            eligible[2*i+1]=!p.writes.empty() && bool(dut.m_WVALID[i]);
        }
        unsigned used=0,last=round_robin;
        // Preserve the original100MHz arbitration and PRNG sequence exactly.
        const bool timed=service_time.board_spec() || CLOCK_PERIOD_PS!=10000;
        if(timed) service_time.advance();
        for(unsigned n=0;n<16 && used<beat_budget;++n) {
            unsigned k=(round_robin+n)%16,i=k/2;
            const bool writing=k&1;
            if(timed && !service_time.available(hp[i],writing)) continue;
            auto& hp_used=service_time.board_spec() && writing?used_hp_write:used_hp;
            if(!eligible[k] || hp_used[hp[i]] || !allow()) continue;
            if(timed) service_time.consume(hp[i],writing);
            hp_used[hp[i]]=true;granted[k]=true;++used;last=(k+1)%16;
            auto& p=ports[i];
            if(k&1) dut.m_WREADY[i]=1;
            else {
                const auto& b=p.reads.front();
                p.rvalid=true;p.rlast=b.left==1;p.rid=b.id;p.rdata=0;
                unsigned aligned=b.address&~7u;
                for(unsigned byte=0;byte<8;++byte) p.rdata|=uint64_t(memory.at(aligned+byte))<<(byte*8);
                dut.m_RVALID[i]=1;dut.m_RDATA[i]=p.rdata;dut.m_RLAST[i]=p.rlast;dut.m_RID[i]=p.rid;
            }
        }
        round_robin=last;
        ++ddr_activity[used?0:1];
        for(unsigned k=0;k<16;++k) if(granted[k]) {
            ++ddr_activity[(k&1)?3:2];++hp_service_beats[hp[k/2]];
            ++((k&1)?hp_write_service_beats:hp_read_service_beats)[hp[k/2]];
        }
        for(unsigned k=0;k<16;++k) if(eligible[k] && !granted[k]) ++ports[k/2].contention;
        dut.eval();
        struct Sample { bool ar,aw,w,r,b; unsigned ra,rl,rs,rb,ri,wa,wl,ws,wb,wi,strb; bool last; uint64_t data; };
        std::array<Sample,8> edge{};
        for(unsigned i=0;i<8;++i) {
            auto& p=ports[i];
            hold(dut.m_ARVALID[i],dut.m_ARREADY[i],{dut.m_ARADDR[i],dut.m_ARLEN[i],dut.m_ARSIZE[i],dut.m_ARBURST[i],dut.m_ARID[i],0},p.ar_stalled,p.ar_hold,"AR",i);
            hold(dut.m_AWVALID[i],dut.m_AWREADY[i],{dut.m_AWADDR[i],dut.m_AWLEN[i],dut.m_AWSIZE[i],dut.m_AWBURST[i],dut.m_AWID[i],0},p.aw_stalled,p.aw_hold,"AW",i);
            hold(dut.m_WVALID[i],dut.m_WREADY[i],{dut.m_WDATA[i],dut.m_WSTRB[i],dut.m_WLAST[i],0,0,0},p.w_stalled,p.w_hold,"W",i);
            edge[i]={bool(dut.m_ARVALID[i]&&dut.m_ARREADY[i]),bool(dut.m_AWVALID[i]&&dut.m_AWREADY[i]),
                bool(dut.m_WVALID[i]&&dut.m_WREADY[i]),bool(dut.m_RVALID[i]&&dut.m_RREADY[i]),bool(dut.m_BVALID[i]&&dut.m_BREADY[i]),
                dut.m_ARADDR[i],dut.m_ARLEN[i],dut.m_ARSIZE[i],dut.m_ARBURST[i],dut.m_ARID[i],
                dut.m_AWADDR[i],dut.m_AWLEN[i],dut.m_AWSIZE[i],dut.m_AWBURST[i],dut.m_AWID[i],
                dut.m_WSTRB[i],bool(dut.m_WLAST[i]),dut.m_WDATA[i]};
            const auto& s=edge[i];
            const uint64_t counts[AXI_METRIC_COUNT]={uint64_t(s.ar),uint64_t(s.aw),uint64_t(s.r),uint64_t(s.w),uint64_t(s.b),
                uint64_t(dut.m_ARVALID[i]&&!dut.m_ARREADY[i]),uint64_t(dut.m_AWVALID[i]&&!dut.m_AWREADY[i]),
                uint64_t(dut.m_RVALID[i]&&!dut.m_RREADY[i]),uint64_t(dut.m_WVALID[i]&&!dut.m_WREADY[i]),
                uint64_t(dut.m_BVALID[i]&&!dut.m_BREADY[i]),uint64_t(!p.reads.empty()),
                uint64_t(!p.writes.empty()||!p.responses.empty()),p.reads.size(),p.writes.size()+p.responses.size(),
                uint64_t(p.reads.empty()&&!p.rvalid&&p.writes.empty()&&p.responses.empty()&&
                         !dut.m_ARVALID[i]&&!dut.m_AWVALID[i]&&!dut.m_WVALID[i]&&!dut.m_RVALID[i]&&!dut.m_BVALID[i]),
                uint64_t(!p.reads.empty()&&!dut.m_RVALID[i])};
            for(unsigned m=0;m<AXI_METRIC_COUNT;++m) p.activity[m]+=counts[m];
        }
        for(unsigned c=0;c<2;++c) lite[c]={bool(dut.c_AWVALID[c]&&dut.c_AWREADY[c]),bool(dut.c_WVALID[c]&&dut.c_WREADY[c]),
            bool(dut.c_BVALID[c]&&dut.c_BREADY[c]),bool(dut.c_ARVALID[c]&&dut.c_ARREADY[c]),
            bool(dut.c_RVALID[c]&&dut.c_RREADY[c]),dut.c_RDATA[c]};
#ifdef ORB60_NATIVE_PROFILE
        // Sample real pre-edge handshakes. Busy includes blocked execution;
        // individual FIFO probes distinguish read/write backpressure.
        for(unsigned p=0;p<PROFILE_COUNT;++p)
            if(active[PROFILE_CORE[p]] && !done[PROFILE_CORE[p]] && dut.profile_bits[p]) ++profile_cycles[p];
        for(unsigned f=0;f<PROFILE_FIFO_COUNT;++f) {
            const auto& spec=PROFILE_FIFOS[f];
            fifo_level[f]+=int(dut.profile_bits[spec.push])-int(dut.profile_bits[spec.pop]);
            require(fifo_level[f]>=0 && unsigned(fifo_level[f])<=spec.depth,"Profile FIFO occupancy violation");
            fifo_highwater[f]=std::max(fifo_highwater[f],unsigned(fifo_level[f]));
        }
#endif
        native_time_ps+=CLOCK_PERIOD_PS-CLOCK_PERIOD_PS/2;dut.clk=1;dut.eval();++cycles;
        if(active[0] && !done[0] && active[1] && !done[1]) ++overlap;
        for(unsigned i=0;i<8;++i) {
            auto& p=ports[i];const auto& s=edge[i];
            if(s.b) { require(!p.responses.empty(),"B without outstanding write");p.responses.pop_front(); }
            if(s.r) {
                require(p.rvalid && !p.reads.empty(),"R without request");
                auto& b=p.reads.front();p.read_bytes+=1u<<b.size;b.address+=1u<<b.size;
                require(p.rlast==(b.left==1),"RLAST mismatch");
                if(--b.left==0) p.reads.pop_front();
                p.rvalid=false;
            }
            if(s.w) {
                require(!p.writes.empty(),"W without accepted AW");auto& b=p.writes.front();
                require(s.last==(b.left==1),"WLAST mismatch");
                unsigned aligned=b.address&~7u;
                unsigned lane_mask=((1u<<(1u<<b.size))-1)<<(b.address&7);
                require((s.strb&~lane_mask)==0,"WSTRB outside transfer lanes");
                for(unsigned byte=0;byte<8;++byte) if(s.strb&(1u<<byte)) {
                    require(inside(aligned+byte,1,p.write_ranges),"Write byte outside ownership");
                    memory.at(aligned+byte)=uint8_t(s.data>>(8*byte));++p.write_bytes;
                }
                b.address+=1u<<b.size;
                if(--b.left==0) {
                    p.responses.push_back({b.id,cycles+service_time.reference_cycles(2+random()%30)});p.writes.pop_front();
                }
            }
            if(s.ar) {
                boundary(s.ra,s.rl,s.rs,s.rb,i,false);
                p.reads.push_back({s.ra,s.rl+1,s.rs,s.ri,
                    cycles+service_time.reference_cycles(read_delay_min+random()%(read_delay_max-read_delay_min+1))});++p.read_bursts;
            }
            if(s.aw) {
                boundary(s.wa,s.wl,s.ws,s.wb,i,true);
                p.writes.push_back({s.wa,s.wl+1,s.ws,s.wi,cycles});++p.write_bursts;
            }
            p.read_highwater=std::max(p.read_highwater,unsigned(p.reads.size()));
            p.write_highwater=std::max(p.write_highwater,unsigned(p.writes.size()+p.responses.size()));
            require(p.reads.size()<=8 && p.writes.size()+p.responses.size()<=8,"DDR outstanding capacity exceeded");
        }
        for(unsigned c=0;c<2;++c) if(active[c] && !done[c] && dut.done[c]) {
            require(idle(c),"Actual ap_done precedes last AXI response on core "+std::to_string(c));
            done[c]=true;finished[c]=cycles;
        }
    }
    void write_control(unsigned c,unsigned address,unsigned value) {
        dut.c_AWADDR[c]=address;dut.c_WDATA[c]=value;dut.c_AWVALID[c]=dut.c_WVALID[c]=1;
        bool aw=false,w=false,b=false;uint64_t limit=cycles+10000;
        while(!b) {
            require(cycles<limit,"AXI-Lite write timeout");tick();
            if(lite[c].aw) { aw=true;dut.c_AWVALID[c]=0; }
            if(lite[c].w) { w=true;dut.c_WVALID[c]=0; }
            if(lite[c].b) { require(aw&&w,"Early control B");b=true; }
        }
    }
    unsigned read_control(unsigned c,unsigned address) {
        dut.c_ARADDR[c]=address;dut.c_ARVALID[c]=1;bool ar=false;uint64_t limit=cycles+10000;
        for(;;) {
            require(cycles<limit,"AXI-Lite read timeout");tick();
            if(lite[c].ar) { ar=true;dut.c_ARVALID[c]=0; }
            if(lite[c].r) { require(ar,"Early control R");return lite[c].data; }
        }
    }
    void set_permissions(unsigned core,std::array<std::vector<Range>,4> reads,
                         std::array<std::vector<Range>,4> writes) {
        require(idle(core),"Changing ownership with outstanding AXI traffic");
        for(unsigned i=0;i<4;++i) {
            // Other core's live readers/writers may never alias these writes/reads.
            if(active[1-core] && !done[1-core]) for(unsigned j=(1-core)*4;j<(1-core)*4+4;++j) {
                auto conflict=[](const std::vector<Range>& a,const std::vector<Range>& b) {
                    for(auto x:a) for(auto y:b) require(x.last<=y.first || y.last<=x.first,"Buffer ownership collision");
                };
                conflict(writes[i],ports[j].read_ranges);conflict(writes[i],ports[j].write_ranges);
                conflict(reads[i],ports[j].write_ranges);
            }
            ports[core*4+i].read_ranges=reads[i];ports[core*4+i].write_ranges=writes[i];
        }
    }
    void put(unsigned address,const Bytes& value) {
        require(uint64_t(address)+value.size()<=memory.size(),"Host memory overflow");
        for(unsigned core=0;core<2;++core) if(active[core] && !done[core]) {
            for(unsigned i=core*4;i<core*4+4;++i) {
                for(auto range:ports[i].read_ranges) require(address+value.size()<=range.first || range.last<=address,"Host overwrites live reader");
                for(auto range:ports[i].write_ranges) require(address+value.size()<=range.first || range.last<=address,"Host overwrites live writer");
            }
        }
        std::copy(value.begin(),value.end(),memory.begin()+address);
        std::copy(value.begin(),value.end(),shadow.begin()+address);
    }
    void poison(unsigned address,unsigned count) {
        static const uint8_t pattern[8]={0xf0,0x0f,0x5a,0x6a,0xef,0xbe,0xad,0xde};
        Bytes b(count);for(unsigned i=0;i<count;++i) b[i]=pattern[i%8];put(address,b);
    }
    void exact(unsigned address,const Bytes& expected,const std::string& label) {
        for(unsigned i=0;i<expected.size();++i) if(memory.at(address+i)!=expected[i]) {
            if(!diagnostic_directory.empty()) {
                std::ofstream actual(diagnostic_directory/"diagnostic_actual.bin",std::ios::binary);
                actual.write(reinterpret_cast<const char*>(memory.data()+address),expected.size());
                std::ofstream reference(diagnostic_directory/"diagnostic_expected.bin",std::ios::binary);
                reference.write(reinterpret_cast<const char*>(expected.data()),expected.size());
            }
            throw std::runtime_error(label+" byte "+std::to_string(i)+" actual="+std::to_string(memory.at(address+i))+
                " expected="+std::to_string(expected[i])+" at cycle="+std::to_string(cycles));
        }
        std::copy(expected.begin(),expected.end(),shadow.begin()+address);
    }
    uint32_t word(unsigned address) const {
        return uint32_t(memory.at(address)) | uint32_t(memory.at(address+1))<<8 |
               uint32_t(memory.at(address+2))<<16 | uint32_t(memory.at(address+3))<<24;
    }
    std::array<uint32_t,16> stats(unsigned address) {
        std::array<uint32_t,16> result{};for(unsigned i=0;i<16;++i) result[i]=word(address+4*i);return result;
    }
    void accept_stats(unsigned address) {
        std::copy(memory.begin()+address,memory.begin()+address+64,shadow.begin()+address);
    }
    std::array<uint64_t,8> counts() const {
        std::array<uint64_t,8> r{};for(unsigned i=0;i<8;++i) r[i]=ports[i].read_bytes+ports[i].write_bytes;return r;
    }
};

struct LayerResult { uint64_t image_cycles=0,descriptor_cycles=0,image_axi_bytes=0,descriptor_axi_bytes=0; unsigned count=0,offset=0; };
struct PortResult {
    std::array<uint64_t,AXI_METRIC_COUNT> activity{};
    uint64_t read_bytes=0,write_bytes=0;
    unsigned read_highwater=0,write_highwater=0;
};
struct FrameResult {
    unsigned frame=0,selected=0;uint64_t cycles=0,overlap_cycles=0,read_bytes=0,write_bytes=0,contention=0;
    std::array<LayerResult,8> layers{};
    std::array<PortResult,8> axi{};
    std::array<uint64_t,4> ddr_activity{},hp_service_beats{};
    std::array<uint64_t,4> hp_read_service_beats{},hp_write_service_beats{};
#ifdef ORB60_NATIVE_PROFILE
    std::array<uint64_t,PROFILE_COUNT> profile_cycles{};
    std::array<unsigned,PROFILE_FIFO_COUNT> fifo_highwater{};
#endif
};

FrameResult frame(Simulation& sim,unsigned number,const fs::path& images,const fs::path& descriptors,bool first_layer_only=false) {
    require(sim.idle(0)&&sim.idle(1),"Frame starts with pending responses");
    sim.active={false,false};sim.done={false,false};
    sim.poison(0,unsigned(sim.memory.size()));
    for(unsigned l=0;l<8;++l) sim.put(point_addr(l),Bytes(16000,0xa5));
    sim.put(FEATURES,Bytes(FRAME_BYTES,0xc3));
    sim.put(RAW[0],load(images/("f"+std::to_string(number)+"_l0_input.bin")));
    auto old=sim.counts();uint64_t old_overlap=sim.overlap,begin=sim.cycles;
    std::array<PortResult,8> old_axi{};
    for(unsigned p=0;p<8;++p) {
        old_axi[p].activity=sim.ports[p].activity;
        old_axi[p].read_bytes=sim.ports[p].read_bytes;old_axi[p].write_bytes=sim.ports[p].write_bytes;
        sim.ports[p].read_highwater=sim.ports[p].write_highwater=0;
    }
    const auto old_ddr=sim.ddr_activity,old_hp=sim.hp_service_beats;
    const auto old_hp_read=sim.hp_read_service_beats,old_hp_write=sim.hp_write_service_beats;
#ifdef ORB60_NATIVE_PROFILE
    const auto old_profile=sim.profile_cycles;
    sim.fifo_highwater.fill(0);
#endif
    FrameResult result;result.frame=number;
    std::array<uint64_t,8> image_counts{},descriptor_counts{};
    auto prefix=[&](unsigned l) { return images/("f"+std::to_string(number)+"_l"+std::to_string(l)); };
    auto file=[&](unsigned l,const std::string& suffix) { return fs::path(prefix(l).string()+"_"+suffix+".bin"); };
    auto launch_image=[&](unsigned l) {
        require(!sim.active[0] || sim.done[0],"Image core reentry");
        unsigned raw=RAW[l%3],blur=BLUR[l%2],next=RAW[(l+1)%3];
        if(l) {
            Bytes expected=load(file(l,"input"));expected.resize(pixels(l));
            sim.exact(raw,expected,"Actual resize feeds next raw");
        }
        sim.poison(blur,IMAGE_BYTES);
        if(l<7) sim.poison(next,IMAGE_BYTES);
        std::array<std::vector<Range>,4> rd{},wr{};
        rd[0]={{raw,raw+rounded(pixels(l))}};
        wr[1]={{point_addr(l),point_addr(l)+16000},{summary_addr(l),summary_addr(l)+64},{layer_stats(l),layer_stats(l)+64}};
        wr[2]={{blur,blur+rounded(pixels(l))}};
        if(l<7) wr[3]={{next,next+rounded(pixels(l+1))}};
        sim.set_permissions(0,rd,wr);
        for(auto pair:std::vector<std::pair<unsigned,unsigned>>{
            {reg0::IMAGE_R,raw},{reg0::BLURRED,blur},{reg0::RESIZED,next},{reg0::SELECTED,point_addr(l)},
            {reg0::RESULT,summary_addr(l)},{reg0::STATS,layer_stats(l)},{reg0::LEVEL,l},{reg0::BUDGET,BUDGET[l]},
            {reg0::HIGH_THRESHOLD,20},{reg0::LOW_THRESHOLD,7},{reg0::DUAL_THRESHOLD,1},{reg0::SELECTED_CAPACITY,1000}})
            sim.write_control(0,pair.first,pair.second);
        image_counts=sim.counts();sim.active[0]=true;sim.done[0]=false;sim.started[0]=sim.cycles;
        sim.write_control(0,0,1);
    };
    auto finish_image=[&](unsigned l) {
        // Direct ap_done is visible before the AXI-Lite return latch updates.
        // Keep the direct response barrier, then cross the next clock before MMIO.
        sim.tick();
        require(sim.done[0] && sim.read_control(0,reg0::AP_RETURN)==0,"Image return status");
        std::cout<<"IMAGE_AUDIT frame="<<number<<" level="<<l<<" elapsed="<<sim.finished[0]-sim.started[0]<<" stats=";
        for(auto word:sim.stats(layer_stats(l))) std::cout<<word<<',';
        std::cout<<" port_bytes=";
        for(unsigned p=0;p<4;++p) std::cout<<sim.counts()[p]-image_counts[p]<<',';
        std::cout<<std::endl;
        unsigned raw=RAW[l%3],blur=BLUR[l%2],next=RAW[(l+1)%3];(void)raw;
        sim.exact(blur,load(file(l,"blur")),"Blur level "+std::to_string(l));
        if(l<7) sim.exact(next,load(file(l,"resize")),"Resize level "+std::to_string(l));
        sim.exact(point_addr(l),load(file(l,"points")),"Point order level "+std::to_string(l));
        sim.exact(summary_addr(l),load(file(l,"summary")),"Summary level "+std::to_string(l));
        unsigned count=sim.word(summary_addr(l)+12);
        require(count==EXPECT_COUNT[number*8+l],"Feature count mismatch");
        auto s=sim.stats(layer_stats(l));unsigned resize=l<7?rounded(pixels(l+1)):0;
        const unsigned groups=(WIDTH[l]+LAYER_PPC-1)/LAYER_PPC*HEIGHT[l];
        const unsigned resized_groups=l<7?(LAYER_PPC==4?(WIDTH[l]+3)/4:(WIDTH[l+1]+1)/2)*HEIGHT[l+1]:0;
        std::array<unsigned,16> expected={LAYER_VERSION,0,l,WIDTH[l],HEIGHT[l],rounded(pixels(l)),rounded(pixels(l)),resize,
            groups,groups,resized_groups,s[11],LAYER_PPC|(l<7?1u:0u),0,0,0};
        require(s==expected && s[11]>0 && s[11]<=sim.finished[0]-sim.started[0],"Layer counters/metadata");
        auto now=sim.counts();
        require(now[0]-image_counts[0]==s[5] && now[1]-image_counts[1]==count*16+128 &&
                now[2]-image_counts[2]==s[6] && now[3]-image_counts[3]==s[7],"Layer AXI byte counts");
        sim.accept_stats(layer_stats(l));
        result.layers[l].count=count;result.layers[l].offset=result.selected;result.selected+=count;
        result.layers[l].image_cycles=sim.finished[0]-sim.started[0];
        for(unsigned p=0;p<4;++p) result.layers[l].image_axi_bytes+=now[p]-image_counts[p];
        std::cout<<"IMAGE_DONE frame="<<number<<" level="<<l<<" count="<<count<<" cycles="<<result.layers[l].image_cycles<<std::endl;
    };
    auto launch_descriptor=[&](unsigned l) {
        require(!sim.active[1] || sim.done[1],"Descriptor core reentry");
        unsigned count=result.layers[l].count,offset=result.layers[l].offset,raw=RAW[l%3],blur=BLUR[l%2];
        require(offset+count<=1000,"Whole-frame capacity");
        std::array<std::vector<Range>,4> rd{},wr{};
        rd[0]={{raw,raw+rounded(pixels(l))}};rd[1]={{blur,blur+rounded(pixels(l))}};
        if(count) rd[2]={{point_addr(l),point_addr(l)+16*count}};
        wr[3]={{desc_stats(l),desc_stats(l)+64}};
        if(count) wr[3].push_back({FEATURES+offset*64,FEATURES+(offset+count)*64});
        sim.set_permissions(1,rd,wr);
        for(auto pair:std::vector<std::pair<unsigned,unsigned>>{
            {reg1::RAW,raw},{reg1::BLURRED,blur},{reg1::POINTS,point_addr(l)},{reg1::FEATURES,FEATURES},
            {reg1::STATS,desc_stats(l)},{reg1::WIDTH,WIDTH[l]},{reg1::HEIGHT,HEIGHT[l]},
            {reg1::COUNT,count},{reg1::LEVEL,l},{reg1::FRAME_OFFSET,offset},{reg1::CAPACITY,1000}})
            sim.write_control(1,pair.first,pair.second);
        descriptor_counts=sim.counts();sim.active[1]=true;sim.done[1]=false;sim.started[1]=sim.cycles;
        sim.write_control(1,0,1);
    };
    auto finish_descriptor=[&](unsigned l) {
        sim.tick();
        require(sim.done[1] && sim.read_control(1,reg1::AP_RETURN)==0,"Descriptor return status");
        unsigned count=result.layers[l].count,offset=result.layers[l].offset,index=number*8+l;
        std::string name="d"+(index<10?std::string("0"):std::string())+std::to_string(index)+"_features.bin";
        sim.exact(FEATURES,load(descriptors/name),"Full appended feature buffer level "+std::to_string(l));
        auto s=sim.stats(desc_stats(l));
        std::array<unsigned,16> expected={0x00600002,0,l,count,count,offset,EXPECT_PATCH_BYTES[index][0],
            EXPECT_PATCH_BYTES[index][1],count*16,count*64,s[10],3,0,0,0,0};
        require(s==expected && s[10]>0 && s[10]<=sim.finished[1]-sim.started[1],"Descriptor metadata/cycle counter");
        auto now=sim.counts();
        require(now[4]-descriptor_counts[4]==s[6] && now[5]-descriptor_counts[5]==s[7] &&
                now[6]-descriptor_counts[6]==s[8] && now[7]-descriptor_counts[7]==s[9]+64,"Descriptor AXI byte counts");
        sim.accept_stats(desc_stats(l));result.layers[l].descriptor_cycles=sim.finished[1]-sim.started[1];
        for(unsigned p=4;p<8;++p) result.layers[l].descriptor_axi_bytes+=now[p]-descriptor_counts[p];
        std::cout<<"DESCRIPTOR_DONE frame="<<number<<" level="<<l<<" cycles="<<result.layers[l].descriptor_cycles<<std::endl;
    };
    // Strict adjacent-level overlap, with three raw and two blur owned slots.
    // Configuration uses the actual generated AXI-Lite interface, not force/release.
    launch_image(0);while(!sim.done[0]) sim.tick();finish_image(0);
    if(first_layer_only) {
        require(sim.idle(0)&&sim.idle(1),"Diagnostic layer completion responses");
        for(unsigned i=0;i<sim.memory.size();++i) if(sim.memory[i]!=sim.shadow[i])
            throw std::runtime_error("Diagnostic DDR guard byte "+std::to_string(i));
        return result;
    }
    for(unsigned l=0;l<8;++l) {
        launch_descriptor(l);
        if(l<7) launch_image(l+1);
        while(!sim.done[1] || (l<7 && !sim.done[0])) sim.tick();
        finish_descriptor(l);if(l<7) finish_image(l+1);
    }
    require(sim.idle(0)&&sim.idle(1),"Frame completion has outstanding responses");
    result.cycles=sim.cycles-begin;result.overlap_cycles=sim.overlap-old_overlap;
    for(unsigned p=0;p<8;++p) {
        auto& r=result.axi[p];const auto& port=sim.ports[p];
        for(unsigned m=0;m<AXI_METRIC_COUNT;++m) r.activity[m]=port.activity[m]-old_axi[p].activity[m];
        r.read_bytes=port.read_bytes-old_axi[p].read_bytes;r.write_bytes=port.write_bytes-old_axi[p].write_bytes;
        r.read_highwater=port.read_highwater;r.write_highwater=port.write_highwater;
        require(r.activity[0]<=r.activity[2],"AXI read beat/request counters");
        require(r.activity[1]==r.activity[4],"Frame has missing write response count");
    }
    for(unsigned q=0;q<4;++q) {
        result.ddr_activity[q]=sim.ddr_activity[q]-old_ddr[q];
        result.hp_service_beats[q]=sim.hp_service_beats[q]-old_hp[q];
        result.hp_read_service_beats[q]=sim.hp_read_service_beats[q]-old_hp_read[q];
        result.hp_write_service_beats[q]=sim.hp_write_service_beats[q]-old_hp_write[q];
    }
#ifdef ORB60_NATIVE_PROFILE
    for(unsigned p=0;p<PROFILE_COUNT;++p) result.profile_cycles[p]=sim.profile_cycles[p]-old_profile[p];
    result.fifo_highwater=sim.fifo_highwater;
    for(unsigned f=0;f<PROFILE_FIFO_COUNT;++f) require(sim.fifo_level[f]==0,"Frame ended with pending profile FIFO tokens");
#endif
    for(unsigned i=0;i<8;++i) {
        result.read_bytes+=sim.ports[i].read_bytes;result.write_bytes+=sim.ports[i].write_bytes;
        result.contention+=sim.ports[i].contention;
    }
    // Counters above are cumulative; return per-frame traffic below.
    uint64_t old_total=0;for(auto n:old) old_total+=n;
    require(result.read_bytes+result.write_bytes>=old_total,"Traffic counter underflow");
    for(unsigned i=0;i<sim.memory.size();++i) if(sim.memory[i]!=sim.shadow[i])
        throw std::runtime_error("Untouched DDR guard byte "+std::to_string(i));
    std::cout<<"FRAME_PASS frame="<<number<<" selected="<<result.selected<<" cycles="<<result.cycles<<std::endl;
    return result;
}

int main(int argc,char** argv) {
    try {
        Verilated::commandArgs(argc,argv);
        if(argc==2 && std::string(argv[1])=="--link-smoke") {
            Simulation sim(2,0,6001);
            require(native_time_ps==20*CLOCK_PERIOD_PS && sim.idle(0) && sim.idle(1),"Native clock/reset startup");
            sim.dut.final();std::cout<<"NATIVE_LINK_RESET_PASS"<<std::endl;return 0;
        }
        bool first_layer=false;unsigned read_min=0,read_max=5;uint64_t board_rate=0;
        for(int a=7;a<argc;++a) {
            const std::string option=argv[a];
            if(option=="--first-layer") first_layer=true;
            else if(option=="--read-delay" && a+2<argc) {
                read_min=unsigned(std::stoul(argv[++a]));read_max=unsigned(std::stoul(argv[++a]));
            } else if(option=="--board-ddr-bytes-per-second" && a+1<argc) {
                board_rate=std::stoull(argv[++a]);require(board_rate>0,"Board DDR rate must be positive");
            } else throw std::runtime_error("Unknown or incomplete option: "+option);
        }
        require(argc>=7,"Usage: native images descriptors result budget stall_percent seed [--first-layer] [--read-delay min max]");
        diagnostic_directory=fs::path(argv[3]).parent_path();
        unsigned budget=unsigned(std::stoul(argv[4])),stalls=unsigned(std::stoul(argv[5])),seed=unsigned(std::stoul(argv[6]));
        Simulation sim(budget,stalls,seed,read_min,read_max,board_rate);
        if(first_layer) {
            frame(sim,0,argv[1],argv[2],true);sim.dut.final();
            std::cout<<"NATIVE_LAYER0_DIAGNOSTIC_PASS"<<std::endl;return 0;
        }
        std::array<FrameResult,3> frames;
        uint64_t old_read=0,old_write=0,old_stall=0;
        for(unsigned i=0;i<3;++i) {
            frames[i]=frame(sim,i,argv[1],argv[2]);
            auto& f=frames[i];uint64_t cumulative_read=f.read_bytes,cumulative_write=f.write_bytes,cumulative_stall=f.contention;
            f.read_bytes-=old_read;f.write_bytes-=old_write;f.contention-=old_stall;
            old_read=cumulative_read;old_write=cumulative_write;old_stall=cumulative_stall;
        }
        std::ofstream out(argv[3]);require(bool(out),"Cannot create result");
        out<<"{\"status\":\"PASS\",\"ddr_beats_per_cycle\":"<<sim.beat_budget<<",\"random_stall_percent\":"<<stalls
           <<",\"seed\":"<<seed<<",\"hp_shared_service_limit\":"<<(board_rate?0:1)
           <<",\"hp_mapping\":[0,3,1,2,0,1,3,2],\"read_initial_delay_cycles\":["<<read_min<<','<<read_max
           <<"],\"write_response_delay_cycles\":[2,31],\"clock_period_ps\":"<<CLOCK_PERIOD_PS
           <<",\"ddr_capacity_bytes_per_second\":"<<sim.service_time.capacity_bytes_per_second()
           <<",\"hp_capacity_bytes_per_second\":"<<sim.service_time.hp_capacity_bytes_per_second()
           <<",\"ddr_model\":\""<<(board_rate?"board_spec_capacity":"legacy_reference")<<"\""
           <<",\"hp_independent_read_write\":"<<(board_rate?"true":"false")
           <<",\"hp_ddri_port_mapping\":[3,3,2,2],\"axi_metric_version\":2"
           <<",\"read_initial_delay_ns\":["<<read_min*10<<','<<read_max*10
           <<"],\"write_response_delay_ns\":[20,310],\"frames\":[";
        for(unsigned i=0;i<3;++i) {
            auto f=frames[i];if(i) out<<',';
            out<<"{\"frame\":"<<i<<",\"selected\":"<<f.selected<<",\"cycles\":"<<f.cycles
               <<",\"overlap_cycles\":"<<f.overlap_cycles<<",\"read_bytes\":"<<f.read_bytes<<",\"write_bytes\":"<<f.write_bytes
               <<",\"arbitration_or_random_wait_cycles\":"<<f.contention<<",\"layers\":[";
            for(unsigned l=0;l<8;++l) {
                auto r=f.layers[l];if(l) out<<',';
                out<<"{\"level\":"<<l<<",\"count\":"<<r.count<<",\"offset\":"<<r.offset<<",\"image_cycles\":"<<r.image_cycles
                   <<",\"descriptor_cycles\":"<<r.descriptor_cycles<<",\"image_axi_bytes\":"<<r.image_axi_bytes
                   <<",\"descriptor_axi_bytes\":"<<r.descriptor_axi_bytes<<'}';
            }
            out<<"],\"ddr_service\":{\"used_cycles\":"<<f.ddr_activity[0]<<",\"idle_cycles\":"<<f.ddr_activity[1]
               <<",\"read_beats\":"<<f.ddr_activity[2]<<",\"write_beats\":"<<f.ddr_activity[3]<<",\"hp_service_beats\":[";
            for(unsigned q=0;q<4;++q) {if(q) out<<',';out<<f.hp_service_beats[q];}
            out<<"],\"hp_read_service_beats\":[";
            for(unsigned q=0;q<4;++q) {if(q) out<<',';out<<f.hp_read_service_beats[q];}
            out<<"],\"hp_write_service_beats\":[";
            for(unsigned q=0;q<4;++q) {if(q) out<<',';out<<f.hp_write_service_beats[q];}
            out<<"]},\"axi_ports\":[";
            for(unsigned p=0;p<8;++p) {
                const auto& r=f.axi[p];if(p) out<<',';
                out<<"{\"port\":"<<p<<",\"hp\":"<<Simulation::hp[p]<<",\"read_bytes\":"<<r.read_bytes
                   <<",\"write_bytes\":"<<r.write_bytes<<",\"read_outstanding_max\":"<<r.read_highwater<<",\"write_outstanding_max\":"<<r.write_highwater;
                for(unsigned m=0;m<AXI_METRIC_COUNT;++m) out<<",\""<<AXI_METRIC_NAMES[m]<<"\":"<<r.activity[m];
                out<<'}';
            }
            out<<"]";
#ifdef ORB60_NATIVE_PROFILE
            out<<",\"profile\":[";
            for(unsigned p=0;p<PROFILE_COUNT;++p) {
                if(p) out<<',';
                out<<"{\"name\":\""<<PROFILE_NAMES[p]<<"\",\"core\":"<<PROFILE_CORE[p]
                   <<",\"cycles\":"<<f.profile_cycles[p]<<'}';
            }
            out<<"],\"fifo_watermarks\":[";
            for(unsigned q=0;q<PROFILE_FIFO_COUNT;++q) {
                if(q) out<<',';
                out<<"{\"push_probe\":"<<PROFILE_FIFOS[q].push<<",\"depth\":"<<PROFILE_FIFOS[q].depth
                   <<",\"max_occupancy\":"<<f.fifo_highwater[q]<<'}';
            }
            out<<"]";
#endif
            out<<"}";
        }
        out<<"]}\n";sim.dut.final();std::cout<<"NATIVE_FRAME_PASS"<<std::endl;return 0;
    } catch(const std::exception& e) { std::cerr<<"NATIVE_FRAME_FAIL "<<e.what()<<std::endl;return 1; }
}
