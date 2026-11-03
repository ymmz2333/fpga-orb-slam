// PS-only adapter around the retained fixed-map matching/PnP implementation.
#include "zslam/slam.hpp"
#include "zslam/formats.hpp"
#include "zslam/filesystem.hpp"
#include "zslam/bridge_wire.hpp"
#include <chrono>
#include <iostream>
#include <netdb.h>

namespace {
zslam::Config fixedConfig() {
    zslam::Config config;
    config.mapping = false;
    config.max_points = zslam::handoff_max_points;
    config.max_keyframes = zslam::handoff_max_keyframes;
    return config;
}

std::string geometryDigest(const zslam::Slam& slam) {
    // Seen counters may change; world point IDs and geometry must stay fixed.
    std::ostringstream text;
    text << std::setprecision(17);
    for (const auto& p : slam.points())
        text << p.id << ',' << p.xyz.x << ',' << p.xyz.y << ',' << p.xyz.z << '\n';
    return demo::sha256(demo::bytes(text.str()));
}

std::string statusJson(const zslam::Status& s) {
    std::ostringstream out;
    out << std::setprecision(17)
        << "{\"source_frame_id\":" << s.frame << ",\"timestamp_ns\":" << s.timestamp_ns
        << ",\"mode\":\"fixed_map_localization\",\"mapping\":false,\"cpu_orb_calls\":0"
        << ",\"state\":" << demo::jsonQuote(zslam::stateName(s.state))
        << ",\"pose_valid\":" << (s.pose_valid ? "true" : "false")
        << ",\"features\":" << s.features << ",\"matches\":" << s.matches
        << ",\"inliers\":" << s.inliers << ",\"points\":" << s.points
        << ",\"keyframes\":" << s.keyframes << ",\"track_ms\":" << s.track_ms
        << ",\"map_ms\":" << s.map_ms << ",\"pose_twc\":[";
    auto pose = s.pose_valid ? s.tcw.inverse() : zslam::Pose{};
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        if (r || c) out << ',';
        out << (r == 3 ? double(c == 3) : (c == 3 ? pose.t[r] : pose.r(r,c)));
    }
    out << "]}";
    return out.str();
}

struct Journal {
    std::string root;
    zslam::TrajectoryWriter trajectory;
    std::ofstream diagnostics;
    uint64_t count = 0, valid = 0;
    Journal(const std::string& path) : root(path), trajectory(path + "/trajectory.csv"),
        diagnostics(path + "/frames.csv") {
        diagnostics << "source_frame_id,timestamp_ns,pose_valid,state,features,matches,inliers,points,keyframes,track_ms,map_ms,cpu_orb_calls\n"
                    << std::setprecision(17);
    }
    std::string append(const zslam::Status& s) {
        if (s.mapping || s.new_points || s.map_ms != 0 || (s.pose_valid && !zslam::rigid(s.tcw)))
            throw std::runtime_error("Fixed-map geometry/mapping contract violated");
        trajectory.append(s);
        diagnostics << s.frame << ',' << s.timestamp_ns << ',' << s.pose_valid << ','
                    << zslam::stateName(s.state) << ',' << s.features << ',' << s.matches
                    << ',' << s.inliers << ',' << s.points << ',' << s.keyframes
                    << ',' << s.track_ms << ',' << s.map_ms << ",0\n";
        auto json = statusJson(s);
        std::ofstream status(root + "/latest.json.part");
        status << json << '\n'; status.close();
        if (!status || !diagnostics) throw std::runtime_error("Localization journal write failed");
        zslam::fs::rename(root + "/latest.json.part", root + "/latest.json");
        ++count; valid += s.pose_valid;
        return json;
    }
    void finish(const std::string& before, const std::string& after) {
        trajectory.finish(); diagnostics.close();
        if (!diagnostics || !count || before != after)
            throw std::runtime_error("Localization drain/fixed geometry check failed");
        std::ofstream report(root + "/LOCALIZATION.json");
        report << "{\"status\":\"COMPLETED\",\"frames\":" << count
               << ",\"valid_poses\":" << valid << ",\"cpu_orb_calls\":0,\"mapping\":false,"
               << "\"geometry_sha256_before\":\"" << before << "\",\"geometry_sha256_after\":\""
               << after << "\"}\n";
        report.close();
        if (!report) throw std::runtime_error("Localization completion report failed");
    }
};

void makeOutput(const std::string& path) {
    if (zslam::fs::exists(path)) throw std::runtime_error("Fresh localization output required");
    zslam::fs::create_directories(path);
}

void stream(zslam::Slam& slam, const zslam::Camera& camera, const std::string& camera_file,
            const std::string& host, const std::string& port, Journal& journal) {
    if (host != "127.0.0.1") throw std::runtime_error("KV260 producer must be local");
    const auto camera_bytes = demo::readFile(camera_file,4096);
    const auto hash = demo::sha256(camera_bytes);
    addrinfo hint{}, *list = nullptr; hint.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host.c_str(),port.c_str(),&hint,&list)) throw std::runtime_error("Local producer lookup failed");
    int fd = -1;
    for (auto* p = list; p; p = p->ai_next) {
        fd = socket(p->ai_family,p->ai_socktype,p->ai_protocol);
        if (fd < 0) continue;
        if (!connect(fd,p->ai_addr,p->ai_addrlen)) break;
        close(fd); fd = -1;
    }
    freeaddrinfo(list);
    if (fd < 0) throw std::runtime_error("Local producer connection failed");
    demo::Connection peer(fd); peer.timeout(120);
    peer.send(demo::response(demo::Hello,hash));
    auto hello = peer.receive();
    if (hello.kind != demo::Hello || demo::string(hello.body) != hash + "\n" + demo::profile + "\n" + demo::string(camera_bytes))
        throw std::runtime_error("Local producer calibration/profile mismatch");
    uint64_t session = 0, last_frame = 0, last_stamp = 0;
    zslam::RecordDecodeCache cache;
    for (;;) {
        auto p = peer.receive();
        if (p.kind == demo::End) {
            if (!journal.count || p.session != session || p.frame != last_frame || p.stamp != last_stamp)
                throw std::runtime_error("Localization drain identity mismatch");
            demo::Packet ack; ack.kind = demo::Ack; ack.session = session; ack.frame = last_frame; ack.stamp = last_stamp;
            peer.send(ack); break;
        }
        if (p.kind != demo::Frame || !p.session || !p.stamp || p.flags & ~demo::color_expected || p.count > 1000 ||
            p.body.size() != demo::image_bytes + 128 + p.count * 64 + 1024 ||
            (journal.count && (p.session != session || p.frame <= last_frame || p.stamp <= last_stamp)) ||
            demo::crc32(p.body.data(),demo::image_bytes) != p.aux)
            throw std::runtime_error("Invalid local PL frame identity/CRC");
        session = p.session; last_frame = p.frame; last_stamp = p.stamp;
        auto frame = zslam::decodeRecords(p.body.data() + demo::image_bytes + 128,p.count*64,p.frame,p.stamp,camera,&cache);
        auto json = journal.append(slam.process(std::move(frame)));
        demo::Packet ack; ack.kind = demo::Ack; ack.session = session; ack.frame = p.frame; ack.stamp = p.stamp;
        ack.body = demo::bytes(json); peer.send(ack);
    }
}
}

int main(int argc, char** argv) {
    try {
        if (argc < 2) throw std::runtime_error("Usage: fixed_map_kv260 import CAMERA EXPORT NEW_MAP | replay CAMERA MAP CAPTURE NEW_OUTPUT | stream CAMERA MAP 127.0.0.1 PORT NEW_OUTPUT");
        const std::string mode = argv[1];
        if ((mode == "import" && argc != 5) || (mode == "replay" && argc != 6) ||
            (mode == "stream" && argc != 7) || (mode != "import" && mode != "replay" && mode != "stream"))
            throw std::runtime_error("Invalid fixed-map command arguments");
        auto camera = zslam::readCamera(argv[2]);
        zslam::Slam slam(camera,fixedConfig());
        if (mode == "import") {
            slam.importHandoff(argv[3]); slam.setMapping(false); slam.save(argv[4]);
            zslam::Slam check(camera,fixedConfig()); check.load(argv[4]);
            if (slam.points().empty() || geometryDigest(slam) != geometryDigest(check))
                throw std::runtime_error("Serialized map round-trip changed geometry");
            std::cout << "KV260_FIXED_MAP_IMPORT_ROUNDTRIP_PASS points=" << slam.points().size() << '\n';
            return 0;
        }
        slam.load(argv[3]); slam.setMapping(false);
        if (slam.points().empty()) throw std::runtime_error("Empty fixed localization map");
        const auto before = geometryDigest(slam);
        const std::string output = argv[argc-1]; makeOutput(output); Journal journal(output);
        if (mode == "stream") stream(slam,camera,argv[2],argv[4],argv[5],journal);
        else {
            zslam::Replay replay(argv[4],camera); zslam::Frame frame;
            while (replay.next(frame)) journal.append(slam.process(std::move(frame)));
        }
        journal.finish(before,geometryDigest(slam));
        std::cout << "KV260_FIXED_MAP_COMPLETED frames=" << journal.count << " valid=" << journal.valid << " cpu_orb=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "KV260_LOCALIZATION_FAILED: " << error.what() << '\n'; return 1;
    }
}
