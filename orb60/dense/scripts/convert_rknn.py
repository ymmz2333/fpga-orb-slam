"""FP16 RK3588 compilation. Full compiler placement output is retained by caller."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from rknn.api import RKNN


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--onnx", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    rknn = None
    start = time.perf_counter()
    status = dict(status="RUNNING", target="rk3588", dtype="float16", quantized=False)
    report = a.output.with_suffix(".conversion.json")
    try:
        rknn = RKNN(verbose=True)
        rknn.config(target_platform="rk3588", float_dtype="float16", optimization_level=3)
        code = rknn.load_onnx(model=str(a.onnx))
        if code != 0:
            raise RuntimeError("load_onnx failed: " + str(code))
        code = rknn.build(do_quantization=False)
        if code != 0:
            raise RuntimeError("FP16 build failed: " + str(code))
        code = rknn.export_rknn(str(a.output))
        if code != 0:
            raise RuntimeError("export_rknn failed: " + str(code))
        h = hashlib.sha256()
        with a.output.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        status.update(status="COMPILED_NOT_BOARD_VERIFIED", sha256=h.hexdigest())
    except Exception as e:
        status.update(status="FAILED", error=str(e))
        raise
    finally:
        status["seconds"] = time.perf_counter() - start
        report.write_text(json.dumps(status, indent=2) + "\n")
        if rknn is not None:
            rknn.release()


if __name__ == "__main__":
    main()
