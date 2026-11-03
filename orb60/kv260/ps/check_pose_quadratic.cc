// Independent randomized comparison with the retained Eigen expression order.
#include <Eigen/Core>
#include "PoseQuadratic.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <random>
#include <cmath>
using A=Eigen::Matrix<double,2,6>;
using O=Eigen::Matrix2d;
using H=Eigen::Matrix<double,6,6>;
using B=Eigen::Matrix<double,6,1>;
using E=Eigen::Vector2d;
volatile double sink=0;
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    std::ofstream binary(argv[1],std::ios::binary);std::mt19937_64 rng(2607015);std::normal_distribution<double> normal;
    double worst=0;
    for(int n=0;n<20000;++n) {
        A a;O omega;E error;H h;B b;
        for(int i=0;i<12;++i)a.data()[i]=normal(rng)*std::pow(10.,n%9-4);
        for(int i=0;i<4;++i)omega.data()[i]=normal(rng);
        omega=(omega.transpose()*omega).eval();if(n%2)omega=O::Identity()*std::abs(normal(rng));
        for(int i=0;i<2;++i)error(i)=normal(rng)*100;
        for(int i=0;i<36;++i)h.data()[i]=normal(rng);
        for(int i=0;i<6;++i)b(i)=normal(rng);
        const double rho=n%3?std::abs(normal(rng))*.3:1.;O weighted=rho*omega;
        H reference=h;B br=b;
        reference.noalias()+=a.transpose()*weighted*a;
        br.noalias()-=rho*a.transpose()*omega*error;
        H initial=h;B initial_b=b;KvPose::accumulate(a,omega,weighted,error,rho,h,b);
        const double delta=std::max((h-reference).cwiseAbs().maxCoeff()/std::max(1.,reference.cwiseAbs().maxCoeff()),
                                    (b-br).cwiseAbs().maxCoeff()/std::max(1.,br.cwiseAbs().maxCoeff()));
        if(!std::isfinite(delta)||delta>1e-12)return 3;
        worst=std::max(worst,delta);
        if(n<256) {
            auto write=[&](const auto& m){binary.write(reinterpret_cast<const char*>(m.data()),sizeof(double)*m.size());};
            write(a);write(omega);write(error);binary.write(reinterpret_cast<const char*>(&rho),8);
            write(initial);write(initial_b);write(h);write(b);
        }
    }
    if(!binary)return 4;binary.close();
    A a=A::Random();O omega=O::Identity(),weighted=.3*omega;E e=E::Random();H h=H::Zero();B b=B::Zero();
    auto benchmark=[&](bool fast){auto t=std::chrono::steady_clock::now();
        for(int i=0;i<200000;++i) {
            a(0,0)=double(i%163+1)*.00001;
            if(fast)KvPose::accumulate(a,omega,weighted,e,.3,h,b);
            else {h.noalias()+=a.transpose()*weighted*a;b.noalias()-=.3*a.transpose()*omega*e;}
        }
        sink+=h.sum()+b.sum();return std::chrono::duration<double>(std::chrono::steady_clock::now()-t).count();};
    const double reference=benchmark(false),fast=benchmark(true);
    std::cout<<"{\"status\":\"QUADRATIC_EQUATIONS_PASS\",\"cases\":20000,\"max_normalized_error\":"<<worst
             <<",\"microbenchmark_reference_seconds\":"<<reference<<",\"microbenchmark_fast_seconds\":"<<fast<<"}\n";
}
