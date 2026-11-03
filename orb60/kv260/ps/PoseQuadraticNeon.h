// PS AArch64 SIMD for the same2x6 normal-equation products, with no FMA.
#pragma once
#if !defined(__aarch64__)
#error AArch64 FP64 NEON target required.
#endif
#include <arm_neon.h>
#include <cassert>
namespace KvPose {
template<class Jacobian,class Information,class Error,class Hessian,class Vector>
inline void accumulate(const Jacobian& a,const Information& omega,const Information& weighted,
                       const Error& error,double rho,Hessian& h,Vector& b) {
    static_assert(Jacobian::RowsAtCompileTime==2&&Jacobian::ColsAtCompileTime==6,"Fixed2x6 pose Jacobian required");
    static_assert(Hessian::RowsAtCompileTime==6&&Hessian::ColsAtCompileTime==6&&!Hessian::IsRowMajor,"Column-major6x6 Hessian required");
    assert(a.innerStride()==1&&a.outerStride()==(Jacobian::IsRowMajor?6:2));
    assert(h.innerStride()==1&&h.outerStride()==6&&b.innerStride()==1);
    alignas(16) double p0[6],p1[6];
    for(int i=0;i<6;i+=2) {
        float64x2_t a0,a1;
        if(Jacobian::IsRowMajor){a0=vld1q_f64(a.data()+i);a1=vld1q_f64(a.data()+6+i);}
        else {const auto pair=vld2q_f64(a.data()+2*i);a0=pair.val[0];a1=pair.val[1];}
        const auto p0v=vaddq_f64(vmulq_n_f64(a0,weighted(0,0)),vmulq_n_f64(a1,weighted(1,0)));
        const auto p1v=vaddq_f64(vmulq_n_f64(a0,weighted(0,1)),vmulq_n_f64(a1,weighted(1,1)));
        const auto r0=vmulq_n_f64(a0,rho),r1=vmulq_n_f64(a1,rho);
        const auto q0=vaddq_f64(vmulq_n_f64(r0,omega(0,0)),vmulq_n_f64(r1,omega(1,0)));
        const auto q1=vaddq_f64(vmulq_n_f64(r0,omega(0,1)),vmulq_n_f64(r1,omega(1,1)));
        const auto delta=vaddq_f64(vmulq_n_f64(q0,error(0)),vmulq_n_f64(q1,error(1)));
        vst1q_f64(b.data()+i,vsubq_f64(vld1q_f64(b.data()+i),delta));
        vst1q_f64(p0+i,p0v);vst1q_f64(p1+i,p1v);
    }
    for(int j=0;j<6;++j)for(int i=0;i<6;i+=2) {
        auto* destination=h.data()+6*j+i;
        const auto delta=vaddq_f64(vmulq_n_f64(vld1q_f64(p0+i),a(0,j)),vmulq_n_f64(vld1q_f64(p1+i),a(1,j)));
        vst1q_f64(destination,vaddq_f64(vld1q_f64(destination),delta));
    }
}
}
