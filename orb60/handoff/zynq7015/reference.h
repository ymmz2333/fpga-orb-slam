/* Small portable PS-side map/render helpers. Does not depend on Qt or OpenGL. */
#ifndef ORB60_HANDOFF_REFERENCE_H
#define ORB60_HANDOFF_REFERENCE_H
#include <stdint.h>
#include <stddef.h>
int orb60_load_f32_xyz(const char *path,float *xyz,size_t capacity,size_t *count);
unsigned orb60_hamming256(const uint8_t a[32],const uint8_t b[32]);
/* One query vs a packed map descriptor array; strict 4/5 ratio and first-index ties. */
int orb60_match256(const uint8_t query[32],const uint8_t *train,size_t count,unsigned maximum,unsigned *index,unsigned *distance);
/* Rcw and tcw are row-major world->camera, fx/fy/cx/cy are in pixels. */
int orb60_project(const float xyz[3],const double rcw[9],const double tcw[3],
                  const double intrinsics[4],double uv[2]);
void orb60_gray_rgb565(const uint8_t *gray,uint16_t *pixels,unsigned width,unsigned height);
void orb60_marker_rgb565(uint16_t *pixels,unsigned width,unsigned height,int x,int y,uint16_t color);
/* Both endpoints must be inside the framebuffer (project/clip before calling). */
int orb60_line_rgb565(uint16_t *pixels,unsigned width,unsigned height,int x0,int y0,int x1,int y1,uint16_t color);
/* Draw original-layer centers scaled to 960x720; count and byte length are checked. */
int orb60_overlay_records_rgb565(uint16_t *pixels,unsigned width,unsigned height,const uint8_t *records,size_t bytes,unsigned count);
#endif
