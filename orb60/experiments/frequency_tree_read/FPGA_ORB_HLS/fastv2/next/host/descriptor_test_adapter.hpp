#pragma once
#include "descriptor.hpp"
#include "next_backend.h"
#include <algorithm>
#include <cstring>
#include <vector>
/** Adapt the existing independent test to the new packed PL interface. */
static int pl_describe_for_test(const uint8_t* raw,const uint8_t* blur,int width,int height,
    const NextPoint* points,int count,int level,NextFeature* output,int capacity) {
    std::vector<uint64_t> raw_words(86400),blur_words(86400),point_words(512),features(8000);
    const size_t image_bytes=width>0 && width<=960 && height>0 && height<=720 ? size_t(width)*height : 0;
    if(raw && image_bytes) std::memcpy(raw_words.data(),raw,image_bytes);
    if(blur && image_bytes) std::memcpy(blur_words.data(),blur,image_bytes);
    if(points && count>0) std::memcpy(point_words.data(),points,size_t(std::min(count,256))*16);
    const int copied=std::max(0,std::min(capacity,256));
    if(output && copied) std::memcpy(features.data(),output,size_t(copied)*64);
    uint64_t stats[8]={};
    const int status=fastv2_descriptor_hls(raw_words.data(),blur_words.data(),point_words.data(),features.data(),
        stats,width,height,count,level,0,capacity);
    orb60::DescriptorStats counters;std::memcpy(&counters,stats,64);
    if(counters.version!=orb60::kDescriptorVersion || counters.status!=uint32_t(status) ||
        counters.completed>uint32_t(std::max(0,count)) || counters.feature_write_bytes!=counters.completed*64)
        throw std::runtime_error("Descriptor stats mismatch");
    if(output && copied) std::memcpy(output,features.data(),size_t(copied)*64);
    return status;
}
