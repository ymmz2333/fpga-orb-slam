# D:\pld FPGA panorama workspace rules

## Session startup

- `D:\pld` is the canonical project root.  The former copy under the Codex
  documents directory is rollback-only; never implement new work there.
- Before changing the panorama implementation or claiming a verification
  result, read `START_HERE.md`, `DEVELOPMENT_GUIDE.md`, and
  `panorama/WORKFLOW.md` completely.
- Use normal Codex communication style in this workspace.  Do not invoke the
  `opus-like` skill unless the user explicitly reverses this rule.
- Run `powershell -ExecutionPolicy Bypass -File scripts/check_environment.ps1`
  before the first tool-dependent action in a new environment.

## Objective and PS/PL boundary

- The reproducible computer simulation must build a panorama from the supplied
  bookshelf photographs using results produced by simulated FPGA logic.
- The computer/Zynq PS owns image preparation, match filtering, RANSAC,
  Homography, Warp, Blend, diagnostics, and the final panorama file.
- The simulated PL owns ORB feature extraction, 256-bit descriptors, and
  Hamming-distance matching.  It may mix Vitis HLS, hand RTL, and AMD IP; pure
  Verilog is not required.
- For isolated IP verification, prefer direct AXI4 memory-mapped access to a
  randomized cocotb DDR model.  Add DMA only at a justified AXI-Stream/DDR
  boundary or in the integrated AMD-IP design.

## Mandatory design-selection gate

Before implementing a block, explicitly choose PS/software, mature AMD IP,
HLS, hand RTL, or a hybrid.  Decide from algorithm structure, cycle-level
control, existing IP maturity, resource/timing budgets, and development risk.
If uncertain, synthesize bounded alternatives and compare evidence.

Current defaults:

- Standard image operators: consider Vitis Vision, but retain only after a real
  comparison with the hand-RTL baseline.
- ORB orientation and rotated BRIEF: custom HLS; replace only measured
  bottlenecks with RTL.
- 256-bit Hamming matcher: hand RTL baseline.
- PS7 DDR, SmartConnect, clocks, reset, and justified DMA: AMD IP.
- RANSAC, Homography, Warp, Blend, and final image: PS/computer software.

## Verification gates

- HLS: independent Python/OpenCV golden -> C simulation -> C synthesis ->
  C/RTL co-simulation -> cocotb against generated RTL with randomized AXI ->
  Vivado OOC -> retained top-level implementation.
- Hand RTL: independent golden -> cocotb with reset/random handshakes ->
  Verilator lint -> optional Yosys trend check -> Vivado OOC/top route.
- Modify HLS C++ and directives, never generated RTL.  Modify handwritten
  logic in RTL.  Do not weaken a failed post-check or relabel it as passing.
- Large multi-frame regressions use native Verilator HDL testbenches; cocotb is
  the protocol/random-stall gate.  XSIM/ModelSim handles AMD models and IP.
- The authoritative resource result is the complete routed top, not a sum of
  OOC cores.  Record setup/hold, unconstrained paths, DRC, routing, congestion,
  and hierarchical LUT/FF/BRAM/DSP usage.

## Integration and timing rules

- Do not write full images to DDR between small sequential stages.  Prefer
  DATAFLOW, local BRAM/FIFO, or AXI-Stream when the access pattern allows it.
- Multiple IPs do not automatically imply DMA.  Direct `m_axi` masters may
  share PS DDR through SmartConnect.
- Begin pairwise integration after adjacent unit gates pass.  Then verify a
  shared DDR address space, ownership, 4 KB burst boundaries, contention,
  backpressure, FIFO watermarks, bytes/frame, and end-to-end latency.
- Optimize only from the real critical path.  Add pipeline/register slices at
  measured hotspots, then rerun functional regressions and place-and-route.
- Retained baseline: XC7Z020 at 100 MHz.  125 MHz currently passes but its HLS
  descriptor checkpoint should be regenerated with an 8 ns target before a
  final 125 MHz release.

## Environment and generated files

- All live scripts derive paths from `scripts/project_env.ps1`.  Never add an
  absolute user-profile or old workspace path to source scripts.
- Machine-specific overrides belong in `scripts/local_env.ps1` (ignored), based
  on `scripts/local_env.example.ps1`.
- Python is the project `.venv` using CPython 3.12.12.  Do not reuse the old
  virtual environment or Vivado's bundled Python.
- Vivado/XSIM scratch defaults to `D:\pld\.work\vivado`; generated HLS/Vivado
  projects and old reports may contain historical absolute paths and are not
  source of truth.  Regenerate rather than hand-edit them.
- Keep ModelSim licensing in `MGLS_LICENSE_FILE`; do not overwrite a possibly
  unrelated `LM_LICENSE_FILE` used by other tools.

## Long jobs and completion claims

- Vivado implementation, HLS synthesis, XSIM, and long regressions run in the
  foreground by default.  Retain the terminal, poll at sensible intervals no
  longer than about 60 seconds, and report concise progress.
- Do not infer success from a running job, stale report, or missing result.
  Inspect compact summaries, then only the bounded log needed for diagnosis.
- Computer verification cannot prove board DDR training/bandwidth, PS cache
  coherency, Linux drivers, live video I/O, power, or temperature.  Keep these
  as explicit board-stage gates.

## RK3588 SSH workflow

- Reuse key-authenticated `ssh rk3588`. The PowerShell short command `rk`
  calls `rk3588/orbslam3_cpu_baseline/scripts/rk.ps1`; use that path directly
  if profiles are disabled. `rk check` is the compact connection check.
- Use `rk exec 'command' -Name short-name`, then `rk status <job_id>` or
  `rk wait <job_id> -Seconds 30`. Commands start in the board project root.
  Use `rk start` when detached execution is wanted. Never relaunch a job just
  because the client's bounded wait expired.
- Full output stays under board `runtime/ssh_jobs/<job_id>/`. Read bounded
  `rk log <job_id> -Lines 20` or `-Match 'error:|fatal|traceback|segmentation'`.
  Do not dump full build logs, repeat unchanged output, or retry passwords.
- STARTING/RUNNING is not completion, even if the query exits 0. Require
  SUCCEEDED, exit_code=0, and task-specific acceptance evidence. LOST means
  there is no trustworthy final exit code. Continue checking live jobs at
  intervals no longer than about 60 seconds and report meaningful progress.
- Read `rk3588/orbslam3_cpu_baseline/docs/SSH_WORKFLOW.md` for configuration,
  log limits and recovery. Host settings and keys stay in ignored local
  config/native SSH config. Respect the user's latest experiment-stage approval;
  SSH setup does not grant additional experiment scope.

