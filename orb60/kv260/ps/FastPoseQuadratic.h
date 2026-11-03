// PS software specialization of the measured 2x6 unary-edge quadratic product.
// Residuals, Jacobians, Huber kernel, iterations and outlier gates are retained.
#pragma once
#include "PoseQuadratic.h"
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
        const auto& a=this->jacobianOplusXi();
        const auto& omega=this->_information;
        double weight=1.;
        if(this->robustKernel()) {
            Eigen::Vector3d rho;
            this->robustKernel()->robustify(this->chi2(),rho);weight=rho[1];
        }
        // Retained base_edge.h robustInformation uses rho[1]*information;
        // its rho[2] correction is disabled. Keep that exact selected model.
        typename Base::InformationType weighted=weight*omega;
        KvPose::accumulate(a,omega,weighted,this->_error,weight,from->A(),from->b());
#ifdef G2O_OPENMP
        from->unlockQuadraticForm();
#endif
    }
};
}
