#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <vector>

namespace zslam {
constexpr double pi = 3.14159265358979323846;
struct V2 { double x=0,y=0; };
struct V3 {
    double x=0,y=0,z=0;
    double &operator[](int i) { return i==0?x:(i==1?y:z); }
    double operator[](int i) const { return i==0?x:(i==1?y:z); }
};
inline V3 operator+(V3 a,V3 b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
inline V3 operator-(V3 a,V3 b){return {a.x-b.x,a.y-b.y,a.z-b.z};}
inline V3 operator-(V3 a){return {-a.x,-a.y,-a.z};}
inline V3 operator*(V3 a,double s){return {a.x*s,a.y*s,a.z*s};}
inline V3 operator/(V3 a,double s){return a*(1/s);}
inline double dot(V3 a,V3 b){return a.x*b.x+a.y*b.y+a.z*b.z;}
inline V3 cross(V3 a,V3 b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
inline double norm(V3 a){return std::sqrt(dot(a,a));}
inline V3 unit(V3 a){double n=norm(a);return n>1e-15?a/n:V3{};}
inline bool finite(V3 a){return std::isfinite(a.x)&&std::isfinite(a.y)&&std::isfinite(a.z);}
inline double distance(V2 a,V2 b){return std::hypot(a.x-b.x,a.y-b.y);}
struct M3 {
    double a[9]={1,0,0,0,1,0,0,0,1};
    double &operator()(int r,int c){return a[r*3+c];}
    double operator()(int r,int c)const{return a[r*3+c];}
    static M3 zero(){M3 m;for(double &v:m.a)v=0;return m;}
    V3 column(int c)const{return {a[c],a[3+c],a[6+c]};}
    void column(int c,V3 v){a[c]=v.x;a[3+c]=v.y;a[6+c]=v.z;}
};
inline M3 transpose(M3 a){M3 b;for(int r=0;r<3;r++)for(int c=0;c<3;c++)b(r,c)=a(c,r);return b;}
inline V3 operator*(M3 a,V3 b){return {dot({a.a[0],a.a[1],a.a[2]},b),dot({a.a[3],a.a[4],a.a[5]},b),dot({a.a[6],a.a[7],a.a[8]},b)};}
inline M3 operator*(M3 a,M3 b){M3 v=M3::zero();for(int r=0;r<3;r++)for(int c=0;c<3;c++)for(int k=0;k<3;k++)v(r,c)+=a(r,k)*b(k,c);return v;}
inline M3 operator*(M3 a,double b){for(double &v:a.a)v*=b;return a;}
inline M3 operator+(M3 a,M3 b){for(int i=0;i<9;i++)a.a[i]+=b.a[i];return a;}
inline double det(M3 a){return dot(a.column(0),cross(a.column(1),a.column(2)));}
inline M3 skew(V3 v){M3 m=M3::zero();m(0,1)=-v.z;m(0,2)=v.y;m(1,0)=v.z;m(1,2)=-v.x;m(2,0)=-v.y;m(2,1)=v.x;return m;}
inline M3 rotation(V3 w){double n=norm(w);M3 k=skew(w);if(n<1e-8)return M3{}+k+(k*k)*.5;return M3{}+k*(std::sin(n)/n)+(k*k)*((1-std::cos(n))/(n*n));}
struct Pose {
    M3 r;V3 t;
    V3 apply(V3 p)const{return r*p+t;}
    Pose inverse()const{M3 q=transpose(r);return {q,q*(-t)};}
    V3 center()const{return transpose(r)*(-t);}
};
inline Pose operator*(Pose a,Pose b){return {a.r*b.r,a.r*b.t+a.t};}
inline bool rigid(Pose p){M3 q=transpose(p.r)*p.r;double e=0;for(int r=0;r<3;r++)for(int c=0;c<3;c++)e+=std::abs(q(r,c)-(r==c));return finite(p.t)&&std::isfinite(e)&&e<1e-5&&std::abs(det(p.r)-1)<1e-5;}

// Small fixed-bound solvers keep the target independent of OpenCV/Eigen/GUI libraries.
inline bool solve(double *a,double *b,double *x,int n){
    for(int k=0;k<n;k++){
        int pivot=k;for(int i=k+1;i<n;i++)if(std::abs(a[i*n+k])>std::abs(a[pivot*n+k]))pivot=i;
        if(!std::isfinite(a[pivot*n+k])||std::abs(a[pivot*n+k])<1e-12)return false;
        for(int j=k;j<n;j++)std::swap(a[k*n+j],a[pivot*n+j]);std::swap(b[k],b[pivot]);
        for(int i=k+1;i<n;i++){double v=a[i*n+k]/a[k*n+k];for(int j=k;j<n;j++)a[i*n+j]-=v*a[k*n+j];b[i]-=v*b[k];}
    }
    for(int i=n-1;i>=0;i--){double s=b[i];for(int j=i+1;j<n;j++)s-=a[i*n+j]*x[j];x[i]=s/a[i*n+i];if(!std::isfinite(x[i]))return false;}
    return true;
}
inline void symmetricEigen(double *a,double *vectors,int n){
    std::fill(vectors,vectors+n*n,0.);for(int i=0;i<n;i++)vectors[i*n+i]=1;
    for(int sweep=0;sweep<64;sweep++){
        double off=0;
        for(int p=0;p<n;p++)for(int q=p+1;q<n;q++){
            double apq=a[p*n+q];off=std::max(off,std::abs(apq));
            if(std::abs(apq)<1e-14*(1+std::abs(a[p*n+p])+std::abs(a[q*n+q])))continue;
            double tau=(a[q*n+q]-a[p*n+p])/(2*apq),t=std::copysign(1.,tau)/(std::abs(tau)+std::hypot(1.,tau));
            double c=1/std::sqrt(1+t*t),s=t*c,app=a[p*n+p],aqq=a[q*n+q];
            a[p*n+p]=app-t*apq;a[q*n+q]=aqq+t*apq;a[p*n+q]=a[q*n+p]=0;
            for(int k=0;k<n;k++)if(k!=p&&k!=q){double u=a[k*n+p],v=a[k*n+q];a[k*n+p]=a[p*n+k]=c*u-s*v;a[k*n+q]=a[q*n+k]=s*u+c*v;}
            for(int k=0;k<n;k++){double u=vectors[k*n+p],v=vectors[k*n+q];vectors[k*n+p]=c*u-s*v;vectors[k*n+q]=s*u+c*v;}
        }
        if(off<1e-13)break;
    }
}
inline bool svd3(M3 a,M3 &u,M3 &v,V3 &singular){
    M3 normal=transpose(a)*a;double ev[9];symmetricEigen(normal.a,ev,3);
    int order[3]={0,1,2};std::sort(order,order+3,[&](int i,int j){return normal(i,i)>normal(j,j);});
    for(int c=0;c<3;c++){v.column(c,{ev[order[c]],ev[3+order[c]],ev[6+order[c]]});singular[c]=std::sqrt(std::max(0.,normal(order[c],order[c])));}
    if(singular.y<1e-12)return false;
    V3 x=unit(a*v.column(0)),y=a*v.column(1);y=unit(y-x*dot(x,y));
    if(norm(y)<.5)return false;
    u.column(0,x);u.column(1,y);u.column(2,cross(x,y));
    v.column(2,cross(v.column(0),v.column(1)));return true;
}
struct Camera {
    int width=960,height=720;
    double fx=910.072021484375,fy=914.093994140625,cx=485.52301025390625,cy=336.7179870605469;
    std::array<double,5> d{{-.005940999835729599,.0551609992980957,-.006093999836593866,.003192000091075897,0}};
    V2 undistort(V2 raw)const{
        double xd=(raw.x-cx)/fx,yd=(raw.y-cy)/fy,x=xd,y=yd;
        for(int i=0;i<10;i++){double r2=x*x+y*y,rad=1+d[0]*r2+d[1]*r2*r2+d[4]*r2*r2*r2;if(std::abs(rad)<1e-9)break;
            double nx=(xd-2*d[2]*x*y-d[3]*(r2+2*x*x))/rad,ny=(yd-d[2]*(r2+2*y*y)-2*d[3]*x*y)/rad;x=nx;y=ny;}
        return {fx*x+cx,fy*y+cy};
    }
    V3 ray(V2 uv)const{return unit({(uv.x-cx)/fx,(uv.y-cy)/fy,1});}
    V2 project(V3 p)const{return {fx*p.x/p.z+cx,fy*p.y/p.z+cy};}
};
inline bool triangulate(const Camera &c,Pose a,Pose b,V2 ua,V2 ub,V3 &p,double minimum_angle=.7){
    V3 x=transpose(a.r)*c.ray(ua),y=transpose(b.r)*c.ray(ub),ca=a.center(),cb=b.center(),w=ca-cb;
    double xy=std::clamp(dot(x,y),-1.,1.),den=1-xy*xy;
    if(den<1e-10||std::acos(xy)*180/pi<minimum_angle)return false;
    double s=(xy*dot(y,w)-dot(x,w))/den,t=(dot(y,w)-xy*dot(x,w))/den;
    if(s<=0||t<=0)return false;p=(ca+x*s+cb+y*t)*.5;
    V3 pa=a.apply(p),pb=b.apply(p);
    return finite(p)&&pa.z>1e-5&&pb.z>1e-5&&distance(c.project(pa),ua)<3&&distance(c.project(pb),ub)<3;
}
struct Observation {V3 xyz;V2 uv;unsigned feature=0,landmark=0;};
double reprojectionCost(const Camera&,Pose,const std::vector<Observation>&,double threshold=4.);
bool optimizePose(const Camera&,const std::vector<Observation>&,Pose&,std::vector<unsigned>&,unsigned minimum=15,int iterations=10);
bool robustPose(const Camera&,const std::vector<Observation>&,Pose&,std::vector<unsigned>&,unsigned minimum=15,unsigned seed=1729);
bool initializeTwoViews(const Camera&,const std::vector<V2>&,const std::vector<V2>&,Pose&,std::vector<unsigned>&,std::vector<V3>&,unsigned seed=1729);
} // namespace zslam
