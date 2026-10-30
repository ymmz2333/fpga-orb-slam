"""The numerical gate must reject corruption that rank-only checks miss."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

script = Path(__file__).resolve().parents[1] / "scripts/evaluate_npu_gate.py"
spec = importlib.util.spec_from_file_location("evaluate_npu_gate", script)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class NumericalGateTests(unittest.TestCase):
    def setUp(self):
        self.reference = np.linspace(.1, 10, 2000).reshape(40, 50)

    def test_fp16_rounding_is_small(self):
        result = gate.evaluate(self.reference, self.reference.astype(np.float16))
        self.assertLess(result["normalized_rmse"], .03)
        self.assertGreater(result["spearman"], .98)

    def test_scale_error_cannot_hide_behind_perfect_rank(self):
        result = gate.evaluate(self.reference, self.reference * 1.3)
        self.assertGreater(result["normalized_rmse"], .03)
        self.assertGreater(result["spearman"], .98)

    def test_inverse_order_is_rejected(self):
        result = gate.evaluate(self.reference, -self.reference)
        self.assertLess(result["spearman"], 0)

    def test_nan_shape_and_flat_reference_are_invalid(self):
        for reference, output in [(self.reference, np.full(self.reference.shape, np.nan)),
                                  (self.reference, np.ones(3)),
                                  (np.ones(10), np.ones(10))]:
            with self.assertRaises(ValueError):
                gate.evaluate(reference, output)


if __name__ == "__main__":
    unittest.main()
