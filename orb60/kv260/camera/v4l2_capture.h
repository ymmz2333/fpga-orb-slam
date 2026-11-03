#pragma once
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
struct orb_camera_frame {
    uint64_t timestamp_ns,dequeued_ns,sequence_gaps;
    uint32_t capture_sequence,kernel_flags;
};
struct orb_camera_info {
    uint32_t width,height,fourcc,stride,sizeimage,colorspace,ycbcr_encoding,quantization,transfer_function;
    uint32_t interval_numerator,interval_denominator,buffers;
    uint64_t frames,sequence_gaps,first_timestamp_ns,last_timestamp_ns;
};
void *orb_camera_open(const char*,uint32_t,unsigned,char*,size_t);
int orb_camera_close(void*);
int orb_camera_info(void*,struct orb_camera_info*);
int orb_camera_read(void*,uint8_t*,size_t,uint8_t*,size_t,struct orb_camera_frame*,unsigned,char*,size_t);
int orb_camera_profile(void*,char*,size_t);
int orb_camera_next(void*,uint8_t*,size_t,uint8_t*,size_t,char*,size_t,unsigned);
#ifdef __cplusplus
}
#endif
