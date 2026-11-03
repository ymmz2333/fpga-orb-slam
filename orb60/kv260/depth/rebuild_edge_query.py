"""Explicitly rebuild the edge register reader, independent of board clock skew."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if platform.machine() != "aarch64":
        raise ValueError("Native AArch64 compiler required")
    root, out = a.root.resolve(), a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    build = root / "build_vai25/library/usefultools"
    recipe = build / "CMakeFiles/tools_extra_ops.dir"
    flags = {}
    for line in (recipe / "flags.make").read_text().splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            flags[key] = shlex.split(value)
    if "-DENABLE_XRT" not in flags["CXX_DEFINES"] or "-DENABLE_CLOUD" in flags["CXX_DEFINES"]:
        raise ValueError("CMake must select the actual edge XRT API first")
    source = root / "vendor/vai25_runtime_source/src/Vitis-AI-Library/usefultools/src/read_register.cpp"
    header = source.with_name("xrt_xcl_read.hpp")
    original_obj = "CMakeFiles/tools_extra_ops.dir/src/read_register.cpp.o"
    old_sha = sha(build / original_obj)
    link = shlex.split((recipe / "link.txt").read_text())
    if link.count(original_obj) != 1:
        raise ValueError("Unexpected native link recipe")
    module_name = link[link.index("-o") + 1]
    link[link.index("-o") + 1] = str(out / module_name)
    link[link.index(original_obj)] = str(out / "read_register.o")
    compile_call = [link[0], *flags["CXX_DEFINES"], *flags["CXX_INCLUDES"], *flags["CXX_FLAGS"],
                    "-c", str(source), "-o", str(out / "read_register.o")]
    record = {"status": "RUNNING", "source_sha256": sha(source), "header_sha256": sha(header),
              "original_object_sha256": old_sha, "commands": [compile_call, link],
              "reason": "Board wall clock reset makes old objects newer than changed compiler flags; force the exact source compilation"}
    try:
        with (out / "build.log").open("w") as log:
            subprocess.run(compile_call, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(link, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
        if sha(build / original_obj) != old_sha:
            raise ValueError("Retained object changed")
        installed = root / "runtime_vai25/lib/python" / module_name
        record["installed_before_sha256"] = sha(installed)
        shutil.copy2(installed, out / (module_name + ".before"))
        shutil.copy2(out / module_name, installed)
        record.update(status="NATIVE_EDGE_REGISTER_READER_REBUILT", installed_sha256=sha(installed),
                      dpu_executed=False, system_libraries_changed=False)
    except BaseException as error:
        record.update(status="FAILED", error=repr(error))
        raise
    finally:
        (out / "RESULT.json").write_text(json.dumps(record, indent=2) + "\n")
    print(record["status"])


if __name__ == "__main__":
    main()
