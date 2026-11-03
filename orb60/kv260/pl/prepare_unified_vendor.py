"""Fetch the exact official VAI 2.5 DPU TRD; never replace it with a stub."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
URL = "https://www.xilinx.com/bin/public/openDownload?filename=DPUCZDX8G.tar.gz"
SHA256 = "2888c035f73c907e29de1ae524e2caf4474b05a59ba30aeac3ebe2c818557603"


def digest(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download if the archive is absent")
    args = parser.parse_args()
    dest = ROOT / "orb60/build/kv260_system/vendor_sources"
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "DPUCZDX8G.tar.gz"
    if not archive.exists():
        if not args.download:
            raise SystemExit("Official DPU archive absent: rerun with --download")
        partial = archive.with_suffix(".gz.part")
        with urllib.request.urlopen(URL, timeout=90) as response, partial.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        if digest(partial) != SHA256:
            raise SystemExit("Official URL changed: downloaded archive hash mismatch; inspect before using")
        partial.replace(archive)
    if digest(archive) != SHA256:
        raise SystemExit("DPU archive hash mismatch")
    ip = dest / "dpu_trd/DPUCZDX8G/dpu_ip/DPUCZDX8G_v4_0_0"
    if not ip.exists():
        with tarfile.open(archive) as bundle:
            bundle.extractall(dest / "dpu_trd", filter="data")
    files = {
        str(p.relative_to(ip)).replace("\\", "/"): digest(p)
        for p in sorted(ip.rglob("*")) if p.is_file()
    }
    evidence = {
        "source_url": URL, "archive_sha256": SHA256,
        "archive_bytes": archive.stat().st_size,
        "official_release": "DPUCZDX8G TRD 4.0 / Vitis AI 2.5 / Vivado 2022.1 reference",
        "local_build_tool": "Vivado 2024.2; actual import/synthesis/route evidence required",
        "ip_vlnv": "xilinx.com:ip:dpuczdx8g:4.0", "ip_files_sha256": files,
        "changes_to_vendor_ip": [],
    }
    (dest / "DPU_PROVENANCE.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"DPU_VENDOR_HASH_VERIFIED {len(files)} IP files")


if __name__ == "__main__":
    main()
