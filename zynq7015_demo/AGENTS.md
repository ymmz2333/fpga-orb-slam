# Two-stage demonstration working copy

Root D:/pld rules apply. This is the editable PS software working copy of
../zynq7015_usb_slam_20261024/source. UPSTREAM_SHA256.json records the input.
Never edit the upstream package or frozen vendor sources.

- Keep the paired ORB150MHz/HDMI bitstream, factory kernel and boot files.
- PS software owns camera, networking, fixed-map matching/PnP and display.
- No CPU ORB fallback, replay fallback, automatic PL fault recovery or map reset.
- One compiler process at a time, minimum available memory 1536MiB.
- Tool locations are configured through root scripts/project_env.ps1 and local
  overrides, not the upstream author's hard-coded profile paths. No WSL.
- Board acceptance requires actual camera/PL, map transfer, disconnected local
  localization and reboot evidence; native tests cannot substitute for it.
