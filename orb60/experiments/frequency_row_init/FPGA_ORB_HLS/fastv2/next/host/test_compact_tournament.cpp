// Original scalar ordering versus compact unsigned keys, including exact ties.
#include "../src/fastv2_hls.cpp"
#include <iostream>
#include <stdexcept>
#include <tuple>

static uint32_t seed=0x6013c011u;
static uint32_t next_random() {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
static void check(const Point& a,int ac,const Point& b,int bc) {
    const auto ka=compact_tournament_key(pack_point(a),ac),kb=compact_tournament_key(pack_point(b),bc);
    const auto winner=tournament_winner(ka,kb);
    if(!a.score && !b.score) {if(winner)throw std::runtime_error("invalid key was not zero");return;}
    const bool pick_a=!b.score || (a.score && std::make_tuple(-a.score,a.y,a.x,ac)<=std::make_tuple(-b.score,b.y,b.x,bc));
    const int expected=pick_a?ac:bc;
    if(int(uint8_t(~uint8_t(uint64_t(winner))))!=expected || winner!=(pick_a?ka:kb))
        throw std::runtime_error("score/y/x/cell priority changed");
}
int main() {
    try {
        uint64_t cases=0;const unsigned mask=(1u<<kTournamentCoordinateBits)-1;
        for(int score:{0,1,7,20,254,255}) for(int ac:{0,1,127,203,255}) for(int bc:{0,1,127,203,255}) {
            check({int(mask),int(mask),score,2047},ac,{int(mask),int(mask),score,0},bc);++cases;
            check({0,int(mask),score,0},ac,{int(mask),0,score,2047},bc);++cases;
        }
        for(int i=0;i<1000000;++i) {
            Point a={int(next_random()&mask),int(next_random()&mask),int(next_random()&255),int(next_random()&2047)};
            Point b={int(next_random()&mask),int(next_random()&mask),int(next_random()&255),int(next_random()&2047)};
            if((i&7)==0) {b.x=a.x;b.y=a.y;b.score=a.score;}
            check(a,int(next_random()&255),b,int(next_random()&255));++cases;
        }
        std::cout<<"COMPACT_TOURNAMENT_EXACT_PASS cases="<<cases<<" key_bits="<<kTournamentKeyBits<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<"COMPACT_TOURNAMENT_FAIL "<<e.what()<<'\n';return 1;}
}
