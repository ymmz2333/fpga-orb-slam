#!/usr/bin/env python3
"""Bounded diagnostic: rebuild just the parser TU and repeat correctness probes."""
import csv
import json
import os
import pathlib
import shlex
import subprocess

root = pathlib.Path(__file__).resolve().parent.parent
entries = json.loads((root / "build/opencv/compile_commands.json").read_text())
entry = next(item for item in entries if item["file"].endswith("/command_line_parser.cpp"))
environment = os.environ.copy()
environment["LD_LIBRARY_PATH"] = str(root / "build/opencv/lib") + ":" + str(root / "install/lib")
variants = [("original", []), ("debug_only", ["-g"]),
            ("frame_pointer_only", ["-fno-omit-frame-pointer"])]
output = root / "logs/parser-compiler-probes.csv"
with output.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["variant", "run", "program", "exit_code"])
    for label, flags in variants:
        with (root / "logs" / ("parser-compile-" + label + ".log")).open("w") as log:
            subprocess.run(shlex.split(entry["command"]) + flags, cwd=entry["directory"], stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(["cmake", "--build", str(root / "build/opencv"), "--target", "opencv_core", "--parallel", "2"], stdout=log, stderr=subprocess.STDOUT, check=True)
        programs = [("version", [str(root / "build/opencv/bin/opencv_version")]),
                    ("parser", [str(root / "runtime/opencv_runtime_probe"), "parser"]),
                    ("image_orb", [str(root / "runtime/opencv_runtime_probe")])]
        for run in range(1, 6):
            for name, arguments in programs:
                with (root / "logs" / ("parser-%s-%s-%d.log" % (label, name, run))).open("w") as log:
                    result = subprocess.run(arguments, cwd=root / "runtime", env=environment, stdout=log, stderr=subprocess.STDOUT)
                writer.writerow([label, run, name, result.returncode])
                stream.flush()
                print(label, run, name, result.returncode, flush=True)
print("Diagnostic CSV:", output, flush=True)
