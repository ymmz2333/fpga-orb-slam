#!/usr/bin/env python3
"""Restore archive-omitted files from pinned upstream blobs and verify each SHA."""
import hashlib
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

path = pathlib.Path(sys.argv[1]).resolve()
commit = sys.argv[2]
repository = sys.argv[3]
(path / ".git/info/attributes").write_text("* -text\n")


def git(*args):
    return subprocess.check_output(["git", "-C", str(path)] + list(args), text=True)


git("add", "--force", "--all")
tree = {}
for line in git("ls-tree", "-r", commit).splitlines():
    metadata, filename = line.split("\t", 1)
    mode, kind, sha = metadata.split()
    tree[filename] = (mode, kind, sha)

for pass_number in range(2):
    differences = git("diff", "--cached", "--name-status", commit).splitlines()
    selected = [line.split("\t", 1)[1] for line in differences
                if line.startswith("D\t") or pass_number == 1]
    for filename in selected:
        if filename not in tree:
            # CMake can create a source-side .cache while dependencies build.
            # Preserve those generated files but never include them upstream.
            git("update-index", "--force-remove", filename)
            print("Excluded generated index entry:", filename, flush=True)
            continue
        mode, kind, expected = tree[filename]
        if kind != "blob":
            if kind == "commit":
                git("update-index", "--add", "--cacheinfo", mode + "," + expected + "," + filename)
            continue
        target = path / filename
        if target.is_file():
            current = target.read_bytes()
            normalized = current.replace(b"\r\n", b"\n")
            candidates = (current, normalized, normalized.replace(b"\n", b"\r\n"))
            restored = next((content for content in candidates
                             if hashlib.sha1(("blob %d\0" % len(content)).encode() + content).hexdigest() == expected), None)
            if restored is not None:
                target.write_bytes(restored)
                target.chmod(0o755 if mode == "100755" else 0o644)
                print("Restored exact upstream line endings:", filename, flush=True)
                continue
        url = "https://raw.githubusercontent.com/" + repository + "/" + commit + "/" + urllib.parse.quote(filename)
        print("Recovering upstream blob:", filename, flush=True)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    content = response.read()
                actual = hashlib.sha1(("blob %d\0" % len(content)).encode() + content).hexdigest()
                if actual != expected:
                    raise RuntimeError("Upstream blob mismatch for " + filename)
                target = path / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(0o755 if mode == "100755" else 0o644)
                print("Restored verified upstream blob:", filename, flush=True)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(0.5)
    git("add", "--force", "--all")
    for filename in git("ls-files").splitlines():
        if filename not in tree:
            git("update-index", "--force-remove", filename)
    if git("write-tree").strip() == git("rev-parse", commit + "^{tree}").strip():
        print("FULL_UPSTREAM_TREE_VERIFIED", flush=True)
        break
else:
    raise RuntimeError("Full source tree still differs from the upstream commit")
