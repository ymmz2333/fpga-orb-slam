#pragma once
#include "math.hpp"
namespace zslam {
// Constant body twist: exp(scale * log(delta)), including translation's
// left-Jacobian coupling. Near-pi rotations have an ambiguous log axis and
// deliberately fall back to the last accepted pose. No matrix-entry scaling.
inline bool scaleRigidMotion(Pose delta,double scale,Pose &result){
    if(!rigid(delta)||!std::isfinite(scale)||scale<0||scale>8)return false;
    if(scale==0){result=Pose{};return true;}
    if(scale==1){result=delta;return true;}
    double theta=std::acos(std::clamp((delta.r(0,0)+delta.r(1,1)+delta.r(2,2)-1)*.5,-1.,1.));
    if(theta>pi-1e-4)return false;
    V3 antisymmetric{delta.r(2,1)-delta.r(1,2),delta.r(0,2)-delta.r(2,0),delta.r(1,0)-delta.r(0,1)};
    V3 omega=antisymmetric*(theta<1e-7?.5:theta/(2*std::sin(theta)));
    M3 k=skew(omega);double angle2=dot(omega,omega);
    double inverse_coefficient=angle2<1e-8?1./12+angle2/720:(1-.5*theta/std::tan(theta*.5))/angle2;
    V3 velocity=(M3{}+k*(-.5)+(k*k)*inverse_coefficient)*delta.t;
    V3 scaled=omega*scale;M3 w=skew(scaled);double a2=dot(scaled,scaled),a=std::sqrt(a2);
    double b=a2<1e-8?.5-a2/24+a2*a2/720:(1-std::cos(a))/a2;
    double c=a2<1e-8?1./6-a2/120+a2*a2/5040:(a-std::sin(a))/(a2*a);
    Pose candidate{rotation(scaled),(M3{}+w*b+(w*w)*c)*(velocity*scale)};
    if(!rigid(candidate))return false;result=candidate;return true;
}
} // namespace zslam
