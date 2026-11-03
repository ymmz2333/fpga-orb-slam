"""Build a private XRT 2022.1 metadata utility; never installs or loads hardware.

The system utility can crash during static section registration.  The standalone
target explicitly places Section.cxx before every derived Section, as required
by the upstream CMakeLists.txt.  All vendor inputs remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--rapidjson", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--validate-existing", action="store_true", help="Inspect an existing identical private build; preserve its BUILD.json")
    args = parser.parse_args()
    if platform.machine() != "aarch64":
        raise ValueError("Run with the native KV260 compiler")
    source, rapid, out = args.source.resolve(), args.rapidjson.resolve(), args.output.resolve()
    provenance = json.loads((source.parent / "PROVENANCE.json").read_text())
    if provenance["commit"] != "ca4bdf101cd1d698377f5a7113d8583f709c2143":
        raise ValueError("Unexpected XRT source revision")
    for item in provenance["files"]:
        if sha(source / item["path"]) != item["sha256"]:
            raise ValueError("Vendor source changed: " + item["path"])
    if not (rapid / "rapidjson/document.h").is_file():
        raise ValueError("Private RapidJSON headers are required")
    rapid_provenance = rapid.parent / "PROVENANCE.json"
    for name, expected in json.loads(rapid_provenance.read_text())["headers"].items():
        if sha(rapid.parent / name.replace("\\", "/")) != expected:
            raise ValueError("RapidJSON header changed: " + name)
    if args.validate_existing:
        if not (out / "build/xclbinutil").is_file():
            raise ValueError("Completed private binary required for validation")
    else:
        out.mkdir(parents=True, exist_ok=False)
    tool = source / "src/runtime_src/tools/xclbinutil"
    files = [tool / "Section.cxx", *sorted(p for p in tool.glob("*.cxx") if p.name != "Section.cxx")]
    cmake = '''cmake_minimum_required(VERSION 3.16)
project(orb60_private_xclbinutil LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION OFF)
find_package(Boost REQUIRED COMPONENTS filesystem program_options system)
find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)
add_executable(xclbinutil
'''
    cmake += "".join('  "' + str(p) + '"\n' for p in files) + ")\n"
    cmake += 'target_include_directories(xclbinutil PRIVATE "' + str(source / "src/runtime_src/core/include") + '" "' + str(rapid) + '" /usr/include/xrt)\n'
    cmake += "target_compile_definitions(xclbinutil PRIVATE ENABLE_JSON_SCHEMA_VALIDATION)\n"
    cmake += "target_compile_options(xclbinutil PRIVATE -include cstdint)\n"
    cmake += "target_link_libraries(xclbinutil PRIVATE Boost::filesystem Boost::program_options Boost::system OpenSSL::Crypto Threads::Threads)\n"
    if args.validate_existing:
        if (out / "CMakeLists.txt").read_text() != cmake:
            raise ValueError("Existing build recipe differs")
    else:
        (out / "CMakeLists.txt").write_text(cmake)
    system = Path("/usr/bin/unwrapped/xclbinutil")
    before = sha(system)
    record = {"status": "RUNNING", "started": time.time(), "xrt_commit": provenance["commit"],
              "scope": "Private metadata tooling only; no XRT libraries, firmware or system files changed",
              "rapidjson_provenance_sha256": sha(rapid_provenance),
              "checker_sha256": sha(Path(__file__)),
              "system_utility_sha256_before": before,
              "ordered_sources": [str(p) for p in files], "reference_sha256": sha(args.reference)}
    try:
        if not args.validate_existing:
            with (out / "build.log").open("w") as log:
                for command in (["cmake", "-S", str(out), "-B", str(out / "build"), "-DCMAKE_BUILD_TYPE=Release"],
                                ["cmake", "--build", str(out / "build"), "-j2"]):
                    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = out / "build/xclbinutil"
        evidence = out / "validation_sections" if args.validate_existing else out
        if args.validate_existing:
            evidence.mkdir(exist_ok=False)
        info = subprocess.run([str(binary), "--input", str(args.reference.resolve()), "--info"],
                              capture_output=True, text=True, timeout=30)
        (evidence / "reference_info.log").write_text(info.stdout + info.stderr)
        if info.returncode or "IP_LAYOUT" not in info.stdout or "MEM_TOPOLOGY" not in info.stdout:
            raise RuntimeError("Reference metadata inspection failed")
        sections = {}
        # This official reference has eight sections and no CLOCK_FREQ_TOPOLOGY.
        # Require the four actual runtime sections, rather than inventing one.
        for name in ("IP_LAYOUT", "MEM_TOPOLOGY", "CONNECTIVITY", "EMBEDDED_METADATA"):
            dest = evidence / (name + (".xml" if name == "EMBEDDED_METADATA" else ".json"))
            fmt = "RAW" if name == "EMBEDDED_METADATA" else "JSON"
            call = subprocess.run([str(binary), "--input", str(args.reference.resolve()), "--dump-section", name + ":" + fmt + ":" + str(dest)],
                                  capture_output=True, text=True, timeout=30)
            (evidence / (name + ".log")).write_text(call.stdout + call.stderr)
            if call.returncode or not dest.is_file() or dest.stat().st_size == 0:
                raise RuntimeError("Section extraction failed: " + name)
            if fmt == "JSON":
                json.loads(dest.read_text())
            sections[name] = sha(dest)
        if sha(system) != before:
            raise RuntimeError("System utility unexpectedly changed")
        record.update(status="PRIVATE_TOOL_REFERENCE_SECTIONS_PASS", binary_sha256=sha(binary),
                      sections_sha256=sections, hardware_loaded=False, dpu_executed=False)
    except BaseException as error:
        record.update(status="FAILED", error=repr(error))
        raise
    finally:
        record["finished"] = time.time()
        name = "VALIDATION.json" if args.validate_existing else "BUILD.json"
        (out / name).write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: record[key] for key in ("status", "binary_sha256", "hardware_loaded", "dpu_executed")}))


if __name__ == "__main__":
    main()
