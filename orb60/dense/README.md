# Colored dense reconstruction and live processing

The first physical pipeline is implemented. See [STATUS.md](STATUS.md) for actual
measurements and the remaining visual-quality limits. Production inference uses
MiDaS v2.1 Small FP16 on RK3588 NPU. Depth Anything V2 failed the accuracy gate
and remains a retained rejected candidate; it is not silently used on CPU.

Design selection: a private C++ RKNN worker owns neural inference; computer/RK
software owns video preparation and geometry. No new PL block is needed.

Generated assets and reports live in `orb60/build/dense/`, never in source.
All model downloads have pinned upstream revisions and SHA256 records. The
Linux conversion virtual environment and board runtime are private directories;
system libraries and Python packages must not be replaced.

Start actual processing and watch the map grow from the workspace root:

```powershell
.\Launch-ORB-Dense.cmd
```

This runs physical FPGA ORB, SLAM and asynchronous NPU keyframe depth. Point
chunks accumulate while the camera moves; existing GPU point buffers persist.
The four live panes show the current image, FPGA features, incremental RGB map,
and original sparse SLAM map. Restart cleans up the owned backend before a fresh
session; startup and runtime FPGA failures stop processing with a visible error.
See [live processing and measurements](LIVE_PROCESSING.md). It currently uses
the paired existing recording. To inspect a finished offline result instead,
run `Launch-ORB-Dense-Result.cmd`.

For the result-only launcher, ignored `orb60/build/dense/latest.local.json` selects the result. The desktop
also accepts `--dense path/to/result.json`. Choose one map if a result contains
several; separate maps are not combined. Full RGB export is independent of the
200,000-point display limit. Source color/feature panels show a genuine selected
keyframe, not a visualization JPEG.

Start a new offline job using the existing key-authenticated SSH workflow:

```powershell
powershell -ExecutionPolicy Bypass -File orb60/dense/scripts/run_modeling.ps1 `
  -Video input.mp4 -Camera camera.yaml -Name room_scan
# Unknown camera must be explicit:
powershell -ExecutionPolicy Bypass -File orb60/dense/scripts/run_modeling.ps1 `
  -Video input.mp4 -ApproximateCamera -Name room_scan_approx
```

This needs the deployed NPU worker and SLAM export extension, and the FPGA
feature service on port 5600. It uploads immutable input copies and starts a
durable `rk` job. Reusing the name checks an existing running job rather than
launching a duplicate. Repeating after completion resumes matching stages;
changed video/camera/code/model requires a new result directory. Do not run
another live FPGA tracking client concurrently. Detailed output remains in the
normal board `runtime/ssh_jobs/` directory. Use `rk status`, `rk wait`, `rk log`.

The standalone Linux entry is `PYTHONPATH=<workspace>/orb60 python3 -m
dense.reconstruct --help`. Its `--video`, `--camera`/`--approximate-camera`,
`--output`, `--slam-root`, `--fpga-host`, `--network-runner`, `--worker`, `--model`
and `--npu-acceptance` are explicit. `--dataset` optionally reuses a verified
existing working-image dataset and source-frame manifest. Without it, all
decodable frames are prepared with original PTS, rotation, camera adjustment,
letterbox and validity mask. Raw input is never rewritten. Stages are
`track`, `select`, `infer`, `fuse`; the default runs all four.

Results contain separate `map_ID/` folders with `dense.ply`, `sparse.ply`,
`poses.json`, `result.json`, original and working color keyframes, camera-depth
NPY arrays and validity masks. `keyframes.json` preserves the final original
SLAM poses/observations association; `reconstruction_keyframes.json` adds fits.
PLY/preview poses are normalized by the first valid median sparse depth; the
original raw SLAM coordinate data remains available. `state.json` records
checksums, timings and memory. Unreconstructable frames are explicitly skipped.

## Reproduce the NPU gate

From the workspace root:

```powershell
powershell -ExecutionPolicy Bypass -File orb60/dense/scripts/prepare_npu_gate.ps1
```

This prepares official upstream sources/weights/runtime and an isolated WSL
conversion environment. Subsequent gate stages write resumable artifacts and
retain failed attempts. A converter or board process exit code alone is not an
acceptance: 20 real indoor frames, reference comparison and NPU placement/run
evidence are required. Per-candidate conversion, numerical and acceptance JSON
files remain in `orb60/build/dense/<candidate>/`.

`run_conversion.ps1 -Stage Reference|Compile -Model DepthAnything|MidasSmall`
creates the PC reference/ONNX and FP16 RKNN. `fetch_midas.py` and 256×256 samples
are needed for the prescribed fallback. `board_gate.ps1 -Stage Deploy|Run|Collect
-Attempt midas-small-fp16 -Samples samples-midas` uses the durable SSH workflow.
Then run `evaluate_npu_gate.py` and `finalize_gate.py`; the latter requires actual
NPU operator profiling and a successful durable job, not just numeric agreement.

MiDaS uses pinned v2.1 source and complete checkpoint with a pinned local
EfficientNet backbone. Its old packaged ONNX differs from the TorchScript release,
and the old TorchScript cannot be exported directly by the chosen PyTorch.
The retained implementation therefore re-exports the same-version official eager
model and verifies it before conversion. Failed exports and comparisons remain
in build logs. No acceptance threshold was loosened.

SLAM source extensions are installed with `scripts/install_export.py` and
`scripts/install_feature_mask.py`; each preserves the previous sources/binaries.
The C++ worker is built with `npu/CMakeLists.txt` and an explicit private
`RKNN_PRIVATE_ROOT`. Do not replace `/usr/lib/librknnrt.so` or upgrade the kernel.

## Offline playback and finer fusion

The separate `Launch-ORB-Dense-Result.cmd` replays the original video and same-run
final camera poses. Dense clouds use world-space point sizes and view-dependent
detail, while export retains all points. A separate cached-depth refinement
produced 1,086,538 real colored points without rerunning tracking or inference.
See [playback and density notes](PLAYBACK_AND_DENSITY.md) for controls,
measurements, reproduction and geometry limits.

## Verification

Geometry/video tests are under `tests/`; native `test_feature_mask.cpp` verifies
descriptor-footprint exclusion and record order. `test_prepare_video.py` runs a
real codec/rotation/PTS test on an explicitly synthetic clip. Numerical gate
tests require SciPy in the conversion environment. Viewer regressions and
`qa_dense.py` live in `orb60/viewer`. `scripts/verify_reconstruction.py` independently
checks real poses, observations, source indices, RGB, FPGA requests and gate SHA.
Strict byte comparison to the original video runs in the board decoder environment;
Windows versus board FFmpeg can differ by two RGB code values.
