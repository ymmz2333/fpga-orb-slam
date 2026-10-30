#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
mkdir -p "$experiment_root/vendor"
fetch() {
    local name="$1" url="$2" tag="$3" expected="$4"
    local path="$experiment_root/vendor/$name"
    if [[ ! -f "$experiment_root/logs/$name-source-tree-verified" ]]; then
        local archive="$experiment_root/runtime/downloads/$name-$tag.tar.gz"
        mkdir -p "$(dirname "$archive")"
        if [[ "$name" == opencv && -f "$experiment_root/runtime/downloads/opencv-4.5.5.tar.gz" ]]; then
            archive="$experiment_root/runtime/downloads/opencv-4.5.5.tar.gz"
        elif [[ ! -f "$archive" ]]; then
            local repo="${url#https://github.com/}"
            repo="${repo%.git}"
            local archive_url="https://codeload.github.com/$repo/tar.gz/$expected"
            if [[ -s "$archive.part" ]]; then
                if ! curl -L --fail --connect-timeout 10 --max-time 1200 --speed-limit 1024 --speed-time 45 \
                    --continue-at - --output "$archive.part" "$archive_url" >&2; then
                    echo "Archive server does not resume this transfer; downloading afresh." >&2
                    curl -L --fail --connect-timeout 10 --max-time 1200 --speed-limit 1024 --speed-time 45 \
                        --output "$archive.part" "$archive_url" >&2
                fi
            else
                curl -L --fail --connect-timeout 10 --max-time 1200 --speed-limit 1024 --speed-time 45 \
                    --output "$archive.part" "$archive_url" >&2
            fi
            mv "$archive.part" "$archive"
        fi
        # Never overlay local modifications when rerunning source retrieval.
        if [[ -d "$path/.git" && -f "$path/CMakeLists.txt" && -n "$(git -C "$path" status --porcelain --untracked-files=no)" ]]; then
            echo "Refusing to overwrite existing source changes in $path" >&2
            exit 1
        fi
        mkdir -p "$path"
        tar -xzf "$archive" --strip-components=1 -C "$path"
        # Equivalent to a shallow clone, but fetching after extracting avoids
        # Git 2.25 trying to hydrate missing attribute blobs during clone.
        if [[ ! -d "$path/.git" ]]; then
            git -C "$path" init >&2
            git -C "$path" remote add origin "$url"
        fi
        git -C "$path" config core.autocrlf false
        # Archive blobs are original bytes. Some upstream Windows files contain
        # CRLF despite text attributes; prevent index normalization on import.
        printf '* -text\n' > "$path/.git/info/attributes"
        git -C "$path" config remote.origin.promisor true
        git -C "$path" config remote.origin.partialclonefilter blob:none
        timeout 90 git -C "$path" -c http.version=HTTP/1.1 -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=45 \
            fetch --depth 1 --filter=blob:none --no-tags origin "refs/tags/$tag:refs/tags/$tag" >&2
        git -C "$path" add --force --all
        # GitHub archives omit submodule gitlinks. Restore their exact upstream
        # index entries; optional pybind11/vcpkg sources are not built in A1.
        while IFS=$'\t' read -r metadata submodule_path; do
            if [[ "$metadata" == 160000\ commit\ * ]]; then
                local submodule_commit="${metadata##* }"
                git -C "$path" update-index --add --cacheinfo "160000,$submodule_commit,$submodule_path"
            fi
        done < <(git -C "$path" ls-tree -r "$expected")
        if [[ "$(git -C "$path" write-tree)" != "$(git -C "$path" rev-parse "$expected^{tree}")" ]]; then
            local repo="${url#https://github.com/}"
            repo="${repo%.git}"
            python3 "$experiment_root/scripts/hydrate_archive_omissions.py" "$path" "$expected" "$repo" >&2
        fi
        local tree expected_tree
        tree="$(git -C "$path" write-tree)"
        expected_tree="$(git -C "$path" rev-parse "$expected^{tree}")"
        [[ "$tree" == "$expected_tree" ]] || { echo "Archive tree mismatch for $name: $tree != $expected_tree" >&2; exit 1; }
        git -C "$path" symbolic-ref HEAD "refs/heads/a1/pinned-source"
        git -C "$path" update-ref HEAD "$expected"
        git -C "$path" diff --cached --exit-code HEAD >&2
        printf '%s\n' "$tree" > "$experiment_root/logs/$name-upstream-tree.txt"
        # Keep the marker outside the source tree to leave its git status clean.
        touch "$experiment_root/logs/$name-source-tree-verified"
    fi
    local actual
    actual="$(git -C "$path" rev-parse "$tag^{commit}")"
    [[ "$actual" == "$expected" ]] || { echo "Unexpected $name commit: $actual" >&2; exit 1; }
    printf '%s,%s,%s,%s\n' "$name" "$tag" "$actual" "$url"
}
{
    echo 'component,tag,commit,url'
    fetch ORB_SLAM3 https://github.com/UZ-SLAMLab/ORB_SLAM3.git v1.0-release 0df83dde1c85c7ab91a0d47de7a29685d046f637
    fetch Pangolin https://github.com/stevenlovegrove/Pangolin.git v0.8 aff6883c83f3fd7e8268a9715e84266c42e2efe3
    fetch opencv https://github.com/opencv/opencv.git 4.5.5 dad26339a975b49cfb6c7dbe4bd5276c9dcb36e2
} | tee "$experiment_root/logs/source_versions.csv"
