#!/usr/bin/env python3
"""Select only MH_01_easy from a ZIP; stream extraction validates each CRC."""
import argparse
import hashlib
import json
import pathlib
import shutil
import stat
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def extract(archive, output):
    output = pathlib.Path(output).resolve()
    if output.exists():
        raise RuntimeError("Refusing to overwrite dataset: "+str(output))
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        markers = [m.filename[:-len("mav0/cam0/data.csv")] for m in members
                   if m.filename.endswith("mav0/cam0/data.csv")]
        candidates = [p for p in markers if "MH_01_easy" in pathlib.PurePosixPath(p).parts]
        if not candidates and markers == [""]:
            candidates = [""]
        if len(candidates) != 1:
            raise RuntimeError("Cannot unambiguously locate MH_01_easy ASL directory")
        prefix = candidates[0]+"mav0/"
        chosen = [m for m in members if m.filename.startswith(prefix) and not m.is_dir()]
        paths = set()
        for m in chosen:
            relative = pathlib.PurePosixPath(m.filename[len(candidates[0]):])
            if relative.is_absolute() or ".." in relative.parts or any(":" in p or "\\" in p for p in relative.parts):
                raise RuntimeError("Unsafe archive path: "+m.filename)
            if stat.S_ISLNK(m.external_attr >> 16) or str(relative) in paths:
                raise RuntimeError("Symlink or duplicate archive member")
            paths.add(str(relative))
        output.mkdir(parents=True)
        file_hashes = {}
        for m in chosen:
            relative = m.filename[len(candidates[0]):]
            target = output.joinpath(*pathlib.PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            with target.open("rb") as stream:
                file_hashes[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    with open(archive, "rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = dict(archive_sha256=archive_hash, selected_prefix=prefix,
                    selected_files=len(file_hashes), sha256=file_hashes)
    (output / "transfer_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = extract(args.archive, args.output)
    print("A2_EXTRACT_PASS selected_files=%d archive_sha256=%s" %
          (manifest["selected_files"], manifest["archive_sha256"]))
