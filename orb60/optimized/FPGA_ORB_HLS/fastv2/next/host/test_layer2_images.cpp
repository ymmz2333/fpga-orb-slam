#include "fastv2.hpp"
#include "image_test_reference.hpp"
#include <cstdlib>
extern "C" int next_test_layer2_image(const uint64_t*,uint64_t*,int,int);

int main(int argc,char** argv) {
    if (argc!=2) return 2;
    const bool resize=std::atoi(argv[1])!=0;
    using namespace next_image_test;
    const ImageCase* cases=resize ? kResizeCases : kGaussianCases;
    const int count=resize ? kResizeCaseCount : kGaussianCaseCount;
    for (int i=0; i<count; ++i) {
        const auto test=cases[i];
        const bool valid=test.level>=0 && test.level<(resize ? 7 : 8);
        const auto raw=valid ? pixels(test) : std::vector<uint8_t>();
        const auto ref=valid ? (resize ? next_image_test::resize(raw,test.level) : gaussian(raw,test.level)) : std::vector<uint8_t>();
        const auto source=pack(raw,false), expected=pack(ref,true);
        std::vector<uint64_t> actual(kPortWords,kPoison);
        const int status=next_test_layer2_image(source.data(),actual.data(),test.level,resize);
        if (!check(resize ? "LAYER2_RESIZE" : "LAYER2_GAUSSIAN",i,test,status,
            valid ? fastv2::kOk : fastv2::kInvalidArgument,actual,expected)) return 1;
    }
    std::cout<<"LAYER2_IMAGE_EXACT_PASS resize="<<resize<<" cases="<<count<<'\n';
    return 0;
}
