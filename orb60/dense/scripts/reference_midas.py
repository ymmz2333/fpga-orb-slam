"""Check official MiDaS ONNX against its official TorchScript release on PC."""
import argparse
import json
from pathlib import Path
import time
import sys
import numpy as np
import torch
import onnx
import onnxruntime as ort
from export_depth_anything import digest

p = argparse.ArgumentParser()
p.add_argument("--assets", required=True, type=Path)
p.add_argument("--samples", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
torch.set_num_threads(6)
sys.path.insert(0, str(a.assets / "midas-v21"))
import midas.blocks
from midas.midas_net_custom import MidasNet_small

def local_backbone(use_pretrained, exportable=False):
    if use_pretrained:
        raise ValueError("Only the explicit official full MiDaS checkpoint is permitted")
    backbone = torch.hub.load(str(a.assets / "gen-efficientnet"), "tf_efficientnet_lite3",
                              source="local", pretrained=False, exportable=exportable)
    return midas.blocks._make_efficientnet_backbone(backbone)

midas.blocks._make_pretrained_efficientnet_lite3 = local_backbone
model = MidasNet_small(str(a.assets / "midas_v21_small_256.pt"), features=64,
                       backbone="efficientnet_lite3", exportable=True,
                       non_negative=True, blocks={"expand": True}).eval()
path = a.output / "midas_small_256.onnx"
manifest = json.loads((a.samples / "samples.json").read_text())
example = torch.from_numpy(np.load(a.samples / (manifest["frames"][0]["id"] + ".input.npy")))
# Re-export the official full checkpoint with its same-version eager source.
with torch.inference_mode():
    torch.onnx.export(model, example, str(path), input_names=["image"],
                      output_names=["relative_inverse_depth"], opset_version=17,
                      do_constant_folding=True, dynamic_axes=None)
onnx.checker.check_model(str(path))
options = ort.SessionOptions()
options.intra_op_num_threads = 6
session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
records = []
with torch.inference_mode():
    for frame in manifest["frames"]:
        name = frame["id"]
        value = np.load(a.samples / (name + ".input.npy"))
        start = time.perf_counter()
        reference = model(torch.from_numpy(value)).numpy()
        exported = session.run(None, {session.get_inputs()[0].name: value})[0]
        error = float(np.max(np.abs(reference.ravel() - exported.ravel())))
        if not np.isfinite(reference).all() or error > .002 * max(1., float(reference.max())):
            raise ValueError("Official ONNX/TorchScript mismatch: " + str(error))
        np.save(a.output / (name + ".reference.npy"), reference)
        records.append(dict(id=name, seconds=time.perf_counter()-start,
                            onnx_max_abs_error=error, minimum=float(reference.min()), maximum=float(reference.max())))
        print("REFERENCE", name, records[-1], flush=True)
report = dict(model="MiDaS-v2.1-Small", shape=[1, 3, 256, 256],
              reference_backend="official v2.1 eager checkpoint float32 on PC, validation only",
              onnx_sha256=digest(path), weights_sha256=digest(a.assets/"midas_v21_small_256.pt"), frames=records)
(a.output / "reference.json").write_text(json.dumps(report, indent=2) + "\n")
