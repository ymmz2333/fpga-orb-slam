#ifndef ZSLAM_VIDEO_PORT_H
#define ZSLAM_VIDEO_PORT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* External camera/HDMI drivers implement this contract. No pins/addresses assumed.
 * acquire returns 1=frame, 0=end, -1=error. Release only after PL completion.
 * Pixels are immutable tightly packed 960x720 GRAY8, stride 960, same calibration.
 * timestamp_ns is integer CLOCK_MONOTONIC time. Dropped sequences retain gaps.
 * A DMA producer must complete cache/coherency ownership before acquire returns.
 */
struct zslam_camera_frame {const uint8_t *pixels;size_t bytes;uint32_t width,height,stride;uint64_t sequence,timestamp_ns,lease;};
struct zslam_camera_port {void *context;int (*acquire)(void*,struct zslam_camera_frame*);void (*release)(void*,uint64_t lease);};
/* present is blocking until the RGB565 buffer may be reused, including DMA reads.
 * The sink owns mode setting/HDMI clocking/VDMA/CDC and vblank synchronization.
 * It must not retain this buffer after returning. No frame rate inferred here.
 */
struct zslam_display_port {void *context;int (*present_rgb565)(void*,const uint16_t*,uint32_t width,uint32_t height,uint32_t stride_bytes,uint64_t sequence);};
#ifdef __cplusplus
}
#endif
#endif
