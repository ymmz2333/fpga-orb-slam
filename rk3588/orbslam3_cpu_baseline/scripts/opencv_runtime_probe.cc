#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/features2d.hpp>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char** argv)
{
    if (argc > 1 && std::string(argv[1]) == "parser")
    {
        cv::CommandLineParser parser(argc, argv, "{ help h | | help }");
        std::cout << "PARSER_CONSTRUCTED" << std::endl;
        parser.has("help");
        std::cout << "PARSER_LOOKUP_COMPLETE" << std::endl;
        return 0;
    }
    cv::Mat image(480, 752, CV_8UC1);
    cv::RNG random(3588);
    random.fill(image, cv::RNG::UNIFORM, 0, 256);
    cv::GaussianBlur(image, image, cv::Size(5, 5), 1.0);
    std::vector<cv::KeyPoint> keypoints;
    cv::Mat descriptors;
    cv::ORB::create(1000)->detectAndCompute(image, cv::noArray(), keypoints, descriptors);
    if (keypoints.empty() || descriptors.rows != static_cast<int>(keypoints.size()) || descriptors.cols != 32)
        throw std::runtime_error("ORB descriptor output failed the shape check");
    if (!cv::imwrite("opencv_probe.png", image))
        throw std::runtime_error("PNG writing failed");
    cv::Mat restored = cv::imread("opencv_probe.png", cv::IMREAD_GRAYSCALE);
    if (restored.size() != image.size() || cv::norm(image, restored, cv::NORM_INF) != 0)
        throw std::runtime_error("PNG roundtrip differs");
    std::cout << "OPENCV_IMAGE_ORB_PROBE_PASS version=" << CV_VERSION << std::endl;
    return 0;
}
