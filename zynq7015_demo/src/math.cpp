#include "zslam/math.hpp"
#include <limits>

namespace zslam {
double reprojectionCost(const Camera &c,Pose p,const std::vector<Observation> &obs,double h){
    double cost=0;
    for(const auto &o:obs){V3 q=p.apply(o.xyz);if(q.z<=1e-6||!finite(q)){cost+=1e6;continue;}
        double e=distance(c.project(q),o.uv);cost+=e<h?e*e:h*(2*e-h);}
    return cost;
}
bool optimizePose(const Camera &c,const std::vector<Observation> &obs,Pose &pose,std::vector<unsigned> &inliers,unsigned minimum,int iterations){
    inliers.clear();if(obs.size()<minimum||!rigid(pose))return false;
    Pose estimate=pose;double cost=reprojectionCost(c,estimate,obs),lambda=1e-4;
    for(int iteration=0;iteration<iterations;iteration++){
        double h[36]={},b[6]={};unsigned used=0;double depth=0;
        for(const auto &o:obs){
            V3 p=estimate.apply(o.xyz);if(p.z<=1e-6||!finite(p))continue;
            V2 uv=c.project(p);double residual[2]={o.uv.x-uv.x,o.uv.y-uv.y};double e=std::hypot(residual[0],residual[1]);
            if(iteration>3&&e>25)continue;
            double w=e<=3?1.:3/e,iz=1/p.z,x=p.x*iz,y=p.y*iz;
            double j[2][6]={{c.fx*iz,0,-c.fx*x*iz,-c.fx*x*y,c.fx*(1+x*x),-c.fx*y},
                            {0,c.fy*iz,-c.fy*y*iz,-c.fy*(1+y*y),c.fy*x*y,c.fy*x}};
            // J^T W J is symmetric. Accumulate one triangle, retaining the
            // residual order, then mirror once instead of repeating 30 products.
            for(int r=0;r<6;r++){double weighted[2]={w*j[0][r],w*j[1][r]};
                for(int k=0;k<2;k++)b[r]+=weighted[k]*residual[k];
                for(int col=r;col<6;col++)for(int k=0;k<2;k++)h[r*6+col]+=weighted[k]*j[k][col];}
            depth+=p.z;used++;
        }
        if(used<minimum)return false;
        for(int r=1;r<6;r++)for(int col=0;col<r;col++)h[r*6+col]=h[col*6+r];
        for(int i=0;i<6;i++)h[i*6+i]+=lambda*(1+h[i*6+i]);
        double dx[6]={};if(!solve(h,b,dx,6))return false;
        V3 t{dx[0],dx[1],dx[2]},w{dx[3],dx[4],dx[5]};
        double factor=std::min(1.,.2/std::max(1e-12,norm(w)));
        factor=std::min(factor,.25*depth/used/std::max(1e-12,norm(t)));
        M3 dr=rotation(w*factor);Pose trial{dr*estimate.r,dr*estimate.t+t*factor};
        double next=reprojectionCost(c,trial,obs);
        if(next<=cost){estimate=trial;double improvement=cost-next;cost=next;lambda=std::max(1e-9,lambda*.3);if(improvement<1e-8)break;}
        else lambda=std::min(1e8,lambda*10);
    }
    for(unsigned i=0;i<obs.size();i++){V3 q=estimate.apply(obs[i].xyz);if(q.z>1e-6&&distance(c.project(q),obs[i].uv)<=4)inliers.push_back(i);}
    if(inliers.size()<minimum||inliers.size()*4<obs.size()||!rigid(estimate))return false;
    pose=estimate;return true;
}

namespace {
bool essential(const Camera &c,const std::vector<V2> &a,const std::vector<V2> &b,const std::vector<unsigned> &indices,M3 &e){
    if(indices.size()<8)return false;
    V2 ma{},mb{};
    for(unsigned i:indices){ma.x+=(a[i].x-c.cx)/c.fx;ma.y+=(a[i].y-c.cy)/c.fy;mb.x+=(b[i].x-c.cx)/c.fx;mb.y+=(b[i].y-c.cy)/c.fy;}
    double count=static_cast<double>(indices.size());ma.x/=count;ma.y/=count;mb.x/=count;mb.y/=count;
    double da=0,db=0;
    for(unsigned i:indices){da+=std::hypot((a[i].x-c.cx)/c.fx-ma.x,(a[i].y-c.cy)/c.fy-ma.y);db+=std::hypot((b[i].x-c.cx)/c.fx-mb.x,(b[i].y-c.cy)/c.fy-mb.y);}
    if(da<1e-8||db<1e-8)return false;
    double sa=std::sqrt(2.)*count/da,sb=std::sqrt(2.)*count/db,ata[81]={},vectors[81];
    for(unsigned i:indices){double x=sa*((a[i].x-c.cx)/c.fx-ma.x),y=sa*((a[i].y-c.cy)/c.fy-ma.y);
        double u=sb*((b[i].x-c.cx)/c.fx-mb.x),v=sb*((b[i].y-c.cy)/c.fy-mb.y),row[9]={u*x,u*y,u,v*x,v*y,v,x,y,1};
        for(int r=0;r<9;r++)for(int col=0;col<9;col++)ata[r*9+col]+=row[r]*row[col];}
    symmetricEigen(ata,vectors,9);int order[9];for(int i=0;i<9;i++)order[i]=i;
    std::sort(order,order+9,[&](int i,int j){return ata[i*9+i]<ata[j*9+j];});
    if(ata[order[1]*9+order[1]]<1e-11*std::max(1.,ata[order[8]*9+order[8]]))return false;
    M3 f=M3::zero();for(int i=0;i<9;i++)f.a[i]=vectors[i*9+order[0]];
    M3 ta{{sa,0,-sa*ma.x,0,sa,-sa*ma.y,0,0,1}},tb{{sb,0,-sb*mb.x,0,sb,-sb*mb.y,0,0,1}};
    f=transpose(tb)*f*ta;M3 u,v;V3 s;if(!svd3(f,u,v,s))return false;
    M3 rank=M3::zero();rank(0,0)=rank(1,1)=1;e=u*rank*transpose(v);return true;
}
double sampson(const Camera &c,M3 e,V2 a,V2 b){
    V3 x{(a.x-c.cx)/c.fx,(a.y-c.cy)/c.fy,1},y{(b.x-c.cx)/c.fx,(b.y-c.cy)/c.fy,1};
    V3 ex=e*x,ey=transpose(e)*y;double v=dot(y,ex),den=ex.x*ex.x+ex.y*ex.y+ey.x*ey.x+ey.y*ey.y;
    return den>1e-20?v*v/den:std::numeric_limits<double>::infinity();
}
unsigned nextRandom(unsigned &s){s=1664525u*s+1013904223u;return s;}
}
bool initializeTwoViews(const Camera &c,const std::vector<V2> &a,const std::vector<V2> &b,Pose &second,std::vector<unsigned> &valid,std::vector<V3> &points,unsigned seed){
    valid.clear();points.clear();if(a.size()!=b.size()||a.size()<40)return false;
    double threshold=9/(.25*(c.fx+c.fy)*(c.fx+c.fy));std::vector<unsigned> best;M3 best_e;
    for(int iteration=0;iteration<120;iteration++){
        std::vector<unsigned> sample;sample.reserve(8);
        while(sample.size()<8){unsigned i=nextRandom(seed)%static_cast<unsigned>(a.size());if(std::find(sample.begin(),sample.end(),i)==sample.end())sample.push_back(i);}
        M3 e;if(!essential(c,a,b,sample,e))continue;std::vector<unsigned> keep;
        for(unsigned i=0;i<a.size();i++)if(sampson(c,e,a[i],b[i])<threshold)keep.push_back(i);
        if(keep.size()>best.size()){best=std::move(keep);best_e=e;}
        if(best.size()*10>a.size()*9&&iteration>24)break;
    }
    if(best.size()<40||best.size()*2<a.size())return false;
    M3 refined;if(essential(c,a,b,best,refined))best_e=refined;
    M3 u,v;V3 singular;if(!svd3(best_e,u,v,singular))return false;
    M3 w{{0,-1,0,1,0,0,0,0,1}};unsigned runner_up=0;Pose result;
    for(int mode=0;mode<4;mode++){
        Pose p{u*(mode&1?transpose(w):w)*transpose(v),u.column(2)*(mode&2?-1.:1.)};
        if(det(p.r)<0){p.r=p.r*(-1);p.t=-p.t;}
        std::vector<unsigned> accepted;std::vector<V3> xyz;
        for(unsigned i:best){V3 x;if(triangulate(c,Pose{},p,a[i],b[i],x,1.0)){accepted.push_back(i);xyz.push_back(x);}}
        if(accepted.size()>valid.size()){runner_up=static_cast<unsigned>(valid.size());valid=std::move(accepted);points=std::move(xyz);result=p;}
        else runner_up=std::max(runner_up,static_cast<unsigned>(accepted.size()));
    }
    if(valid.size()<40||valid.size()*2<best.size()||runner_up>.85*valid.size()){valid.clear();points.clear();return false;}
    second=result;return rigid(second);
}
} // namespace zslam
