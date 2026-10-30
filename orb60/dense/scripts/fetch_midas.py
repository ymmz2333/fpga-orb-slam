"""Only invoked after the primary DA2 candidate fails the real NPU gate."""
import argparse
import concurrent.futures
import json
import tarfile
from pathlib import Path
from fetch_assets import fetch

p = argparse.ArgumentParser()
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
base = "https://github.com/isl-org/MiDaS/releases/download/v2_1/"
files = [(a.output / name, base + name) for name in
         ["model-small.onnx", "model-small-traced.pt", "midas_v21_small_256.pt"]]
MIDAS_REV = "94afff70fe0873c3af70355e5388e4d482bfc807"
EFFICIENT_REV = "771ce082b2ce6d033f55b3d47c1f77389ad3c180"
archives = [("midas-v21", "isl-org/MiDaS", MIDAS_REV),
            ("gen-efficientnet", "rwightman/gen-efficientnet-pytorch", EFFICIENT_REV)]
files += [(a.output / (name + ".tar.gz"), f"https://codeload.github.com/{repo}/tar.gz/{rev}")
          for name, repo, rev in archives]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    records = list(pool.map(fetch, files))
for name, repo, rev in archives:
    if not (a.output / name).exists():
        with tarfile.open(a.output / (name + ".tar.gz")) as archive:
            archive.extractall(a.output / "upstream", filter="data")
        (a.output / "upstream" / (repo.split('/')[1] + '-' + rev)).rename(a.output / name)
(a.output / "midas-assets.json").write_text(json.dumps(dict(
    model="MiDaS v2.1 Small", upstream_release="v2_1", files=records), indent=2) + "\n")
print(json.dumps(records, indent=2), flush=True)
