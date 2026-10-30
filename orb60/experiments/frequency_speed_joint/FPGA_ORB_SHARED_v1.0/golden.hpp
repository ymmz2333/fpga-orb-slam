// GPL-3.0-or-later: ORB-SLAM3-derived selection and standard ORB pattern.
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>
#ifndef ORB_DEFAULT_LEVELS
#define ORB_DEFAULT_LEVELS 8
#endif
#ifndef ORB_DEFAULT_FEATURES
#define ORB_DEFAULT_FEATURES 1000
#endif
#ifndef ORB_MAX_WIDTH
#define ORB_MAX_WIDTH 1920
#endif
#ifndef ORB_MAX_HEIGHT
#define ORB_MAX_HEIGHT 1080
#endif
#ifndef ORB_MAX_FEATURES
#define ORB_MAX_FEATURES 10000
#endif
namespace orb_golden {
struct Image {
    int width=0,height=0;
    std::vector<uint8_t> pixels;
    Image()=default;
    Image(int w,int h):width(w),height(h),pixels(size_t(w)*size_t(h)) {}
    uint8_t& at(int x,int y) { return pixels.at(size_t(y)*size_t(width)+size_t(x)); }
    uint8_t at(int x,int y) const { return pixels.at(size_t(y)*size_t(width)+size_t(x)); }
};
struct Config {
    int levels=ORB_DEFAULT_LEVELS,features=ORB_DEFAULT_FEATURES;
    uint32_t scale_num=6,scale_den=5;
    int threshold=20,low_threshold=7,angle_bins=32;
    bool fixed_fast=true,grid=true,blur=true,box2=false,box_half_up=false;
    bool dual_threshold=true,counts_only=false;
    int grid_top_k=1;
    int overlap_left=0,overlap_right=1000;
};
struct Point { int x=0,y=0,score=0,tile=0; };
struct Feature {
    Point point;
    int level=0,bin=0;
    int32_t m10=0,m01=0;
    uint32_t angle_q16=0;
    std::array<uint8_t,32> descriptor{};
};
struct Layer {
    Image image,blurred,score;
    std::vector<Point> candidates,selected;
    std::vector<Feature> features;
    int budget=0,cell_side=0,cell_cols=0,cell_rows=0,empty_cells=0,fallback_cells=0;
    uint64_t scale_q24=0;
};
struct Result { std::vector<Layer> layers; std::vector<Feature> ordered; int mono_left=0; };
int64_t round_even(int64_t value,int64_t divisor);
uint64_t isqrt(uint64_t n);
uint32_t binary32_bits(int64_t numerator,uint64_t denominator);
int reflect101(int p,int size);
Image resize_linear(const Image&,int w,int h);
Image gaussian7(const Image&);
Image fast_scores(const Image&);
std::vector<Point> tiled_candidates(const Image&,const Config&);
std::vector<Point> select_grid(const std::vector<Point>&,int w,int h,int budget,Layer&,const Config* config=nullptr);
std::vector<int> budgets(const Config&);
std::pair<int32_t,int32_t> moments(const Image&,int x,int y);
uint32_t angle_q16(int32_t m10,int32_t m01);
int quantize(uint32_t angle,int bins);
Feature describe(const Image&,const Image&,Point,int level,int bins);
Result extract(const Image&,const Config&,const Result* prepared=nullptr);
Image read_pgm(const std::string&);
void write_pgm(const std::string&,const Image&);
void write_packet(const std::string&,const Result&,const Config&,int width,int height,uint64_t ns,int role);
void write_trace(const std::string&,const Result&,const Config&);
}
