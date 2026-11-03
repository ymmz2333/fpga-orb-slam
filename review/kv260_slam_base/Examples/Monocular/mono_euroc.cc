/**
* This file is part of ORB-SLAM3
*
* Copyright (C) 2017-2021 Carlos Campos, Richard Elvira, Juan J. Gómez Rodríguez, José M.M. Montiel and Juan D. Tardós, University of Zaragoza.
* Copyright (C) 2014-2016 Raúl Mur-Artal, José M.M. Montiel and Juan D. Tardós, University of Zaragoza.
*
* ORB-SLAM3 is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
* License as published by the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* ORB-SLAM3 is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even
* the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License along with ORB-SLAM3.
* If not, see <http://www.gnu.org/licenses/>.
*/

#include<iostream>
#include<algorithm>
#include<fstream>
#include<chrono>
#include<vector>
#include<string>
#include<iomanip>

#include<opencv2/core/core.hpp>

#include<System.h>
#include<FeatureIO.h>
#include<FpgaReplayInput.h>
#include<OrbTelemetry.h>
#include<memory>

using namespace std;

void LoadImages(const string &strImagePath, const string &strPathTimes,
                vector<string> &vstrImages, vector<double> &vTimeStamps);

int main(int argc, char **argv)
{  
    // Preserve v1.0's headless default, while making the run condition explicit.
    bool bUseViewer = false, unpaced=false;
    string featureMode="native", featureDirectory, telemetryDirectory;
    bool telemetryRecord=false;
    vector<char*> positionalArguments;
    positionalArguments.push_back(argv[0]);
    for(int i = 1; i < argc; ++i)
    {
        const string argument(argv[i]);
        if(argument == "--no-viewer")
            bUseViewer = false;
        else if(argument == "--unpaced")
            unpaced=true;
        else if(argument == "--viewer")
            bUseViewer = true;
        else if(argument == "--telemetry-record") telemetryRecord=true;
        else if(argument == "--telemetry-dir") {
            if(i+1>=argc)return 1;telemetryDirectory=argv[++i];
        }
        else if(argument == "--feature-mode" || argument == "--feature-dir")
        {
            if(i+1>=argc) { cerr << "Missing option value: " << argument << endl; return 1; }
            if(argument=="--feature-mode") featureMode=argv[++i];
            else featureDirectory=argv[++i];
        }
        else
            positionalArguments.push_back(argv[i]);
    }
    argc = static_cast<int>(positionalArguments.size());
    positionalArguments.push_back(nullptr);
    argv = positionalArguments.data();

    if(argc < 5)
    {
        cerr << endl << "Usage: ./mono_euroc path_to_vocabulary path_to_settings path_to_sequence_folder_1 path_to_times_file_1 (path_to_image_folder_2 path_to_times_file_2 ... path_to_image_folder_N path_to_times_file_N) (trajectory_file_name) [--no-viewer|--viewer] [--feature-mode native|dump|inject|fpga|fpga-pipeline] [--unpaced] [--feature-dir DIR]" << endl;
        return 1;
    }

    ORB_SLAM3::FeatureIO::Configure(featureMode,featureDirectory);
    const int num_seq = (argc-3)/2;
    if(ORB_SLAM3::FeatureIO::PipelineActive()&&num_seq!=1) throw runtime_error("FPGA pipeline accepts one sequence per connection");
    cout << "num_seq = " << num_seq << endl;
    bool bFileName= (((argc-3) % 2) == 1);
    string file_name;
    if (bFileName)
    {
        file_name = string(argv[argc-1]);
        cout << "file name: " << file_name << endl;
    }

    // Load all sequences:
    int seq;
    vector< vector<string> > vstrImageFilenames;
    vector< vector<double> > vTimestampsCam;
    vector<int> nImages;

    vstrImageFilenames.resize(num_seq);
    vTimestampsCam.resize(num_seq);
    nImages.resize(num_seq);

    int tot_images = 0;
    for (seq = 0; seq<num_seq; seq++)
    {
        cout << "Loading images for sequence " << seq << "...";
        LoadImages(string(argv[(2*seq)+3]) + "/mav0/cam0/data", string(argv[(2*seq)+4]), vstrImageFilenames[seq], vTimestampsCam[seq]);
        cout << "LOADED!" << endl;

        nImages[seq] = vstrImageFilenames[seq].size();
        tot_images += nImages[seq];
    }

    // Vector for tracking time statistics
    vector<float> vTimesTrack;
    vTimesTrack.resize(tot_images);

    cout << endl << "-------" << endl;
    cout.precision(17);


    int fps = 20;
    float dT = 1.f/fps;
    // Create SLAM system. It initializes all system threads and gets ready to process frames.
    cout << "Viewer: " << (bUseViewer ? "enabled" : "disabled") << endl;
    ORB_SLAM3::System SLAM(argv[1],argv[2],ORB_SLAM3::System::MONOCULAR, bUseViewer);
    float imageScale = SLAM.GetImageScale();
    if(ORB_SLAM3::FeatureIO::PipelineActive()&&imageScale!=1.f) throw runtime_error("fixed FPGA image scale must be1");

    std::unique_ptr<ORB_SLAM3::OrbTelemetry> telemetry;
    if(!telemetryDirectory.empty()) telemetry.reset(new ORB_SLAM3::OrbTelemetry(telemetryDirectory,telemetryRecord));
    double t_resize = 0.f;
    double t_track = 0.f;
#ifdef REGISTER_TIMES
    // Keep buffered state output outside the measured TrackMonocular interval.
    ofstream featureFile("FeatureTimeStats.csv");
    ofstream mapFile("MapStateStats.csv");
    if(!mapFile) { cerr << "Cannot create MapStateStats.csv" << endl; return 2; }
    mapFile << "frame_index,map_id,relocalized\n";
    if(!featureFile) { cerr << "Cannot create FeatureTimeStats.csv" << endl; return 2; }
    featureFile << "frame_index,timestamp_ns,role,count,extractor_calls,read_ms,decode_ms,native_ms,dump_ms,auxiliary_ms,inliers\n";
    featureFile << setprecision(17);
    ofstream stateFile("TrackingStates.csv");
    if(!stateFile.is_open())
    {
        cerr << "Cannot create TrackingStates.csv" << endl;
        return 2;
    }
    stateFile << "frame_index,sequence_index,sequence_frame,timestamp_s,state_before,state_after\n";
    stateFile << setprecision(17);
    size_t stateFrameIndex = 0;
    int previousTrackingState = -1; // System is not ready before the first input.
#endif

    auto replayStart=std::chrono::steady_clock::now();
    for (seq = 0; seq<num_seq; seq++)
    {
        std::unique_ptr<ORB_SLAM3::FpgaReplayInput> input;
        if(ORB_SLAM3::FeatureIO::PipelineActive()) input.reset(new ORB_SLAM3::FpgaReplayInput(vstrImageFilenames[seq]));

        // Main loop
        cv::Mat im;
        int proccIm = 0;
        for(int ni=0; ni<nImages[seq]; ni++, proccIm++)
        {

            // Read image from file
            im = input ? input->get(size_t(ni)) : cv::imread(vstrImageFilenames[seq][ni],cv::IMREAD_UNCHANGED); //,CV_LOAD_IMAGE_UNCHANGED);
            double tframe = vTimestampsCam[seq][ni];

            if(im.empty())
            {
                cerr << endl << "Failed to load image at: "
                     <<  vstrImageFilenames[seq][ni] << endl;
                return 1;
            }

            if(imageScale != 1.f)
            {
#ifdef REGISTER_TIMES
    #ifdef COMPILEDWITHC11
                std::chrono::steady_clock::time_point t_Start_Resize = std::chrono::steady_clock::now();
    #else
                std::chrono::monotonic_clock::time_point t_Start_Resize = std::chrono::monotonic_clock::now();
    #endif
#endif
                int width = im.cols * imageScale;
                int height = im.rows * imageScale;
                cv::resize(im, im, cv::Size(width, height));
#ifdef REGISTER_TIMES
    #ifdef COMPILEDWITHC11
                std::chrono::steady_clock::time_point t_End_Resize = std::chrono::steady_clock::now();
    #else
                std::chrono::monotonic_clock::time_point t_End_Resize = std::chrono::monotonic_clock::now();
    #endif
                t_resize = std::chrono::duration_cast<std::chrono::duration<double,std::milli> >(t_End_Resize - t_Start_Resize).count();
                SLAM.InsertResizeTime(t_resize);
#endif
            }

            const string imageName=vstrImageFilenames[seq][ni];
            const size_t basename=imageName.find_last_of("/")+1;
            const uint64_t timestampNs=stoull(imageName.substr(basename,imageName.size()-basename-4));
            ORB_SLAM3::FeatureIO::Begin(timestampNs);

    #ifdef COMPILEDWITHC11
            std::chrono::steady_clock::time_point t1 = std::chrono::steady_clock::now();
    #else
            std::chrono::monotonic_clock::time_point t1 = std::chrono::monotonic_clock::now();
    #endif

            // Pass the image to the SLAM system
            // cout << "tframe = " << tframe << endl;
            auto currentTcw=SLAM.TrackMonocular(im,tframe); // TODO change to monocular_inertial

    #ifdef COMPILEDWITHC11
            std::chrono::steady_clock::time_point t2 = std::chrono::steady_clock::now();
    #else
            std::chrono::monotonic_clock::time_point t2 = std::chrono::monotonic_clock::now();
    #endif

#ifdef REGISTER_TIMES
            t_track = t_resize + std::chrono::duration_cast<std::chrono::duration<double,std::milli> >(t2 - t1).count();
            SLAM.InsertTrackTime(t_track);
            // GetTrackingState mirrors Tracking::mState after GrabImageMonocular.
            const int currentTrackingState = SLAM.GetTrackingState();
            const auto featureStats=ORB_SLAM3::FeatureIO::Stats();
            const int inliers=(previousTrackingState>=2 && previousTrackingState<=4 && currentTrackingState==2)
                ? SLAM.GetTrackingInliers() : -1;
            featureFile << stateFrameIndex << ',' << featureStats.timestamp_ns << ',' << featureStats.role << ','
                        << featureStats.count << ',' << featureStats.extractor_calls << ','
                        << featureStats.read_ms << ',' << featureStats.decode_ms << ',' << featureStats.native_ms << ','
                        << featureStats.dump_ms << ',' << featureStats.auxiliary_ms << ',' << inliers << '\n';
            mapFile << stateFrameIndex << ',' << SLAM.GetActiveMapId() << ','
                    << (SLAM.DidRelocalizeCurrentFrame() ? 1 : 0) << '\n';
            stateFile << stateFrameIndex++ << ',' << seq << ',' << ni << ',' << tframe
                      << ',' << previousTrackingState << ',' << currentTrackingState << '\n';
            previousTrackingState = currentTrackingState;
#endif

            double ttrack= std::chrono::duration_cast<std::chrono::duration<double> >(t2 - t1).count();

            vTimesTrack[ni]=ttrack;
            if(telemetry) telemetry->capture(SLAM,im,currentTcw,uint64_t(ni),timestampNs,
                ORB_SLAM3::FeatureIO::Stats(),ttrack*1000.,ni==nImages[seq]-1);

            // Wait to load the next frame
            double T=0;
            if(ni<nImages[seq]-1)
                T = vTimestampsCam[seq][ni+1]-tframe;
            else if(ni>0)
                T = tframe-vTimestampsCam[seq][ni-1];

            //std::cout << "T: " << T << std::endl;
            //std::cout << "ttrack: " << ttrack << std::endl;

            if(!unpaced && ttrack<T) {
                //std::cout << "usleep: " << (dT-ttrack) << std::endl;
                usleep((T-ttrack)*1e6); // 1e6
            }
        }

        if(input) input->finish();

        if(seq < num_seq - 1)
        {
            string kf_file_submap =  "./SubMaps/kf_SubMap_" + std::to_string(seq) + ".txt";
            string f_file_submap =  "./SubMaps/f_SubMap_" + std::to_string(seq) + ".txt";
            SLAM.SaveTrajectoryEuRoC(f_file_submap);
            SLAM.SaveKeyFrameTrajectoryEuRoC(kf_file_submap);

            cout << "Changing the dataset" << endl;

            SLAM.ChangeDataset();
        }

    }
#ifdef REGISTER_TIMES
    stateFile.close();
    featureFile.close();
    mapFile.close();
#endif
    const double replaySeconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-replayStart).count();
    cout<<"REPLAY_SUMMARY frames="<<tot_images<<" seconds="<<replaySeconds<<" fps="<<tot_images/replaySeconds<<endl;
    if(telemetry)telemetry->finish();
    // Stop all threads
    SLAM.Shutdown();
    SLAM.SaveMapDiagnostics("Diagnostics");

    // Save camera trajectory
    if (bFileName)
    {
        const string kf_file =  "kf_" + string(argv[argc-1]) + ".txt";
        const string f_file =  "f_" + string(argv[argc-1]) + ".txt";
        SLAM.SaveTrajectoryEuRoC(f_file);
        SLAM.SaveKeyFrameTrajectoryEuRoC(kf_file);
    }
    else
    {
        SLAM.SaveTrajectoryEuRoC("CameraTrajectory.txt");
        SLAM.SaveKeyFrameTrajectoryEuRoC("KeyFrameTrajectory.txt");
    }

    return 0;
}

void LoadImages(const string &strImagePath, const string &strPathTimes,
                vector<string> &vstrImages, vector<double> &vTimeStamps)
{
    ifstream fTimes;
    fTimes.open(strPathTimes.c_str());
    vTimeStamps.reserve(5000);
    vstrImages.reserve(5000);
    while(!fTimes.eof())
    {
        string s;
        getline(fTimes,s);
        if(!s.empty())
        {
            stringstream ss;
            ss << s;
            vstrImages.push_back(strImagePath + "/" + ss.str() + ".png");
            double t;
            ss >> t;
            vTimeStamps.push_back(t*1e-9);

        }
    }
}
