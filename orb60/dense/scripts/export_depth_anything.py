"""Floating PC reference + static ONNX export, never production CPU inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", required=True, type=Path)
    p.add_argument("--samples", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--threads", type=int, default=6)
    a = p.parse_args()
    os.environ["XFORMERS_DISABLED"] = "1"
    sys.path.insert(0, str(a.assets / "depth-anything-v2"))
    import torch
    import numpy as np
    import onnx
    import onnxruntime as ort
    from depth_anything_v2.dpt import DepthAnythingV2
    torch.set_num_threads(a.threads)
    model = DepthAnythingV2(encoder="vits", features=64,
                           out_channels=[48, 96, 192, 384]).eval()
    weights = a.assets / "depth_anything_v2_vits.pth"
    model.load_state_dict(torch.load(str(weights), map_location="cpu", weights_only=True))
    a.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((a.samples / "samples.json").read_text())
    example = torch.from_numpy(np.load(a.samples / (manifest["frames"][0]["id"] + ".input.npy")))
    target = a.output / "depth_anything_v2_small_518x392.onnx"
    with torch.inference_mode():
        if not target.exists():
            torch.onnx.export(model, example, str(target), input_names=["image"],
                              output_names=["relative_inverse_depth"], opset_version=17,
                              do_constant_folding=True, dynamic_axes=None)
        onnx.checker.check_model(str(target))
        options = ort.SessionOptions()
        options.intra_op_num_threads = a.threads
        session = ort.InferenceSession(str(target), options, providers=["CPUExecutionProvider"])
        records = []
        for frame in manifest["frames"]:
            name = frame["id"]
            value = np.load(a.samples / (name + ".input.npy"))
            start = time.perf_counter()
            reference = model(torch.from_numpy(value)).numpy()
            exported = session.run(None, {"image": value})[0]
            error = float(np.max(np.abs(reference - exported)))
            if not np.isfinite(reference).all() or error > 0.002 * max(1., float(reference.max())):
                raise ValueError("ONNX export does not match official floating model: " + str(error))
            np.save(a.output / (name + ".reference.npy"), reference)
            records.append(dict(id=name, seconds=time.perf_counter() - start,
                                onnx_max_abs_error=error,
                                minimum=float(reference.min()), maximum=float(reference.max())))
            print("REFERENCE", name, records[-1], flush=True)
    report = dict(model="Depth-Anything-V2-Small", shape=[1, 3, 392, 518],
                  reference_backend="official PyTorch float32 on PC, validation only",
                  onnx_sha256=digest(target), weights_sha256=digest(weights), frames=records)
    (a.output / "reference.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
