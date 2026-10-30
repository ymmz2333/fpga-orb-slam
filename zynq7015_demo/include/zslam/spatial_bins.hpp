#pragma once
#include "math.hpp"
#include <stdexcept>
namespace zslam {
// Stable CSR bins: one index per input, no per-cell heap allocation.
// Positions outside the historical 30x23 grid are excluded. Circle filtering
// stays with the caller so its original distance test and tie ordering remain.
class SpatialBins {
    static constexpr int cell=32,cols=30,rows=23;
    std::array<unsigned,cols*rows+1> heads_{};
    std::vector<unsigned> indices_;std::vector<int> labels_;
    static int label(V2 p){
        if(!std::isfinite(p.x)||!std::isfinite(p.y)||p.x<0||p.y<0||p.x>=cols*cell||p.y>=rows*cell)return -1;
        return static_cast<int>(p.y/cell)*cols+static_cast<int>(p.x/cell);
    }
public:
    template<class Position>void build(unsigned count,Position position){
        if(count>50000)throw std::runtime_error("Spatial index exceeds bounded point capacity");
        heads_.fill(0);labels_.resize(count);
        for(unsigned i=0;i<count;i++){int bin=label(position(i));labels_[i]=bin;if(bin>=0)heads_[bin+1]++;}
        for(unsigned bin=1;bin<heads_.size();bin++)heads_[bin]+=heads_[bin-1];
        indices_.resize(heads_.back());auto cursor=heads_;
        for(unsigned i=0;i<count;i++)if(labels_[i]>=0)indices_[cursor[labels_[i]]++]=i;
    }
    template<class Visit>void visit(V2 center,double radius,Visit accept)const{
        if(!std::isfinite(center.x)||!std::isfinite(center.y)||!std::isfinite(radius)||radius<0)return;
        double left=std::max(0.,center.x-radius),right=std::min(double(cols*cell),center.x+radius);
        double top=std::max(0.,center.y-radius),bottom=std::min(double(rows*cell),center.y+radius);
        if(left>right||top>bottom)return;
        int x0=std::min(cols-1,static_cast<int>(left/cell)),x1=std::min(cols-1,static_cast<int>(right/cell));
        int y0=std::min(rows-1,static_cast<int>(top/cell)),y1=std::min(rows-1,static_cast<int>(bottom/cell));
        for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){
            unsigned bin=static_cast<unsigned>(y*cols+x);
            for(unsigned at=heads_[bin];at<heads_[bin+1];at++)accept(indices_[at]);
        }
    }
    std::size_t reservedBytes()const{return sizeof(heads_)+indices_.capacity()*sizeof(unsigned)+labels_.capacity()*sizeof(int);}
};
}
