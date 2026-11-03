// PS float32 ReLU for the four explicitly reviewed MiDaS boundaries.
#include <vart/op_imp.h>
#include <cstdint>
#include "approved_relu.hpp"

namespace {
class Relu final : public vart::experimental::OpImpBase {
 public:
  Relu(const xir::Op* op, xir::Attrs* attrs) : OpImpBase(op, attrs) {
    CHECK_EQ(op->get_type(), "relu");
    bool approved = false;
    for (const auto* name : kv260_relu_names) approved |= op->get_name() == name;
    CHECK(approved) << "ReLU is outside the model-bound PS policy";
    const auto input_type = op->get_input_op("input", 0)->get_output_tensor()->get_data_type();
    const auto output_type = op->get_output_tensor()->get_data_type();
    CHECK(input_type == xir::DataType(xir::DataType::FLOAT, 32));
    CHECK(output_type == input_type);
  }
  int calculate(vart::simple_tensor_buffer_t<float> output,
                vart::simple_tensor_buffer_t<float> input) {
    CHECK(output.tensor->get_shape() == input.tensor->get_shape());
    CHECK(output.data != nullptr && input.data != nullptr);
    const auto count = input.tensor->get_element_num();
    for (std::int32_t i = 0; i < count; ++i) {
      const float value = input.data[i];
      output.data[i] = value < 0.0f ? 0.0f : value;
    }
    return 0;
  }
};
}
extern "C" const char* kv260_ps_relu_model_sha256() { return kv260_relu_model_sha256; }
DEF_XIR_OP_IMP(Relu)
