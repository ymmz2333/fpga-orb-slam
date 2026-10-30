#include "golden.hpp"
#include "constants.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <list>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace orb_golden {
static void require(bool v,const char* message) { if(!v)throw std::runtime_error(message); }
int64_t round_even(int64_t value,int64_t divisor) {
    require(divisor>0,"Nonpositive divisor");
    bool neg=value<0;uint64_t v=neg?uint64_t(-(value+1))+1:uint64_t(value),d=uint64_t(divisor);
    uint64_t q=v/d,r=v%d;
    if(r>d-r || (r==d-r && (q&1)))++q;
    return neg?-int64_t(q):int64_t(q);
}
uint64_t isqrt(uint64_t n) {
    uint64_t r=0,b=uint64_t(1)<<62;
    while(b>n)b>>=2;
    while(b) { if(n>=r+b){n-=r+b;r=(r>>1)+b;}else r>>=1;b>>=2; }
    return r;
}
// Encode a rational into IEEE-754 binary32 without executing floating operations.
// Supported finite normal range covers every B1 field in the supported geometry.
uint32_t binary32_bits(int64_t numerator,uint64_t denominator) {
    require(denominator>0,"Zero binary32 denominator");
    if(!numerator)return 0;
    bool neg=numerator<0;uint64_t n=neg?uint64_t(-(numerator+1))+1:uint64_t(numerator);
    int e=0;__uint128_t v=n,d=denominator;
    while(v<d){v<<=1;--e;}
    while(v>=(d<<1)){d<<=1;++e;}
    require(e>=-126 && e<=127,"binary32 range");
    __uint128_t scaled=v<<23,q=scaled/d,r=scaled%d;
    if(r>d-r || (r==d-r && (q&1)))++q;
    if(q==(uint64_t(1)<<24)){q>>=1;++e;}
    return (neg?0x80000000u:0u)|(uint32_t(e+127)<<23)|(uint32_t(q)&0x7fffffu);
}
int reflect101(int p,int size) {
    require(size>0,"Empty reflection domain");if(size==1)return 0;
    while(p<0||p>=size) { if(p<0)p=-p;else p=2*size-p-2; }
    return p;
}
struct Axis { int a,b;int weight; };
static Axis axis(int target,int src,int dst) {
    // Pixel-centre map ((2*x+1)*src-dst)/(2*dst), replicated edges.
    int64_t num=int64_t(2*target+1)*src-dst,den=int64_t(2)*dst;
    int64_t a=num/den,r=num%den;
    if(r<0){--a;r+=den;}
    if(a<0)return {0,0,0};
    if(a>=src-1)return {src-1,src-1,0};
    int weight=int(round_even(r*2048,den));
    return {int(a),int(a+1),weight};
}
Image resize_linear(const Image& src,int w,int h) {
    require(w>0&&h>0,"Empty resize");Image out(w,h);
    std::vector<Axis> xs;for(int x=0;x<w;++x)xs.push_back(axis(x,src.width,w));
    for(int y=0;y<h;++y) {
        Axis a=axis(y,src.height,h);
        for(int x=0;x<w;++x) {
            Axis b=xs[size_t(x)];
            int64_t row0=int64_t(src.at(b.a,a.a))*(2048-b.weight)+int64_t(src.at(b.b,a.a))*b.weight;
            int64_t row1=int64_t(src.at(b.a,a.b))*(2048-b.weight)+int64_t(src.at(b.b,a.b))*b.weight;
            // OpenCV 8-bit INTER_LINEAR optimized vertical path: row >>4;
            // each weighted product >>16; final (+2)>>2. Define it explicitly.
            int64_t value=((row0>>4)*(2048-a.weight)>>16)+((row1>>4)*a.weight>>16);
            out.at(x,y)=uint8_t((value+2)>>2);
        }
    }
    return out;
}
Image gaussian7(const Image& src) {
    // sigma=2, 7 taps, normalized Q0.8 kernel; two axes, one final rounding.
    constexpr int k[7]={18,34,48,56,48,34,18};
    std::vector<uint16_t> horizontal(src.pixels.size());Image out(src.width,src.height);
    for(int y=0;y<src.height;++y)for(int x=0;x<src.width;++x) {
        uint32_t s=0;for(int i=0;i<7;++i)s+=uint32_t(k[i])*src.at(reflect101(x+i-3,src.width),y);
        horizontal[size_t(y)*size_t(src.width)+size_t(x)]=uint16_t(s);
    }
    for(int y=0;y<src.height;++y)for(int x=0;x<src.width;++x) {
        uint32_t s=0;for(int i=0;i<7;++i)s+=uint32_t(k[i])*horizontal[size_t(reflect101(y+i-3,src.height))*size_t(src.width)+size_t(x)];
        out.at(x,y)=uint8_t((s+32768u)>>16);
    }
    return out;
}
Image fast_scores(const Image& im) {
    constexpr int dx[16]={0,1,2,3,3,3,2,1,0,-1,-2,-3,-3,-3,-2,-1};
    constexpr int dy[16]={3,3,2,1,0,-1,-2,-3,-3,-3,-2,-1,0,1,2,3};
    Image out(im.width,im.height);
    for(int y=3;y<im.height-3;++y)for(int x=3;x<im.width-3;++x) {
        int diff[25],center=im.at(x,y);
        for(int i=0;i<16;++i)diff[i]=int(im.at(x+dx[i],y+dy[i]))-center;
        for(int i=16;i<25;++i)diff[i]=diff[i-16];
        int best=0;
        for(int i=0;i<16;++i) {
            int lo=255,hi=-255;
            for(int j=0;j<9;++j){lo=std::min(lo,diff[i+j]);hi=std::max(hi,diff[i+j]);}
            best=std::max(best,std::max(lo,-hi));
        }
        out.at(x,y)=uint8_t(std::max(0,best-1));
    }
    return out;
}
static std::vector<Point> tile_nms(const Image& score,int x0,int y0,int x1,int y1,int threshold,int tile) {
    std::vector<Point> out;
    for(int y=y0+3;y<y1-3;++y)for(int x=x0+3;x<x1-3;++x) {
        int s=score.at(x,y);if(s<threshold)continue;
        bool keep=true;
        for(int j=-1;j<=1&&keep;++j)for(int i=-1;i<=1;++i) {
            if(i==0&&j==0)continue;
            int nx=x+i,ny=y+j;
            int n=(nx>=x0+3&&nx<x1-3&&ny>=y0+3&&ny<y1-3)?score.at(nx,ny):0;
            if(n>=s){keep=false;break;}
        }
        if(keep)out.push_back({x-16,y-16,s,tile});
    }
    return out;
}
static std::vector<Point> candidates_with_scores(const Image& score,const Config& c) {
    int w=score.width-32,h=score.height-32,cols=w/35,rows=h/35;
    // Extension: a nonempty area smaller than 35 has one tile (B2 divided by zero).
    if(w<=6||h<=6)return {};
    cols=std::max(1,cols);rows=std::max(1,rows);
    int wc=(w+cols-1)/cols,hc=(h+rows-1)/rows;
    std::vector<Point> out;
    for(int y=0;y<rows;++y)for(int x=0;x<cols;++x) {
        int iy=16+y*hc,ix=16+x*wc,my=std::min(iy+hc+6,score.height-16),mx=std::min(ix+wc+6,score.width-16);
        if(iy>=score.height-19||ix>=score.width-22)continue;
        auto cell=tile_nms(score,ix,iy,mx,my,c.dual_threshold?c.low_threshold:c.threshold,y*cols+x);
        if(cell.empty()&&!c.fixed_fast)cell=tile_nms(score,ix,iy,mx,my,c.low_threshold,y*cols+x);
        out.insert(out.end(),cell.begin(),cell.end());
    }
    return out;
}
std::vector<Point> tiled_candidates(const Image& im,const Config& c) { return candidates_with_scores(fast_scores(im),c); }
static bool raster(const Point& a,const Point& b){return a.y<b.y||(a.y==b.y&&a.x<b.x);}
static bool strongest(const Point& a,const Point& b){return a.score>b.score||(a.score==b.score&&raster(a,b));}
std::vector<Point> select_grid(const std::vector<Point>& keys,int w,int h,int budget,Layer& l,const Config* config) {
    if(budget<=0||w<=0||h<=0)return {};
    l.cell_side=std::max(1,int(isqrt(uint64_t(w)*uint64_t(h)/uint64_t(budget))));
    l.cell_cols=std::max(1,w/l.cell_side);l.cell_rows=std::max(1,h/l.cell_side);
    const int top_k=config?config->grid_top_k:1;
    const bool dual=config&&config->dual_threshold;
    const int high=config?config->threshold:20,low=config?config->low_threshold:7;
    std::vector<std::vector<Point>> cells(size_t(l.cell_cols)*size_t(l.cell_rows));
    for(size_t i=0;i<keys.size();++i) {
        const Point& k=keys[i];require(k.x>=0&&k.x<w&&k.y>=0&&k.y<h,"Candidate outside effective area");
        int x=std::min(k.x/l.cell_side,l.cell_cols-1),y=std::min(k.y/l.cell_side,l.cell_rows-1);
        cells[size_t(y*l.cell_cols+x)].push_back(k);
    }
    std::vector<Point> out;
    for(auto& cell:cells) {
        if(dual) {
            const bool has_high=std::any_of(cell.begin(),cell.end(),[&](const Point& p){return p.score>=high;});
            cell.erase(std::remove_if(cell.begin(),cell.end(),[&](const Point& p){return p.score<(has_high?high:low);}),cell.end());
            if(!has_high&&!cell.empty())++l.fallback_cells;
        }
        if(cell.empty()){++l.empty_cells;continue;}
        std::stable_sort(cell.begin(),cell.end(),strongest);
        const size_t count=std::min(cell.size(),size_t(top_k));
        out.insert(out.end(),cell.begin(),cell.begin()+static_cast<std::ptrdiff_t>(count));
    }
    if(int(out.size())>budget){std::stable_sort(out.begin(),out.end(),strongest);out.resize(size_t(budget));}
    return out;
}
// Integer translation of ORB-SLAM3's linked-list octree for simplifications-off audit.
struct Node { int x0=0,y0=0,x1=0,y1=0;std::vector<Point> keys; };
static std::vector<Point> octree(const std::vector<Point>& keys,int w,int h,int budget) {
    if(keys.empty()||budget<=0)return {};
    std::list<Node> nodes;
    int ni=std::max(1,int((int64_t(w)*2+h)/(2*h)));
    std::vector<std::list<Node>::iterator> initial;
    for(int i=0;i<ni;++i){nodes.push_back({w*i/ni,0,w*(i+1)/ni,h,{}});initial.push_back(std::prev(nodes.end()));}
    for(auto p:keys)initial[size_t(std::min(ni-1,p.x*ni/w))]->keys.push_back(p);
    for(auto i=nodes.begin();i!=nodes.end();)if(i->keys.empty())i=nodes.erase(i);else ++i;
    using Iterator=std::list<Node>::iterator;
    std::vector<Iterator> expandable;
    auto split=[&](Iterator i) {
        int xm=i->x0+(i->x1-i->x0+1)/2,ym=i->y0+(i->y1-i->y0+1)/2;
        std::array<Node,4> sub={Node{i->x0,i->y0,xm,ym,{}},Node{xm,i->y0,i->x1,ym,{}},Node{i->x0,ym,xm,i->y1,{}},Node{xm,ym,i->x1,i->y1,{}}};
        for(auto p:i->keys)sub[size_t((p.x>=xm?1:0)+(p.y>=ym?2:0))].keys.push_back(p);
        for(auto& n:sub)if(!n.keys.empty()) { nodes.push_front(std::move(n));if(nodes.front().keys.size()>1)expandable.push_back(nodes.begin()); }
        return nodes.erase(i);
    };
    bool finished=false;
    while(!finished) {
        size_t before=nodes.size();expandable.clear();
        for(auto i=nodes.begin();i!=nodes.end();) { if(i->keys.size()<=1)++i;else i=split(i); }
        finished=int(nodes.size())>=budget||nodes.size()==before;
        if(!finished&&int(nodes.size()+expandable.size()*3)>budget) {
            while(!finished) {
                before=nodes.size();auto prev=expandable;expandable.clear();
                std::sort(prev.begin(),prev.end(),[](Iterator a,Iterator b){return a->keys.size()<b->keys.size()||(a->keys.size()==b->keys.size()&&a->x0<b->x0);});
                for(auto i=prev.rbegin();i!=prev.rend();++i) { split(*i);if(int(nodes.size())>=budget)break; }
                finished=int(nodes.size())>=budget||nodes.size()==before;
            }
        }
    }
    std::vector<Point> out;
    for(auto& n:nodes) { Point best=n.keys[0];for(auto p:n.keys)if(p.score>best.score)best=p;out.push_back(best); }
    return out;
}
std::vector<int> budgets(const Config& c) {
    constexpr uint64_t one=uint64_t(1)<<32;
    std::vector<uint64_t> weight(size_t(c.levels));weight[0]=one;
    uint64_t sum=one;
    for(int l=1;l<c.levels;++l){weight[size_t(l)]=uint64_t(round_even(int64_t(weight[size_t(l-1)]*c.scale_den),c.scale_num));sum+=weight[size_t(l)];}
    std::vector<int> b(size_t(c.levels));int used=0;
    // Q32 first desired count and reciprocal progression, then nearest-even.
    uint64_t desired=uint64_t((__uint128_t(c.features)*one*one+sum/2)/sum);
    for(int l=0;l<c.levels-1;++l) {
        b[size_t(l)]=std::min(c.features-used,int(round_even(int64_t(desired),int64_t(one))));used+=b[size_t(l)];
        desired=uint64_t(round_even(int64_t(desired*c.scale_den),c.scale_num));
    }
    b.back()=std::max(0,c.features-used);return b;
}
std::pair<int32_t,int32_t> moments(const Image& im,int x,int y) {
    int32_t m10=0,m01=0;
    for(int u=-15;u<=15;++u)m10+=u*im.at(x+u,y);
    for(int v=1;v<=15;++v) {
        int vs=0;
        for(int u=-umax[v];u<=umax[v];++u) {
            int plus=im.at(x+u,y+v),minus=im.at(x+u,y-v);
            vs+=plus-minus;m10+=u*(plus+minus);
        }
        m01+=v*vs;
    }
    return {m10,m01};
}
static int64_t signed_shift(int64_t x,int k) {
    if(k==0)return x;
    return x>=0?x/(int64_t(1)<<k):-((-x+(int64_t(1)<<k)-1)/(int64_t(1)<<k));
}
uint32_t angle_q16(int32_t m10,int32_t m01) {
    if(m10==0&&m01==0)return 0;
    if(m01==0)return m10<0?180u*65536u:0u;
    if(m10==0)return m01<0?270u*65536u:90u*65536u;
    int64_t x=int64_t(m10)*(int64_t(1)<<20),y=int64_t(m01)*(int64_t(1)<<20),z=0;
    if(x<0){x=-x;y=-y;z=int64_t(180)<<24;}
    for(int k=0;k<32&&y!=0;++k) {
        int64_t old=x;
        if(y>0){x+=signed_shift(y,k);y-=signed_shift(old,k);z+=cordic_degrees_q24[k];}
        else {x-=signed_shift(y,k);y+=signed_shift(old,k);z-=cordic_degrees_q24[k];}
    }
    int64_t full=int64_t(360)<<24;z=(z%full+full)%full;
    return uint32_t(round_even(z,256)%(int64_t(360)<<16));
}
int quantize(uint32_t angle,int bins) {
    require(bins==8||bins==32,"Only A8/A32 supported");
    uint64_t full=uint64_t(360)<<16;
    return int((uint64_t(angle)*uint64_t(bins)+full/2)/full%uint64_t(bins));
}
static std::pair<int64_t,int64_t> sincos_q30(uint32_t angle) {
    int64_t z=int64_t(angle)*256;
    int64_t full=int64_t(360)<<24;
    if(z>(int64_t(180)<<24))z-=full;
    int sign=1;
    if(z>(int64_t(90)<<24)){z-=int64_t(180)<<24;sign=-1;}
    if(z<-(int64_t(90)<<24)){z+=int64_t(180)<<24;sign=-1;}
    int64_t x=cordic_gain_q30,y=0;
    for(int k=0;k<32;++k) {
        int64_t old=x;
        if(z>=0){x-=signed_shift(y,k);y+=signed_shift(old,k);z-=cordic_degrees_q24[k];}
        else {x+=signed_shift(y,k);y-=signed_shift(old,k);z+=cordic_degrees_q24[k];}
    }
    return {sign*x,sign*y};
}
Feature describe(const Image& raw,const Image& blurred,Point p,int level,int bins) {
    Feature f;f.point=p;f.level=level;
    auto m=moments(raw,p.x,p.y);f.m10=m.first;f.m01=m.second;
    f.angle_q16=angle_q16(f.m10,f.m01);
    int64_t co,si;
    if(bins) {
        f.bin=quantize(f.angle_q16,bins);f.angle_q16=uint32_t(uint64_t(f.bin)*(uint64_t(360)<<16)/uint64_t(bins));
        int index=f.bin*(32/bins);co=trig32[index][0];si=trig32[index][1];
    } else {f.bin=-1;auto cs=sincos_q30(f.angle_q16);co=cs.first;si=cs.second;}
    auto sample=[&](int index) {
        int x=pattern[index],y=pattern[index+1];
        int dx=int(round_even(x*co-y*si,int64_t(1)<<30));
        int dy=int(round_even(x*si+y*co,int64_t(1)<<30));
        return blurred.at(p.x+dx,p.y+dy);
    };
    for(int bit=0;bit<256;++bit)if(sample(bit*4)<sample(bit*4+2))f.descriptor[size_t(bit/8)]|=uint8_t(1u<<(bit%8));
    return f;
}
Result extract(const Image& im,const Config& c,const Result* prepared) {
    require(im.width>0&&im.height>0&&im.width<=ORB_MAX_WIDTH&&im.height<=ORB_MAX_HEIGHT,"Image bounds");
    require(im.pixels.size()==size_t(im.width)*size_t(im.height),"Image storage length");
    require(c.levels>=1&&c.levels<=8&&c.features>0&&c.features<=ORB_MAX_FEATURES,"Configuration bounds");
    require(c.scale_den>0&&c.scale_num>c.scale_den&&c.scale_num<=16&&c.scale_den<=16,"Scale must be rational >1, numerator/denominator <=16");
    require(c.threshold>=1&&c.threshold<=255&&c.low_threshold>=1&&c.low_threshold<=255,"FAST threshold 1..255");
    require(c.angle_bins==0||c.angle_bins==8||c.angle_bins==32,"Angle mode");
    require(c.grid_top_k>=1&&c.grid_top_k<=ORB_MAX_FEATURES,"Grid top-K bounds");
    require(!c.dual_threshold||(c.grid&&c.fixed_fast&&c.low_threshold<=c.threshold),"T2 requires grid/fixed FAST and ordered thresholds");
    require(!c.box2||(c.levels==2&&c.scale_num==2*c.scale_den&&im.width%2==0&&im.height%2==0),"box2 requires even image, L2, scale2");
    Result r;auto bs=budgets(c);uint64_t scale=uint64_t(1)<<24;
    bool reusable=prepared&&!prepared->layers.empty()&&prepared->layers[0].image.pixels==im.pixels&&
        prepared->layers[0].image.width==im.width&&prepared->layers[0].image.height==im.height&&!c.box2;
    std::vector<Feature> natural;
    for(int l=0;l<c.levels;++l) {
        Layer layer;layer.scale_q24=scale;layer.budget=bs[size_t(l)];
        int w=int(round_even(int64_t(im.width)*(int64_t(1)<<24),int64_t(scale))),h=int(round_even(int64_t(im.height)*(int64_t(1)<<24),int64_t(scale)));
        require(w>0&&h>0,"Pyramid dimension became zero");
        bool cached=reusable&&size_t(l)<prepared->layers.size()&&prepared->layers[size_t(l)].scale_q24==scale;
        if(cached)layer.image=prepared->layers[size_t(l)].image;
        else if(l==0)layer.image=im;
        else if(c.box2) {
            layer.image=Image(w,h);
            for(int y=0;y<h;++y)for(int x=0;x<w;++x) {
                int s=im.at(2*x,2*y)+im.at(2*x+1,2*y)+im.at(2*x,2*y+1)+im.at(2*x+1,2*y+1);
                layer.image.at(x,y)=uint8_t((s+(c.box_half_up?2:0))/4);
            }
        } else layer.image=resize_linear(r.layers.back().image,w,h);
        layer.score=cached?prepared->layers[size_t(l)].score:fast_scores(layer.image);layer.candidates=candidates_with_scores(layer.score,c);
        if(c.grid)layer.selected=select_grid(layer.candidates,w-32,h-32,layer.budget,layer,&c);
        else layer.selected=octree(layer.candidates,w-32,h-32,layer.budget);
        if(!c.counts_only)layer.blurred=c.blur?gaussian7(layer.image):layer.image;
        if(!c.counts_only)for(auto p:layer.selected) {
            p.x+=16;p.y+=16;Feature f=describe(layer.image,layer.blurred,p,l,c.angle_bins);
            layer.features.push_back(f);natural.push_back(f);
        }
        r.layers.push_back(std::move(layer));
        scale=uint64_t(round_even(int64_t(scale*c.scale_num),c.scale_den));
    }
    r.ordered.resize(natural.size());size_t left=0,right=natural.size();
    for(auto f:natural) {
        uint64_t x=uint64_t(f.point.x)*r.layers[size_t(f.level)].scale_q24;
        bool overlap=int64_t(x)>=int64_t(c.overlap_left)*(int64_t(1)<<24)&&int64_t(x)<=int64_t(c.overlap_right)*(int64_t(1)<<24);
        if(overlap)r.ordered[--right]=f;else r.ordered[left++]=f;
    }
    r.mono_left=int(left);return r;
}
static std::string token(std::istream& f) {
    std::string s;
    for(;;){f>>std::ws;if(f.peek()!='#')break;std::getline(f,s);}
    f>>s;return s;
}
Image read_pgm(const std::string& path) {
    std::ifstream f(path,std::ios::binary);require(bool(f),"Cannot open PGM");
    require(token(f)=="P5","Only binary P5 grayscale supported");int w=std::stoi(token(f)),h=std::stoi(token(f));
    require(w>0&&h>0&&w<=ORB_MAX_WIDTH&&h<=ORB_MAX_HEIGHT,"PGM bounds");require(token(f)=="255","PGM maxval must be 255");
    int ws=f.get();require(ws=='\n'||ws=='\r'||ws==' '||ws=='\t',"PGM separator");if(ws=='\r'&&f.peek()=='\n')f.get();
    Image im(w,h);f.read(reinterpret_cast<char*>(im.pixels.data()),std::streamsize(im.pixels.size()));
    require(f.gcount()==std::streamsize(im.pixels.size())&&f.peek()==std::char_traits<char>::eof(),"PGM payload length");return im;
}
void write_pgm(const std::string& path,const Image& im) {
    std::ofstream f(path,std::ios::binary);f<<"P5\n"<<im.width<<' '<<im.height<<"\n255\n";
    f.write(reinterpret_cast<const char*>(im.pixels.data()),std::streamsize(im.pixels.size()));require(bool(f),"PGM write failed");
}
static void le(std::ostream& f,uint64_t v,int bytes) { for(int i=0;i<bytes;++i)f.put(char((v>>(8*i))&255)); }
void write_packet(const std::string& path,const Result& r,const Config& c,int width,int height,uint64_t ns,int role) {
    std::ofstream f(path,std::ios::binary);require(bool(f),"Cannot create packet");
    f.write("ORBFEAT\0",8);le(f,1,2);le(f,64,2);le(f,64,2);le(f,uint64_t(role),1);le(f,0,1);
    le(f,ns,8);le(f,uint64_t(width),4);le(f,uint64_t(height),4);le(f,r.ordered.size(),4);le(f,uint64_t(c.levels),4);
    le(f,binary32_bits(c.scale_num,c.scale_den),4);le(f,uint64_t(c.features),4);le(f,32,4);le(f,0,4);le(f,uint64_t(r.mono_left),4);le(f,0,4);
    for(const auto& p:r.ordered) {
        uint64_t scale=r.layers[size_t(p.level)].scale_q24;
        le(f,binary32_bits(int64_t(p.point.x)*int64_t(scale),uint64_t(1)<<24),4);
        le(f,binary32_bits(int64_t(p.point.y)*int64_t(scale),uint64_t(1)<<24),4);
        le(f,uint64_t(p.level),4);le(f,binary32_bits(p.angle_q16,uint64_t(1)<<16),4);
        // B2 size is int(31*scale), then converted to binary32.
        le(f,binary32_bits(int64_t(31*scale>>24),1),4);le(f,binary32_bits(p.point.score,1),4);
        le(f,0xffffffffu,4);le(f,0,4);f.write(reinterpret_cast<const char*>(p.descriptor.data()),32);
    }
    require(bool(f),"Packet write failed");
}
void write_trace(const std::string& path,const Result& r,const Config& c) {
    std::filesystem::create_directories(path);
    std::ofstream manifest(path+"/trace.json");manifest<<"{\"schema\":2,\"byte_order\":\"little\",\"image_order\":\"row-major y,x\",\"levels\":[";
    for(size_t i=0;i<r.layers.size();++i) {
        const auto& l=r.layers[i];std::string prefix=path+"/L"+std::to_string(i);
        auto binary=[&](const std::string& name,const Image& im) {
            std::ofstream f(prefix+name,std::ios::binary);f.write(reinterpret_cast<const char*>(im.pixels.data()),std::streamsize(im.pixels.size()));require(bool(f),"Trace write");
        };
        binary("_pyramid.u8",l.image);binary("_fast.u8",l.score);binary("_gaussian.u8",l.blurred);
        // Diagnostic threshold gates share the raw FAST score; no new detector/NMS.
        Image high=l.score,low=l.score;
        for(size_t j=0;j<l.score.pixels.size();++j) {
            high.pixels[j]=l.score.pixels[j]>=c.threshold?l.score.pixels[j]:0;
            low.pixels[j]=l.score.pixels[j]>=c.low_threshold?l.score.pixels[j]:0;
        }
        binary("_fast_high.u8",high);binary("_fast_low.u8",low);
        auto points=[&](const std::string& name,const std::vector<Point>& ps) {
            std::ofstream f(prefix+name);f<<"index,x_effective,y_effective,response,tile\n";
            for(size_t j=0;j<ps.size();++j){auto p=ps[j];f<<j<<','<<p.x<<','<<p.y<<','<<p.score<<','<<p.tile<<'\n';}
        };
        points("_nms.csv",l.candidates);points("_grid.csv",l.selected);
        std::vector<Point> high_points,low_points;
        for(auto p:l.candidates) {
            if(p.score>=c.threshold)high_points.push_back(p);
            else if(p.score>=c.low_threshold)low_points.push_back(p);
        }
        points("_nms_high.csv",high_points);points("_nms_low.csv",low_points);
        std::ofstream origins(prefix+"_grid_thresholds.csv");
        origins<<"index,x_effective,y_effective,response,threshold_used\n";
        for(size_t j=0;j<l.selected.size();++j) {
            auto p=l.selected[j];origins<<j<<','<<p.x<<','<<p.y<<','<<p.score<<','<<(p.score>=c.threshold?c.threshold:c.low_threshold)<<'\n';
        }
        require(bool(origins),"Trace threshold origin write");
        std::ofstream moments_file(prefix+"_moments.csv"),descriptor_file(prefix+"_descriptors.u8",std::ios::binary);
        moments_file<<"index,x_layer,y_layer,m10,m01,angle_q16,bin\n";
        for(size_t j=0;j<l.features.size();++j) {
            auto p=l.features[j];moments_file<<j<<','<<p.point.x<<','<<p.point.y<<','<<p.m10<<','<<p.m01<<','<<p.angle_q16<<','<<p.bin<<'\n';
            descriptor_file.write(reinterpret_cast<const char*>(p.descriptor.data()),32);
        }
        if(i)manifest<<',';
        manifest<<"{\"level\":"<<i<<",\"width\":"<<l.image.width<<",\"height\":"<<l.image.height<<",\"scale_q24\":"<<l.scale_q24<<",\"budget\":"<<l.budget<<",\"candidates\":"<<l.candidates.size()<<",\"selected\":"<<l.selected.size()<<",\"cell_side\":"<<l.cell_side<<",\"cell_cols\":"<<l.cell_cols<<",\"cell_rows\":"<<l.cell_rows<<",\"empty_cells\":"<<l.empty_cells<<",\"fallback_cells\":"<<l.fallback_cells<<'}';
    }
    manifest<<"],\"angle_bins\":"<<c.angle_bins<<",\"dual_threshold\":"<<c.dual_threshold<<",\"grid_top_k\":"<<c.grid_top_k<<",\"threshold_high\":"<<c.threshold<<",\"threshold_low\":"<<c.low_threshold<<",\"fixed_fast\":"<<c.fixed_fast<<",\"grid\":"<<c.grid<<",\"blur\":"<<c.blur<<",\"points\":"<<r.ordered.size()<<",\"mono_left\":"<<r.mono_left<<"}\n";
    std::ofstream order(path+"/output_order.csv");order<<"record,level,x_layer,y_layer\n";
    for(size_t i=0;i<r.ordered.size();++i){auto p=r.ordered[i];order<<i<<','<<p.level<<','<<p.point.x<<','<<p.point.y<<'\n';}
    require(bool(manifest)&&bool(order),"Trace manifest write");
}
}
