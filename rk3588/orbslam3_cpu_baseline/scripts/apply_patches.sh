#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
source_root="$experiment_root/vendor/ORB_SLAM3"
phase="${ORB_PHASE:-a1}"
case "$phase" in
    a1) branch=a1/rk3588-cpu-baseline; patch_limit=7 ;;
    a2) branch=a2/euroc-baseline; patch_limit=8 ;;
    b1) branch=b1/external-features; patch_limit=9 ;;
    c1) branch=c1/tello-observability; patch_limit=10 ;;
    *) echo 'ORB_PHASE must be a1, a2, b1 or c1' >&2; exit 2 ;;
esac
if git -C "$source_root" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$source_root" checkout "$branch"
else
    git -C "$source_root" checkout -b "$branch" 0df83dde1c85c7ab91a0d47de7a29685d046f637
fi
for patch in "$experiment_root"/patches/*.patch; do
    prefix="$(basename "$patch")"
    prefix="${prefix%%-*}"
    [[ "$prefix" =~ ^[0-9]{4}$ ]] || { echo "Invalid patch name: $patch" >&2; exit 2; }
    (( 10#$prefix <= patch_limit )) || continue
    title="$(sed -n 's/^Subject: //p' "$patch" | head -n 1)"
    [[ -n "$title" ]] || { echo "Missing patch subject: $patch" >&2; exit 1; }
    # Later phases may insert adjacent lines. The fallback still checks the
    # actual changed lines; only irrelevant surrounding context is omitted.
    # Fresh application below always retains strict context matching.
    if git -C "$source_root" apply --reverse --check "$patch" 2>/dev/null || \
       git -C "$source_root" apply --reverse --check -C0 "$patch" 2>/dev/null; then
        printf 'Already applied: %s\n' "$title"
        continue
    fi
    git -C "$source_root" apply --check "$patch"
    git -C "$source_root" apply "$patch"
    mapfile -t paths < <(git -C "$source_root" apply --numstat "$patch" | cut -f3)
    git -C "$source_root" add -- "${paths[@]}"
    git -C "$source_root" -c user.name='RK3588 Baseline' -c user.email='rk3588-baseline@local' commit -m "$title"
done
git -C "$source_root" log --format='%H%x09%s' -n 12 | python3 -c '
import csv, sys
writer = csv.writer(sys.stdout)
writer.writerow(["commit", "subject"])
writer.writerows(line.rstrip("\n").split("\t", 1) for line in sys.stdin)
' | tee "$experiment_root/logs/orb_commits.csv"
