#include "Thirdparty/DBoW2/DBoW2/FORB.h"
#include "BowDistanceNeon.h"
int DBoW2::FORB::distance(const TDescriptor& a,const TDescriptor& b) {
    return KvBow::distance(a,b);
}
