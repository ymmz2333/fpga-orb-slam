/* Adapted from OpenCV 4.2.0; BSD-3-Clause. See LICENSE and provenance.json.
   Only cv::Mat wrappers removed; numerical P3P implementation unchanged. */
#ifndef P3P_H
#define P3P_H


#include <algorithm>

class p3p
{
 public:
  p3p(double fx, double fy, double cx, double cy);


  int solve(double R[4][3][3], double t[4][3],
            double mu0, double mv0,   double X0, double Y0, double Z0,
            double mu1, double mv1,   double X1, double Y1, double Z1,
            double mu2, double mv2,   double X2, double Y2, double Z2,
            double mu3, double mv3,   double X3, double Y3, double Z3,
            bool p4p);
  bool solve(double R[3][3], double t[3],
             double mu0, double mv0,   double X0, double Y0, double Z0,
             double mu1, double mv1,   double X1, double Y1, double Z1,
             double mu2, double mv2,   double X2, double Y2, double Z2,
             double mu3, double mv3,   double X3, double Y3, double Z3);

 private:
  void init_inverse_parameters();
  int solve_for_lengths(double lengths[4][3], double distances[3], double cosines[3]);
  bool align(double M_start[3][3],
             double X0, double Y0, double Z0,
             double X1, double Y1, double Z1,
             double X2, double Y2, double Z2,
             double R[3][3], double T[3]);

  bool jacobi_4x4(double * A, double * D, double * U);

  double fx, fy, cx, cy;
  double inv_fx, inv_fy, cx_fx, cy_fy;
};

#endif // P3P_H
