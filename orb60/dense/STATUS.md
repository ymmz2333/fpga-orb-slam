# First implementation results — 2026-10-22

**Actual live-processing update:** the default launcher now runs FPGA SLAM and
NPU depth concurrently, retaining per-keyframe GPU point blocks as the map grows.
The 900-frame real run produced 33 blocks / 224,948 points at 23.13 display FPS.
See [live processing evidence](LIVE_PROCESSING.md).

Full live run: 2,273 real FPGA requests, zero CPU ORB, 98 NPU frames, 91 point
blocks / 628,857 colored points. Normal desktop display averaged 20.86 FPS;
the initial point block appeared at 15.62 s including initialization.

**Separate result viewer:** `Launch-ORB-Dense-Result.cmd` opens a 1,086,538-point
refinement with full 2,273-frame video replay, same-run camera poses, pause/seek/
restart, world-space point coverage and view-dependent detail. Source depth and
geometry support are unchanged. See [measured update](PLAYBACK_AND_DENSITY.md).

The physical FPGA → RK3588 SLAM → NPU depth → colored voxel cloud → desktop
chain runs. The existing 150 MHz bitstream and PS write-combining service were
restored after a board reboot. No HLS/RTL, place-and-route or SD boot change.

## Model gate

Depth Anything V2 Small 518×392 FP16 compiled and executed on NPU but failed
accuracy: worst normalized RMSE 61.02%, minimum Spearman 0.4158. It is rejected.

The prescribed MiDaS v2.1 Small 256×256 FP16 fallback passed all 20 real indoor
keyframes: worst normalized RMSE **0.6756%**, minimum Spearman **0.999896**.
Actual profiling shows **128 NPU compute nodes**. CPU resize/I/O are recorded;
no prohibited CPU network fallback. Mean inference **94.87 ms**. Private Runtime
2.5.0 works with driver 0.9.8; system Runtime 1.6.0 was not replaced.

## Physical reconstruction

| Input | 900-frame / ~30 s clip | Full 2,273 valid frames |
|---|---:|---:|
| Colored fused points | 107,876 | 140,244 |
| Selected keyframes | 32 | 83 |
| Accepted depth keyframes | 31 | 79 |
| Skipped invalid fits | 1 | 4 |
| Tracking, including startup/shutdown | 27.51 s | 51.29 s |
| Source color preparation | 10.18 s | 21.24 s |
| NPU pass | 3.37 s | 8.58 s |
| Alignment/filter/fusion | 19.51 s | 49.13 s |
| Peak measured process RSS | 501.8 MiB | 649.1 MiB |

Full-sequence SLAM processing throughput: **55.89 FPS**, CPU ORB calls zero.
The 900-frame run's feature counts/record CRCs match the paired prior run exactly.
Fresh multithreaded SLAM runs can produce different optimized keyframe sets;
resume checks and retains completed artifacts. Four-stage resume was exercised.

Strict board-side source RGB comparison passed with zero pixel error. Windows
versus board FFmpeg RGB conversion differs by at most two code values. The
initial failed cross-decoder byte check is retained, not relabeled as passing.
It is not a frame-index or RGB/BGR mismatch.

## Checked implementation

- Final stable atlas export, separate maps, final Twc/intrinsics/distortion,
  reliable sparse observations, exact source indices and original color PNG.
- C++ NPU worker, model SHA, real operator profiles, execution and memory data.
- Robust affine inverse-depth fitting, invalid-frame skips, multiview support,
  1%-of-reference-depth voxel edge, two-million-point deterministic capacity.
- Stage checksums, exclusive output ownership, resume, retained failed attempts.
- Explicit approximate-camera mode, original PTS, phone rotation, letterbox and
  native descriptor-footprint validity mask. A 12-frame rotated synthetic clip
  passed real codec/preparation and actual FPGA protocol tests (CPU ORB zero).
- Desktop RGB cloud loading, sparse/dense switches, rotation/zoom, full PLY
  export; display capped at 200,000 points. ORBVIZ01 remains compatible.

## Quality limits

This is a rough relative-scale prototype. The supplied Tello recording uses
explicitly borrowed provisional intrinsics. Major surfaces and colored object
regions are visible, but shelf/box edges remain blurred; some surfaces show
thickness/curvature and isolated noise. Fine structure quality is **not fully
accepted**. No metric accuracy, filled surfaces or realtime depth is claimed.

A calibrated, translating, well-lit input is needed for the next quality pass.
Phone-file preparation is implemented/tested; no actual phone recording was
available for a reconstruction quality check. All code and measured evidence
remain available even where visual quality is incomplete.
