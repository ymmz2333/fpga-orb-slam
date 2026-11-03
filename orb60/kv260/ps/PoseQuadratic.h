// Same small normal-equation products as retained g2o, without dynamic products.
#pragma once
namespace KvPose {
template<class Jacobian,class Information,class Error,class Hessian,class Vector>
inline void accumulate(const Jacobian& a,const Information& omega,const Information& weighted,
                       const Error& error,double rho,Hessian& h,Vector& b) {
    for(int i=0;i<6;++i) {
        const double a0=a(0,i),a1=a(1,i);
        const double p0=a0*weighted(0,0)+a1*weighted(1,0);
        const double p1=a0*weighted(0,1)+a1*weighted(1,1);
        const double q0=(rho*a0)*omega(0,0)+(rho*a1)*omega(1,0);
        const double q1=(rho*a0)*omega(0,1)+(rho*a1)*omega(1,1);
        b(i)-=q0*error(0)+q1*error(1);
        for(int j=0;j<6;++j)h(i,j)+=p0*a(0,j)+p1*a(1,j);
    }
}
}
