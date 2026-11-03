"""Package only a verified standalone DPU build; never loads hardware."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get("FPGA_PROJECT_ROOT", str(Path(__file__).resolve().parents[3])))
    job = args.job.resolve()
    subprocess.run([sys.executable, str(Path(__file__).with_name("check_dpu_only.py")), str(job), "--release"], check=True)
    manifest = json.loads((job / "release_manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("export_verified"):
        raise SystemExit("Verified bitstream export is required")
    entries = {"hardware/" + name: job / name for name in manifest["sha256"]}
    for name in ("release_manifest.json", "validation.json", "project_path.txt", "system_generated.tcl"):
        entries["hardware/" + name] = job / name
    if (job / "RESULT_ZH.md").exists():
        entries["RESULT_ZH.md"] = job / "RESULT_ZH.md"
    for path in sorted((job / "source_build").glob("*")):
        if path.is_file():
            entries["provenance/source_build/" + path.name] = path
    source = root / "orb60/kv260/pl"
    for name in ("dpu_only.tcl", "report_dpu_only.tcl", "refine_dpu_only.tcl", "export_dpu_only.tcl", "check_dpu_only.py", "run_dpu_only.ps1", "run_refine_dpu_only.ps1", "package_dpu_only.py"):
        entries["source/orb60/kv260/pl/" + name] = source / name
    for name in ("open_dpu_only.ps1", "open_dpu_only.tcl"):
        entries["source/orb60/kv260/pl/" + name] = source / name
    if (job / "refinement.json").exists():
        entries["provenance/refinement.json"] = job / "refinement.json"
    if (job / "prior_timing_attempts.json").exists():
        entries["provenance/prior_timing_attempts.json"] = job / "prior_timing_attempts.json"
        attempts = json.loads((job / "prior_timing_attempts.json").read_text(encoding="utf-8"))
        for attempt in attempts["attempts"]:
            previous = job.parent / attempt["job"]
            for name in ("validation.json", "timing_summary.rpt"):
                entries["provenance/" + previous.name + "/" + name] = previous / name
    entries["README_ZH.md"] = source / "DPU_ONLY_PLATFORM_ZH.md"
    entries["source/scripts/project_env.ps1"] = root / "scripts/project_env.ps1"
    entries["source/orb60/kv260/pl/prepare_unified_vendor.py"] = source / "prepare_unified_vendor.py"
    entries["provenance/DPU_PROVENANCE.json"] = root / "orb60/build/kv260_system/vendor_sources/DPU_PROVENANCE.json"
    model_dir = root / "orb60/build/kv260_system/depth_midas_qat/compiled"
    for name in ("midas_kv260_b4096.xmodel", "compilation.json", "target_profile.json", "placement.json", "arch.json"):
        entries["model/" + name] = model_dir / name
    entries["model/ps_operator_policy.json"] = model_dir.parent / "ps_operator_policy.json"
    hashes = {name: {"bytes": path.stat().st_size, "sha256": digest(path)} for name, path in sorted(entries.items())}
    payload = {"status": "HOST_STATIC_PASS_BOARD_UNTESTED", "job": job.name,
               "board_programmed": False, "ethernet_pipeline_implemented": False,
               "model_numerical_acceptance": manifest["model_binding"]["numerical_acceptance"],
               "user_visual_acceptance": manifest["model_binding"]["user_visual_acceptance"], "files": hashes}
    archive = job / "kv260_dpu_only_handoff.zip"
    if archive.exists():
        raise SystemExit("Refusing to overwrite a retained handoff archive")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        for name, path in sorted(entries.items()):
            out.write(path, name)
        out.writestr("MANIFEST.json", json.dumps(payload, indent=2) + "\n")
    with zipfile.ZipFile(archive) as check:
        bad = check.testzip()
        if bad:
            raise SystemExit("Archive CRC failure: " + bad)
        for name, item in hashes.items():
            if hashlib.sha256(check.read(name)).hexdigest() != item["sha256"]:
                raise SystemExit("Archive SHA256 mismatch: " + name)
    evidence = {"archive": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive),
                "files_verified": len(entries), "board_programmed": False}
    (job / "handoff_verified.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
