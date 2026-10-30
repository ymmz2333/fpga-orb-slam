"""Download pinned official assets; no installation or system library changes."""
import argparse
import concurrent.futures
import hashlib
import json
import shutil
import tarfile
import time
import urllib.request
from pathlib import Path

RK_REV = "2c723177a94fac65cbc036d722907ddbc91980cf"
DA_REV = "a561b849ebae10a6f5ef49e26c83cbbcd36c71bf"
HF_REV = "03876f8651c73a60fe4c2c48294e09fcb6838fcf"
WHEEL = "rknn_toolkit2-2.5.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
UV_VERSION = "0.13.4"


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def fetch(item):
    target, url = item
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = target.with_name(target.name + ".part")
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ORB60-dense/1"})
                with urllib.request.urlopen(req, timeout=120) as src, tmp.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                tmp.replace(target)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return dict(file=str(target.name), url=url, bytes=target.stat().st_size,
                sha256=sha256(target))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    base = f"https://raw.githubusercontent.com/airockchip/rknn-toolkit2/{RK_REV}/"
    files = [(root / WHEEL, base + "rknn-toolkit2/packages/x86_64/" + WHEEL),
             (root / "requirements_cp310.txt", base + "rknn-toolkit2/packages/x86_64/requirements_cp310.txt"),
             (root / "uv-linux.tar.gz", f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"),
             (root / "librknnrt.so", base + "rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so"),
             (root / "rknn_api.h", base + "rknpu2/runtime/Linux/librknn_api/include/rknn_api.h"),
             (root / "depth-anything-v2.tar.gz", f"https://codeload.github.com/DepthAnything/Depth-Anything-V2/tar.gz/{DA_REV}"),
             (root / "depth_anything_v2_vits.pth", f"https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/{HF_REV}/depth_anything_v2_vits.pth")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, files))
    source = root / "depth-anything-v2"
    if not source.exists():
        with tarfile.open(root / "depth-anything-v2.tar.gz") as archive:
            archive.extractall(root / "upstream", filter="data")
        (root / "upstream" / ("Depth-Anything-V2-" + DA_REV)).rename(source)
    manifest = dict(rknn_revision=RK_REV, depth_anything_revision=DA_REV,
                    weights_revision=HF_REV, files=records)
    (root / "assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
