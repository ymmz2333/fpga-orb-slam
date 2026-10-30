#!/usr/bin/env python3
"""Record real board environment facts as CSV and a bounded diagnostic log."""
import csv
import argparse
import datetime
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "logs"
OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("--stem", choices=("environment", "environment-final"), default="environment")
stem = parser.parse_args().stem
rows = []
logs = []


def record(section, item, value, unit=""):
    rows.append((section, item, str(value), unit))


def command(args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logs.append("$ " + " ".join(args) + "\n" + result.stdout + "exit=" + str(result.returncode))
    return result.stdout.strip(), result.returncode


record("snapshot", "utc", datetime.datetime.now(datetime.timezone.utc).isoformat())
for line in pathlib.Path("/etc/os-release").read_text().splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        record("os", key, value.strip('"'))
record("kernel", "uname", command(["uname", "-a"])[0])
for executable in ("gcc", "g++", "cmake", "git", "python3"):
    output, rc = command([executable, "--version"]) if shutil.which(executable) else ("not installed", 127)
    record("tool", executable, output.splitlines()[0] if output else "no output")
    record("tool_exit", executable, rc)
for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
    key, value = line.split(":", 1)
    if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
        record("memory", key, value.strip().split()[0], "KiB")
disk = shutil.disk_usage(ROOT)
for key in ("total", "used", "free"):
    record("disk", key, getattr(disk, key), "bytes")
command(["free", "-h"])
command(["swapon", "--show"])
command(["df", "-h", "/", str(ROOT)])
command(["lscpu"])
for cpu in sorted(pathlib.Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
    for relative in ("cpu_capacity", "regs/identification/midr_el1", "topology/core_id", "topology/physical_package_id"):
        path = cpu / relative
        if path.exists():
            record(cpu.name, relative, path.read_text().strip())
    midr_path = cpu / "regs/identification/midr_el1"
    if midr_path.exists():
        part = (int(midr_path.read_text().strip(), 16) >> 4) & 0xFFF
        record(cpu.name, "cpu_model", {0xD05: "Cortex-A55", 0xD0B: "Cortex-A76"}.get(part, "part_0x%x" % part))
for policy in sorted(pathlib.Path("/sys/devices/system/cpu/cpufreq").glob("policy*")):
    for key in ("affected_cpus", "scaling_governor", "scaling_available_governors", "cpuinfo_max_freq", "scaling_cur_freq"):
        path = policy / key
        if path.exists():
            record(policy.name, key, path.read_text().strip(), "kHz" if "freq" in key else "")
for zone in sorted(pathlib.Path("/sys/class/thermal").glob("thermal_zone*")):
    record(zone.name, "type", (zone / "type").read_text().strip())
    record(zone.name, "temp", (zone / "temp").read_text().strip(), "millidegrees_C")
packages = ["build-essential", "cmake", "git", "libeigen3-dev", "libboost-serialization-dev", "libssl-dev", "libgl1-mesa-dev", "libglew-dev", "libegl1-mesa-dev", "libjpeg-dev", "libpng-dev", "libtiff-dev"]
output, _ = command(["dpkg-query", "-W", "-f=${Package},${Version},${db:Status-Status}\n"] + packages)
for line in output.splitlines():
    fields = line.split(",")
    if len(fields) == 3:
        record("package", fields[0], fields[1] + " (" + fields[2] + ")")
output, rc = command(["bash", "-c", "printf 'int main() {}\\n' | g++ -march=native -x c++ -fsyntax-only -"])
record("compiler_probe", "march_native_exit", rc)
record("compiler_probe", "march_native_output", output or "accepted")
with (OUT / (stem + ".csv")).open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["section", "item", "value", "unit"])
    writer.writerows(rows)
(OUT / (stem + ".log")).write_text("\n\n".join(logs) + "\n")
print("Environment CSV:", OUT / (stem + ".csv"))
print("Environment log:", OUT / (stem + ".log"))
