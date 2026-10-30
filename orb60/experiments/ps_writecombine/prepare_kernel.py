"""Extract the supplied factory kernel to fresh WSL scratch and check its config."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import subprocess
import tarfile
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path,
                        default=Path.home() / ".cache/orb60-writecombine")
    args = parser.parse_args()
    output = args.output.resolve()
    prefix = "ACZ7015_Linux_Factory_Source/linux/kernel"
    with tarfile.open(args.archive, "r:gz") as archive:
        count = 0
        for member in archive:
            if member.name != prefix and not member.name.startswith(prefix + "/"):
                continue
            relative = PurePosixPath(member.name).relative_to(prefix)
            if ".." in relative.parts or relative.is_absolute():
                raise RuntimeError("Unsafe archive path")
            if member.issym():
                target = posixpath.normpath(str(relative.parent / member.linkname))
                if target.startswith("../") or target == ".." or target.startswith("/"):
                    raise RuntimeError("Unsafe kernel symlink: " + member.name)
            if member.islnk() and not member.linkname.startswith(prefix + "/"):
                raise RuntimeError("Unsafe kernel hard link")
            count += 1
    args.scratch_root.mkdir(parents=True, exist_ok=True)
    kernel = Path(tempfile.mkdtemp(prefix="kernel-", dir=args.scratch_root))
    subprocess.run(["tar", "-xzf", str(args.archive), "-C", str(kernel),
                    "--strip-components=3", prefix], check=True)
    live = gzip.decompress((output / "live.config.gz").read_bytes())
    source_config = (kernel / ".config").read_bytes()
    if live != source_config:
        raise RuntimeError("Factory .config differs from the running kernel; refuse to build/load")
    for required in ("Module.symvers", "include/generated/autoconf.h", "include/generated/utsrelease.h"):
        if not (kernel / required).is_file():
            raise RuntimeError("Missing factory build artifact: " + required)
    release = (kernel / "include/generated/utsrelease.h").read_text()
    if release.strip() != '#define UTS_RELEASE "4.14.0-xilinx"':
        raise RuntimeError("Unexpected kernel release")
    record = dict(archive=str(args.archive), archive_sha256=digest(args.archive),
                  extracted_kernel=str(kernel), selected_members=count,
                  live_config_exact=True, config_sha256=hashlib.sha256(live).hexdigest(),
                  module_symvers_sha256=digest(kernel / "Module.symvers"),
                  compile_header=(kernel / "include/generated/compile.h").read_text())
    (output / "kernel_provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    (output / "kernel_path.txt").write_text(str(kernel) + "\n")
    print("FACTORY_KERNEL_CONFIG_EXACT", kernel)


if __name__ == "__main__":
    main()
