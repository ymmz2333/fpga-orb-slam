// Private RKNN C-API process. No CPU neural-network implementation exists here.
#include "rknn_api.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/resource.h>

namespace fs = std::filesystem;
void check(int rc, const char* operation) {
    if (rc != RKNN_SUCC) throw std::runtime_error(std::string(operation) + ": " + std::to_string(rc));
}
std::vector<char> read(const fs::path& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("Cannot read " + path.string());
    auto size = f.tellg();
    if (size <= 0) throw std::runtime_error("Empty file " + path.string());
    std::vector<char> result(static_cast<size_t>(size));
    f.seekg(0);
    if (!f.read(result.data(), result.size())) throw std::runtime_error("Short read");
    return result;
}
struct Context {
    rknn_context value = 0;
    ~Context() { if (value) rknn_destroy(value); }
};
int main(int argc, char** argv) {
    try {
        if (argc != 5) throw std::runtime_error("usage: dense_npu_worker model.rknn inputs-directory names.txt output-directory");
        const fs::path inputs = argv[2], output = argv[4];
        fs::create_directories(output);
        auto model = read(argv[1]);
        Context ctx;
        check(rknn_init(&ctx.value, model.data(), model.size(), RKNN_FLAG_COLLECT_PERF_MASK, nullptr), "rknn_init");
        check(rknn_set_core_mask(ctx.value, RKNN_NPU_CORE_0_1_2), "rknn_set_core_mask");
        rknn_sdk_version version{};
        check(rknn_query(ctx.value, RKNN_QUERY_SDK_VERSION, &version, sizeof(version)), "SDK version");
        std::cout << "RKNN_RUNTIME=" << version.api_version << " DRIVER=" << version.drv_version << std::endl;
        rknn_input_output_num counts{};
        check(rknn_query(ctx.value, RKNN_QUERY_IN_OUT_NUM, &counts, sizeof(counts)), "tensor counts");
        if (counts.n_input != 1 || counts.n_output != 1) throw std::runtime_error("Expected one input/output");
        rknn_tensor_attr in{}, out{};
        check(rknn_query(ctx.value, RKNN_QUERY_INPUT_ATTR, &in, sizeof(in)), "input attributes");
        check(rknn_query(ctx.value, RKNN_QUERY_OUTPUT_ATTR, &out, sizeof(out)), "output attributes");
        std::ofstream report(output / "worker.json");
        report << "{\"runtime\":\"" << version.api_version << "\",\"driver\":\"" << version.drv_version
               << "\",\"core_mask\":7,\"input_elements\":" << in.n_elems
               << ",\"output_elements\":" << out.n_elems << ",\"frames\":[";
        const bool streaming=std::string(argv[3])=="-";
        std::ifstream file;
        if (!streaming) file.open(argv[3]);
        if (!streaming && !file) throw std::runtime_error("Cannot open input list");
        std::istream& list=streaming?std::cin:file;
        std::string name;
        size_t count = 0;
        while (std::getline(list, name)) {
            if (!name.empty() && name.back() == '\r') name.pop_back();
            if (name.empty()) continue;
            if (name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != std::string::npos)
                throw std::runtime_error("Invalid frame name");
            auto data = read(inputs / (name + ".input.f32"));
            if (data.size() != in.n_elems * sizeof(float)) throw std::runtime_error("Input tensor size mismatch");
            rknn_input input{};
            input.buf = data.data(); input.size = data.size();
            input.type = RKNN_TENSOR_FLOAT32; input.fmt = RKNN_TENSOR_NCHW;
            const auto start = std::chrono::steady_clock::now();
            check(rknn_inputs_set(ctx.value, 1, &input), "rknn_inputs_set");
            check(rknn_run(ctx.value, nullptr), "rknn_run");
            rknn_output result{};
            result.want_float = 1;
            check(rknn_outputs_get(ctx.value, 1, &result, nullptr), "rknn_outputs_get");
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            if (result.size != out.n_elems * sizeof(float)) {
                rknn_outputs_release(ctx.value, 1, &result);
                throw std::runtime_error("Output tensor size mismatch");
            }
            bool finite = true;
            auto values = static_cast<const float*>(result.buf);
            for (uint32_t i = 0; i < out.n_elems; ++i) finite &= std::isfinite(values[i]);
            if (!finite) {
                rknn_outputs_release(ctx.value, 1, &result);
                throw std::runtime_error("Nonfinite NPU output");
            }
            std::ofstream binary(output / (name + ".output.f32"), std::ios::binary);
            binary.write(static_cast<const char*>(result.buf), result.size);
            bool written = binary.good();
            check(rknn_outputs_release(ctx.value, 1, &result), "rknn_outputs_release");
            if (!written) throw std::runtime_error("Output write failed");
            rknn_perf_run perf{};
            check(rknn_query(ctx.value, RKNN_QUERY_PERF_RUN, &perf, sizeof(perf)), "run performance");
            if (perf.run_duration <= 0) throw std::runtime_error("Missing hardware execution time");
            if (!count) {
                rknn_perf_detail detail{};
                check(rknn_query(ctx.value, RKNN_QUERY_PERF_DETAIL, &detail, sizeof(detail)), "operator placement");
                if (!detail.perf_data || !detail.data_len) throw std::runtime_error("Missing operator profile");
                std::ofstream profile(output / "operator-profile.txt", std::ios::binary);
                profile.write(detail.perf_data, detail.data_len);
            }
            if (count++) report << ',';
            report << "{\"id\":\"" << name << "\",\"seconds\":" << elapsed
                   << ",\"hardware_run_us\":" << perf.run_duration << '}';
            report.flush();
            std::cout << "NPU_FRAME " << name << " seconds=" << elapsed << " hardware_us=" << perf.run_duration << std::endl;
        }
        if (!count) throw std::runtime_error("No input frames");
        rknn_mem_size memory{};
        check(rknn_query(ctx.value, RKNN_QUERY_MEM_SIZE, &memory, sizeof(memory)), "NPU memory");
        rusage resources{};
        getrusage(RUSAGE_SELF, &resources);
        report << "],\"peak_rss_kib\":" << resources.ru_maxrss << ",\"npu_weight_bytes\":"
               << memory.total_weight_size << ",\"npu_internal_bytes\":" << memory.total_internal_size
               << ",\"npu_dma_allocated_bytes\":" << memory.total_dma_allocated_size
               << ",\"status\":\"COMPLETED_REQUIRES_ACCURACY_GATE\"}\n";
        if (!report.good()) throw std::runtime_error("Report write failed");
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "NPU_WORKER_FAILED " << e.what() << std::endl;
        return 1;
    }
}
