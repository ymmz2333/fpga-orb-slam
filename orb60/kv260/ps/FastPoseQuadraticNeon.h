// Same edge residual/Jacobian/Huber semantics; only FP64 accumulation uses SIMD.
#pragma once
#include "PoseQuadraticNeon.h"
namespace KvPose {
template<class Base> class Edge:public Base {
public:
    EIGEN_MAKE_ALIGNED_OPERATOR_NEW
    void constructQuadraticForm() override {
        auto* from=static_cast<g2o::VertexSE3Expmap*>(this->_vertices[0]);
        if(from->fixed())return;
#ifdef G2O_OPENMP
        from->lockQuadraticForm();
#endif
        const auto& a=this->jacobianOplusXi();const auto& omega=this->_information;
        double weight=1.;
        if(this->robustKernel()) {Eigen::Vector3d rho;this->robustKernel()->robustify(this->chi2(),rho);weight=rho[1];}
        typename Base::InformationType weighted=weight*omega;
        KvPose::accumulate(a,omega,weighted,this->_error,weight,from->A(),from->b());
#ifdef G2O_OPENMP
        from->unlockQuadraticForm();
#endif
    }
};
}
