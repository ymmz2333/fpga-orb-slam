#pragma once
#include <opencv2/core.hpp>
#include <opencv2/features2d.hpp>
#include <vector>
int originalExtract(const cv::Mat&, int, float, int, int, int, std::vector<cv::KeyPoint>&, cv::Mat&);
void originalDescribeAt(const cv::Mat&, std::vector<cv::KeyPoint>, cv::Mat&);
