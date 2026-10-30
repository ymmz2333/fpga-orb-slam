# ORB60 evidence and remaining gates

## Scope and implementation choices

Independent development lives here; the R11 archive remains unchanged. Target:
xc7z015clg485-2, 960x720, eight layers, 100 MHz primary clock, exact A32 ORB.
Custom HLS is retained for FAST/Gaussian/Resize and the future descriptor. AMD
IP owns PS7, AXI protocol/width conversion, clock and reset. PS software owns
scheduling, buffer ownership and cache visibility. No new DMA is required.

The baseline uses the paired R8 image/frontend sources and the frozen default
R11 PS release. Profile uses a separate host-test entry/library. The 94-file
origin hashes are in provenance.json; CMake and the board-host include selector
are migration harness changes. Algorithms and frozen_ps files are unchanged.

## Verified 2024.2 baseline

- Host: 17/17 exact tests passed; GNU 13.2.0, CPython 3.12.12.
- HLS job: build/baseline/hls/20261012_010831_all_5ef88504, SUCCEEDED.
- CSim, synthesis, Verilog co-simulation and IP export passed for all three
  cores. FAST 11, Resize 13, Gaussian 14 transactions. FAST includes 70,398
  candidates, fallback, capacity rejection and restart cases.
- 32-bit address registers and original offsets are retained. FAST output
  remains a 512-bit AXI interface. Deprecated DATA_PACK is ignored by 2024.2;
  co-simulation confirms exact record layout for these transactions.
- Independent NumPy oracle reproduces all 11 frozen C++ FAST summary/point
  vectors exactly and produces all 38 AXI vectors. Resize and Gaussian use
  rational integer arithmetic/direct reflected convolution, without DUT ROMs.
- New synthesis estimates are not routed resource evidence. The 2024.2 compiler
  automatically pipelines the candidate reducer at II=3; the pixel loop is II=1.

## Current gate and execution policy

The user subsequently prioritized modification effects. The extended baseline
gate 20261012_013221_5df2bed0 was cancelled during resize smoke; only FAST's two
randomized AXI smoke/recovery transactions completed (PASS). Do not treat the
cancelled chain as a full protocol or routed baseline pass. Proceed with bounded
optimization comparisons using the accepted 17-host/three-core co-sim baseline.

First optimized candidate: four explicitly pipelined signed 9-bit maxima
stages (16->8->4->2->1), a versioned front64 HLS entry with contiguous 64-bit
point/summary writes, and generator-owned 21-bit resize coordinates. The direct
front64 bench checks all 16,000 output bytes, including unwritten slots; the
legacy host interface is a compatibility adapter. Resize tests independently
derive indices/weights from rational arithmetic after the representation change.
Candidate reducer II=1, shared-read 2PPC and PL descriptors remain later work.

Optimization comparison 20261012_014321_982b7277 FAILED in FAST co-simulation
wrapper compilation. All 17 optimized host tests and FAST CSim/synthesis passed.
The host-only legacy adapter caused the design translation unit to be compiled
as a co-simulation auxiliary, where HLS rewrote the top declaration's C linkage.
Exclude that adapter from FASTV2_HLS_CSIM as well as synthesis; the direct front64
bench never uses it. No generated RTL or frozen failed-job inputs are edited.
Provisional FAST HLS estimates: LUT 26687->13341, FF 14485->7878,
BRAM18 74->53, AXI output 512->64 bits; EmitCellOrder II 2->1.
RasterColumns remains II=1; ReduceCandidateTokens remains II=3. These estimates
are not a route/timing pass or a functional RTL acceptance for the failed job.

scripts/baseline_gate.ps1 first runs randomized AXI smoke/recovery cases, then
all 38 exact transactions, then the complete three-core PS7 top implementation.
Each step requires its own post-check before the next begins. It reuses the
existing cocotb/ModelSim environment and shared AXI-Lite driver. The scoped DDR
model adds correct narrow-transfer bus lanes for the 512-bit output port.
Monitors check stable requests under stalls, legal strobes/addresses, 4 KB burst
boundaries, response errors and all write responses completed before ap_done.
Every IP is interrupted during a live transaction and restarted after reset.

The user's latest execution preference supersedes the root polling default:
after starting a long job, finish the conversation turn and wait for the user
to report completion. Keep status JSON/logs and inspect them on resumption.

## Still required

Comparison 20261012_090905_358bc3ea SUCCEEDED: 17 host tests, FAST 11 and
Resize 13 co-simulation transactions passed. FAST HLS LUT/FF/BRAM18 estimates
26687/14485/74 -> 13341/7878/53; EmitCellOrder II 2->1; output AXI 512->64.
FAST max co-simulation cycles 796630->796665: this stage saves resources but
does not yet improve the full scan latency. Resize BRAM18 46->42, DSP 14->13,
max cycles 697732->697130. Estimated periods remain 7.902/7.300 ns, not routed
timing evidence. Retain both immutable accepted child jobs for comparison.

The next HLS candidate uses fully partitioned 8-bit per-cell score registers
and one write-only payload BRAM during reduction. No false dependency directive
is used. Raster-ordered tokens make the first equal-score point the exact tie
winner; CSim asserts that order. A low-threshold maximum is the high-threshold
maximum whenever any high candidate exists, so one payload store suffices and
fallback follows from winner.score<high. Independent sorted-grid host cases
cover same-cell runs, score ties, cell revisits, all profiles, empty/capacity
cases and guards. Only changed FAST is rebuilt; unchanged Resize reuse requires
consumed-source hashes and its prior co-simulation acceptance. The new comparison
explicitly fails its throughput post-check unless ReduceCandidateTokens II=1.

Comparison 20261012_093609_7f0ade4f SUCCEEDED: 18 host tests and all 11 FAST
C/RTL transactions passed. ReduceCandidateTokens achieved II=1, depth=3.
Compared with the accepted stage-one front64, HLS estimates increased from
13341/7878 to 21209/11111 LUT/FF and decreased BRAM18 53->51. Max transaction
latency remained 796665 cycles; the scan is still 1PPC. This register-score
implementation is retained as a throughput reference, with resource cost
explicitly pending complete-top measurement.

The current 2PPC FAST block uses custom HLS: a streamed 64-bit DDR reader,
odd-row-aware unpacker, packed 16-bit pixel/score line banks, two score lanes,
and a lossless ordered pair serializer feeding the accepted reducer. Generator
owned paired geometry avoids two accesses to a single-port coordinate ROM.
The independent golden exports 16 exact transactions covering all eight levels;
host merge stress also covers 4096 consecutive double-valid pairs. The bounded
front2_gate.ps1 runs host/C simulation/synthesis/co-simulation, then requires
measured II=1 for unpack, pair scan, pair merge and reduction. It records any
failure without weakening the check. Shared-reader Gaussian/Resize integration,
finite-FIFO protocol stress, PL descriptors and retained top routing are still
required after this standalone unit gate.

Front2 comparison 20261012_100352_front2_a93d1812 failed only its report-name
post-check: HLS flattened UnpackPairs to VITIS_LOOP_25_1_UnpackPairs. All 20
host tests and 16 RTL transactions passed; no design change is needed. The
original failed record is retained. Recovery comparison
20261012_101511_front2_2b7af5e6 reuses the immutable accepted HLS child and passes
all four II=1 checks with independent XML/log agreement. The parser rejects
missing or ambiguous labels and retains actual II violations; three script
regressions pass. The 960x720 high-density transaction decreased from 796665 to
355392 cycles, HLS LUT/FF/BRAM18 increased 21209/11111/51 -> 27339/14504/63.
These remain estimates/co-simulation results, without routed or board claims.

The next front2_axi_gate.ps1 uses the existing randomized cocotb/ModelSim DDR
workflow. It independently rechecks all 16 frozen C++ outputs with Python, then
checks AXI stalls, 4 KB boundaries, byte guards, write-response completion and
live-reset recovery. Generated front2 RTL is staged byte-identically; no RTL
or prior result is edited. Complete-top timing and resources are still pending.

AXI gate 20261012_101714_front2_27c2a9b0 FAILED during full-regression Python
startup at simulation time zero (sys.stdout=None in cocotb logging). Independent
Python/C++ vectors and both smoke/reset transactions passed. This is not full
protocol acceptance, and its failed state is retained. Runtime startup repair
is pending; do not infer a DUT protocol failure from this log.

The user explicitly prioritized 2PPC routed WNS over protocol testing at this
stage. timing.ps1 therefore runs a bounded 100 MHz complete three-core timing
experiment using the accepted front2, compressed-ROM Resize and baseline
Gaussian 2024.2 IPs. Custom HLS remains the algorithm implementation; AMD IP
provides PS7, AXI protocol/width conversion, clocks and resets. The experiment
has fixed source/IP hashes and reports setup/hold paths, coverage, DRC,
congestion and hierarchical mapped resources. It records measured slack even
when negative before strict post-checks. No bitstream/XSA is exported in this
timing-only run. Complete protocol and release gates remain pending.

Timing job 20261012_102428_front2_100mhz_5723af21 FAILED during IP generation:
Vivado hit the legacy Windows 260-byte path limit on generated HLS filenames.
Synthesis/place/route never started; there is no measured WNS from that job.
The timing runner now stages all live inputs/IPs/projects under the configured
VivadoBuildRoot with an eight-character unique directory and project/BD names
p/s. It rejects predicted IP paths >=240 bytes before Vivado and archives
compact reports/status separately. Authored HLS, clock/device and failed-job
snapshots are unchanged; no drive mapping or generated-RTL edit is used.

Timing job 20261012_102919_front2_100mhz_c3c05ce4 completed actual route_design
but FAILED the wrapper's exact STATUS-string check: Vivado 2024.2 returned
"Not started phys_opt_design (Post-Route)" for the next enabled step. Its routed
report proves 100 MHz WNS +0.180 ns, TNS 0, WHS +0.050 ns, THS 0, and all 34344
routable nets fully routed without errors. The worst path is in front2 lane0
FAST score, d_16 register to select_ln161_14 register: 12 logic levels,
9.516 ns data delay (3.696 logic, 5.820 route). Coverage counts are zero. DRC
lists warnings, no error/critical-warning rows. These are real complete-top
route measurements despite the retained failed wrapper status; they do not
prove full protocol/release/board acceptance or include post-route phys_opt.

The build wrapper now requires the unique run's route completion marker,
absence of an error marker and its routed checkpoint; shared strict reports
also require every routable net fully routed and setup/hold/coverage/DRC gates.
The 2024.2 coverage parser handles the added heading counts and rejects missing,
inconsistent or nonzero evidence. timing_recover.ps1 opens the immutable routed
checkpoint, checks actual part/clock, and exports fresh timing, resources,
hierarchy/congestion/DRC reports in a separate recovery job, without resynthesis,
rerouting or changing the failed job's state. Post-route optimization is not
applied during recovery so the measured checkpoint remains comparable.

Recovery 20261012_104923_front2_recovery_b41601c9 SUCCEEDED. The actual routed
complete top uses 19364 LUT (41.91%), 17823 FF (19.29%), 56/95 BRAM tiles
(42 RAMB36 + 28 RAMB18, 58.95%), and 20/160 DSP (12.50%). Slice occupancy is
6916/11550 (59.88%). R11's historical routed release used 20452 LUT, 23621 FF,
61 BRAM tiles and 16 DSP: net changes -1088 LUT (-5.32%), -5798 FF (-24.55%),
-5 BRAM tiles (-8.20%) and +4 DSP. Both reports target xc7z015clg485-2/100 MHz,
but the historical release used Vivado 2018.3 and the new candidate 2024.2;
the net change includes tool migration and design changes, not isolated causes.
New routed hierarchy: FAST 10750 LUT/9350 FF/29.5 BRAM tiles/2 DSP,
Gaussian 3479/3357/7.5/1, Resize 3395/3179/19/17. No historical hierarchical
report is available for a precise routed per-module delta. Earlier "FAST LUT
halved" was an intermediate 1PPC HLS estimate, not this final-top resource delta.

Known structural changes: explicit signed 9-bit balanced registered FAST maximum
tree; contiguous 64-bit point/summary writes replacing the 512-bit write master;
one low-threshold winner payload store with per-cell score registers replacing
two high/low payload tables; 21-bit Resize coordinates replacing the inferred
33-bit entry and deriving source_b=source_a+1; streamed 2PPC FAST reader, packed
16-bit line banks and two score lanes. II=1 score registers and two lanes add
resources, while narrower interfaces and deduplicated stores remove resources.
Per-change routed causality is not proven without same-tool controlled builds.
Worst path comparisons are between each design's own worst path: 16->12 logic
levels and 9.644->9.516 ns data delay, with WNS +0.177->+0.180 ns. The new
FAST arc-extrema/selection path has 61.16% routing delay and remains the hotspot.
Shared-read 2PPC Gaussian/Resize and exact PL descriptors are not included yet.

Next candidate: custom HLS fastv2_layer2_hls, a versioned shared-reader layer
engine. One DDR input master feeds 2PPC FAST, Gaussian and Resize through private
FIFOs/line banks; outputs use three independent 64-bit masters (point/summary/
stats, blur, next-level raw). AMD IP remains responsible for DDR/interconnect,
protocol conversion, clocks/reset. Gaussian has exact two-lane horizontal and
packed vertical filters. Resize retains only the preceding raw row and two
six-pixel windows; a generator-proven source-pair schedule emits each output
pair as soon as its samples exist. At destination widths 667/463 the final
three pixels need an explicit tail cycle, not an assumed single emission.
All output images remain flat across odd row widths and final padding is zero.

Native functional gates passed: 21 shared-layer transactions, all 14 Gaussian
and 13 Resize cases, including all profiles, zero/255/random/structured input,
capacity errors, invalid levels and untouched output guards. Point/summary
records remain unchanged. New 64-byte LayerStats identifies interface version,
issued image payload bytes/tokens and dataflow clock-loop cycles; native C
execution has no timing model and returns cycle count 1. Statistics write time,
PS delay and final AXI-response behavior remain separate checks.

layer2_gate.ps1 runs all 23 host tests, freezes sources, independently checks
19 C++ FAST vectors with NumPy/Python and records full expected image binaries,
then runs CSim/synthesis/21-transaction RTL co-simulation. The post-check reads
each pipeline XML instance separately (including both packers/writers), requires
actual II=1 and four 64-bit AXI masters. Routed resource/timing, random-AXI repair
and exact PL descriptors remain pending. No new throughput/60 FPS claim is made.

Shared-layer comparison 20261012_112245_layer2_6c71b587 SUCCEEDED. All 23 host
tests, 19 independent Python/C++ FAST crosschecks and 21 C/RTL transactions
passed. Every required pipeline instance is II=1, including both packers and
writers. Four AXI masters are actually 64 bits. HLS estimates are 39740 LUT,
23746 FF, 108 BRAM18 and 20 DSP, not mapped top utilization. The largest
transaction including FAST/Gaussian/Resize finishes in 356045 co-simulation
cycles (3.56045 ms at assumed 100 MHz), versus front-only 355392 cycles.
Recorded dataflow cycles across the eight dense-input profiles sum to 1158783
(11.58783 ms at assumed 100 MHz), excluding per-call statistics write/PS delay
and real DDR contention. This is not a complete feature-frame/board FPS result.

HLS estimates the shared-layer DATAFLOW/top control timing at 10.461 ns despite
II=1; child compute modules are <=7.3 ns estimates. Therefore first run the new
shared-reader complete top at 100 MHz via layer2_timing.ps1 rather than reusing
the prior three-core +0.180 ns claim. One layer IP replaces three independent
image masters, with AMD AXI protocol conversion on the four PS7 HP ports. The
short scratch and route completion/coverage checks reuse the corrected workflow.
Actual shared-top WNS/resources precede descriptor integration; exact custom
HLS orientation/BRIEF remains the next block after this timing check.

Shared-layer timing 20261012_115142_layer2_100mhz_bcdf4f7c completed routing
but FAILED report startup: open_run impl_1 reported the stopped run as not
launched, despite .route_design.end.rst and s_wrapper_routed.dcp being present.
Its complete-top routed report shows 100 MHz WNS +0.233 ns, TNS 0, WHS +0.053
ns, THS 0; all 30179 routable nets are fully routed with no routing errors.
The worst path moved to ReduceCandidateTokens' completely partitioned score
register select/update enable: best_score_99 -> best_score_28 CE, 11 logic
levels, 9.237 ns data delay (2.516 ns logic, 6.721 ns routing). HLS's 10.461 ns
estimate did not become a routed violation in this build. Placed utilization
is 17360 LUT/14998 FF/50.5 BRAM tiles/29 DSP, pending fresh routed report export.
The original failed state remains unchanged. Timing templates now close the
project and open the verified completed routed checkpoint instead of relying
on open_run state; recovery derives the correct shared-layer core and scope
from the parent HLS acceptance. No HLS/RTL algorithm change or reroute is needed.

Baseline randomized AXI/OOC/top route and regenerated BSP/ELF/XSA pairing are
not yet accepted. No board has been programmed or tested in this development
run. No 60 FPS result is claimed.

Shared-reader routed report recovery 20261012_120600_layer2_recovery_17c2d654
SUCCEEDED. Fresh reports from the immutable routed checkpoint confirm 17360 LUT
(37.58%), 14998 FF (16.23%), 50.5/95 BRAM tiles (53.16%) and 29/160 DSP
(18.13%). Setup WNS +0.233 ns, hold WHS +0.053 ns, TNS/THS zero; 30179/30179
routable nets fully routed, zero routing errors and zero uncovered timing checks.
The worst path is the candidate score select/update enable recorded above.

The user deferred PS changes and asked for ordinary/stress input FPS at this
stage. Existing eight-level cosim transaction latencies sum to 1159697 cycles,
or 11.59697 ms / 86.23 FPS at 100 MHz, for image preprocessing/selection only.
Using historical per-layer ARM times and unchanged cache/control costs gives
an explicitly conditional 280-point estimate near 15.6 ms/64 FPS and a linearly
scaled 942-point estimate near 30.6 ms/33 FPS with PS(n)/PL(n+1) overlap. These
are neither integrated-system nor physical-board results. Descriptor ARM time
is still exposed at high feature counts; exact PL descriptor work remains pending.

layer2_benchmark.ps1 reuses a copy of the accepted HLS solution, performs no
synthesis/route, requires before/after synthesis-RTL hashes to match and runs
24 exact transactions: the historical image, a resized noise pyramid and a
zero pyramid. Actual Resize output feeds the next layer; independent Python
checks full blur/resize/point/summary bytes and native C precedes RTL co-sim.
report_layer2_benchmark.py separates measured eight-layer latency from the
historical ARM/caching projection. PS firmware remains unmodified. No P99/max
or complete-frame FPS acceptance can be inferred from three input samples.

Exact PL descriptor candidate uses custom HLS, two separate raw/blur DDR loaders
and depth-two stream_of_blocks patch channels with explicit ownership/dual-port
BRAM binding. Raw disk storage is 31 rows x5 aligned 64-bit words; blurred patch
is 37 rows x6 words, with clipped fetches and exact sample-bound rejection.
Original int32 moments, signed-floor CORDIC, nearest-even angle rounding and A32
quantization are retained. A generator verifies all 16384 full-table coordinates
before packing 2048 24-bit pairs for eight basic directions and exact quarter
rotation reconstruction. BRIEF requests two patch reads per comparison; no false
dependency directive is used. Feature output appends complete ordered 64-byte
records to a capacity-1000 frame. A later bad point preserves prior records and
drains ownership channels; controls/status/counters use interface version 00600002.

All 26 host tests passed after adding descriptor arithmetic/changing/append
regressions: 117266 full-int32 angle pairs, all A32 bins, existing 56 changing
transactions, quarter tables and 942-feature frame append/error guards. The
independent Python full-table model also passed 37 direct packed-interface native
transactions using real eight-level 280-point and noise 942-point pyramids, empty
points, signed errors, legal corners and rotated out-of-bounds samples. A 256-point
odd-width call ending exactly at capacity 1000 is added before vendor gates.
Descriptor HLS synthesis/co-sim actual II, cycles, resources and integrated routed
timing remain pending. PS source and the ongoing frozen image benchmark are
unchanged. Optimized compiler flags are scoped to descriptor Csim/co-sim to avoid
the earlier long unoptimized full-image Csim runtime.

Image benchmark 20261012_122652_layer2_benchmark_56a61151 SUCCEEDED with all
24 exact native/Csim/RTL transactions and identical synthesis-RTL hashes before
and after testing. Actual eight-call RTL latencies: historical 280-point image
11.20 ms / 89.28 FPS, true resized noise pyramid (188762 candidates, 942 points)
11.60 ms / 86.24 FPS, zero pyramid 11.20 ms / 89.29 FPS, at assumed 100 MHz.
These are frontend reciprocals, not complete ORB/board results. Retaining the
historical per-layer ARM/cache/control model gives ordinary 15.44 ms / 64.75 FPS
and pressure 30.58 ms / 32.70 FPS. The pressure ARM extrapolation assumes linear
per-point cost; no board cache/DDR-contention claim is made. No PS code changed.

Descriptor independent Python/native stream test now has 38 passing transactions;
the added 256-point call uses odd width 463 and ends exactly at record 1000.
HLS descriptor gate uses the frozen 38-case input hashes, optimized C simulation,
synthesis and co-simulation, then records actual loop II and 64-bit AXI widths.
The finite double-buffer ownership, actual resource and cycles are still vendor
gates. Integrated routing and random-AXI repair remain required later.

Descriptor HLS 20261012_132126_descriptor_9cae63b8 SUCCEEDED: all 38 C/RTL
transactions exact, including 32 bins, 280/942/empty frame append, clipped edge
sampling, errors and 256-point odd-width call ending at capacity. Moment center,
symmetric pairs, BRIEF and clock counter are actually II=1; point record loader
II=2 and 64-byte feature writer II=8 match their record sizes and are overlapped
with much longer per-point compute. Four AXI masters are 64 bits. Ordinary
eight-layer descriptor latency sums to 261171 cycles (2.61171 ms at 100 MHz);
942-point noise descriptor latency sums to 859459 (8.59459 ms). These are separate
core co-simulation figures, not shared-DDR/frame/board latency. HLS estimates
17093 LUT, 12440 FF, 35 BRAM18 and 8 DSP. Estimated period is 12.077 ns, exceeding
the target; routed WNS is required before accepting hardware timing.

The outer descriptor gate retained a stale RUNNING marker despite terminal exit
0 and completed post-check outputs. The original record is preserved. Fresh
source/vector hash + II/interface/co-simulation audit
20261012_134054_descriptor_recovery_cfb915fc SUCCEEDED, with no HLS rerun or
weakened checks. Future gate child HLS runners use a separate PowerShell process
to isolate state. The exact cause of the stale outer marker is not yet established.

orb_timing.ps1 builds the complete two-core PL top using accepted frozen IPs,
one control interconnect and four AMD AXI interconnects with two upstream masters
each and PS7 HP protocol conversion. Layer raw/blur/next-image/points ports pair
with descriptor raw/blur/features/points respectively. No DMA or PL layer sequencer
is added. This is a 100 MHz timing/resource experiment before joint randomized
DDR/ownership and PS integration; no bit/XSA/ELF release or board programming.
All nets/constraints/setup/hold/DRC/hierarchy/congestion are checked from the
completed routed checkpoint using the corrected report workflow.

Integrated layer + exact descriptor route 20261012_134429_orb_100mhz_d4174613
SUCCEEDED at 100 MHz on xc7z015clg485-2. Actual complete routed top: 27033 LUT
(58.51%), 27169 FF (29.40%), 59 RAMB36 +18 RAMB18 =68/95 BRAM tiles (71.58%),
40/160 DSP (25%), 9633 slices (83.40%). Setup WNS +0.238 ns, hold WHS +0.035 ns,
TNS/THS zero; 50347/50347 routable nets fully routed, zero routing errors, zero
uncovered timing checks, no Error/Critical Warning DRC rows. Vendor warnings
remain in the retained DRC/methodology reports. No post-route physopt was applied.
Worst setup path is FAST score lane1 f_14 -> select_ln161_10: 13 logic levels,
9.522 ns delay (3.990 logic,5.532 routing), clock period10 ns. Descriptor HLS
12.077 ns estimate did not cause a routed violation in this build.

Actual retained hierarchy: layer 16390 LUT/13795 FF/50.5 BRAM/29 DSP; descriptor
8209 LUT/10530 FF/17.5 BRAM/11 DSP. AMD control/arbitration/reset consumes the
remaining logic/registers. Whole-top resources are authoritative; this newly
PL-owned backend increases total resources versus old ARM-descriptor R11.

Next protocol gate repairs the previously deferred ModelSim embedded-Python
stdio failure through task-local PYGPI_USERS bootstrap, before cocotb logging.
No installed library or global environment is patched. Child LIBPYTHON_LOC and
PYTHONHOME derive from the CPython DLL actually loaded by the project venv;
bootstrap records and checks actual DLL/version3.12.12. The new frozen gate
exercises 4-master descriptor and layer independently in one DDR address space,
27% randomized stalls, delayed write responses, 4 KB edges, invalid controls,
odd width/tail, capacity1000, partial errors and in-flight reset/restart.
It observes the actual internal ap_done pulse and requires every AXI response
already complete, rather than relying only on delayed PS polling. Targeted
protocol subsets precede native-Verilator bulk/frame/shared-contention tests;
they do not replace full regression or prove physical DDR/PS/board timing.

Datapath AXI 20261012_141855_datapath_axi_c7c63f51 FAILED in the final descriptor
256-point case at the test's counter bound, after five protocol transactions
passed (empty/capacity/error/corners/partial prefix). Direct done barrier, return
status and metadata fields reached the check; the final whole-DDR/count checks
did not run and this is not a descriptor protocol PASS. Layer testing did not
start. Actual embedded runtime provenance proves the project CPython 3.12.12
DLL is loaded. There was no logging initialization failure in this job.

The failed bound summed only ClockCycles(200) polling waits and omitted all
AXI-Lite control-read handshake clocks; the undercount grows with long jobs.
The test now measures actual simulator picoseconds /10000 per 100 MHz clock,
including configuration/poll/status overhead, uses the same real elapsed clock
for its timeout and requires internal cycles <= measured elapsed with no +1000
allowance. It records current stats and both timing counts before assertions.
All byte, transfer-count, 4 KB, reset and direct-response checks remain intact;
HLS source/RTL/IP and the +0.238 ns routed result are unchanged. The failed
record is retained and a fresh gate must pass before integration proceeds.

Datapath AXI 20261012_143039_datapath_axi_e0eb08c4 SUCCEEDED: six descriptor
and three layer directed transactions exact under 27% stalls, delayed responses,
4 KB edges, in-flight reset/restart, capacity/error/odd-width cases. Both actual
ap_done barriers required zero outstanding responses. Actual byte counts, all
DDR bytes/guards and real simulator elapsed-cycle bounds passed; project Python
3.12.12 loaded-DLL provenance passed. This is a targeted protocol subset, not a
full multi-frame/two-core/physical-DDR proof. A ModelSim teardown logger emitted
Bad file descriptor after passing tests; XML and task-specific results confirm
PASS. Future task-local stdio handling may be hardened separately.

Next design choice: computer/native C++ host scheduling and randomized byte DDR
model, two unmodified generated HLS datapaths, AMD-IP hardware interconnect kept
as routed. Native integration reuses established Verilator workflow. Testbench
enforces three raw/two blur owned slots, exact full frame append and actual AXI
write completion. Descriptor(n) overlaps image(n+1), with real AXI-Lite setup.
Only layer0 is injected; descriptors read actual upstream raw/blur/points.
DDR model shares one byte array with four paired HP arbitration groups, at most
one serviced memory beat per group/clock, and a configurable aggregate beat
budget. The planned 2-beat and 1-beat/27%-stall cases are bounded bandwidth
assumptions, not measurements of AMD interconnect/DDR PHY or board FPS. PS
firmware remains unchanged. Integration is not accepted until new gate passes.

Native harness preflight_native_20261012_145819 passed source/vector provenance,
generated-register/wrapper checks, C++ compilation and independent pin-stub DDR
tests: paired-HP shared reads, stalled response stability, narrow strobed writes,
delayed final B, byte counters, illegal 4 KB crossing and ownership rejection.
This validates the authored memory test model, not either HLS RTL or frame FPS.

Native frame 20261012_150028_native_frame_ea07bffa FAILED before HDL compilation:
Windows .cmd rejected the long source-list command. All preflight checks passed,
no RTL simulation ran. New runner uses a native Verilator sources.f argument
file and retains compact failure/log locations. HLS/PS/retained timing unchanged.

Native frame 20261012_150123_native_frame_417920d6 FAILED in Verilator parsing,
not simulation: NEEDTIMINGOPT for vendor #0 initialization. The new runner uses
--no-timing for the explicit C++ clocked harness, after auditing all staged RTL
for numeric nonzero/expression delays. Generated RTL remains byte-identical;
transactions follow explicit reset. Preflight_native_20261012_150646 passed the
1023-zero-delay audit, DDR-model unit tests and actual two-core Verilator lint
(exit0). Vendor width/delay warnings are retained. Frame correctness/FPS still
requires the new full native build and run; no old failure is relabelled PASS.

Native frame 20261012_150835_native_frame_668febb2 FAILED at final executable
link: the Windows runtime referenced undefined sc_time_stamp(). Both HLS
generated models, runtime objects and model archive compiled; no full frame
ran. The authored C++ harness now provides the callback and advances real model
time by 5000 ps per half-clock. Generated RTL/IP and PS firmware are unchanged.
Preflight_native_link_20261012_151826 linked the new harness to the existing
actual two-core model/runtime archive and passed 20-clock reset/idle startup;
source/archive hashes and logs are retained. Future fresh gates require this
actual link/reset smoke before full simulations. This is neither frame byte
acceptance nor a physical/FPS result; the original FAILED record is retained.

Native frame 20261012_152016_native_frame_4d511b31 FAILED in the first image
comparison after successful compile/link/reset. Diagnostic
diagnose_native_20261012_153241 proved the test controller passed budget=-1;
the fixed-profile layer requires the actual layer budget. Core correctly wrote
status=1, zero image bytes and 128 summary/stat bytes, leaving blur untouched.
The early AXI-Lite AP_RETURN read also sampled the old zero before the return
latch updated. The test controller now sends 217/181/151/126/105/87/73/60 and
crosses one clock after direct ap_done before reading the return register.
The direct all-responses completion barrier and exact byte gates remain intact.
Budget metadata is checked against the frozen benchmark controls. HLS/PS/RTL
and the retained +0.238 ns route are unchanged; the failed result is preserved.

Diagnostic diagnose_native_20261012_153604 SUCCEEDED for real-image layer0 only:
356024 cycles, all blur/resize/points/summary/guards exact, 64 selected points;
691200 raw read bytes, 691200 blur write bytes, 480000 resize write bytes,
1152 points+summary+stats write bytes. Actual dataflow counter355956 bounded by
observed elapsed cycles. This is a single-layer diagnostic using the original
compiled two-core model; descriptor/whole-frame acceptance and FPS are pending.

Native frame 20261012_155803_native_frame_d49eeb08 SUCCEEDED: six complete
960x720/eight-level frames across two DDR service profiles, 48 layer calls and
48 descriptor calls, 2444 exact 64-byte records. Actual upstream blur/resize/
points fed descriptors in common DDR; only layer0 input was injected. All
per-layer outputs, full appended features/guards, ownership, 4 KB bursts,
stable handshakes, AXI counts and direct final-response barriers passed.
Fresh independent result/log/offset/traffic arithmetic and frozen test/RTL
hash audit passed. Neither HLS/RTL nor PS firmware changed.

At assumed 100 MHz, 2 shared 64-bit DDR beats/clock (one/group maximum), no
added random grant stalls, with read initial0..5/write B2..31 clocks: ordinary
280-point frame1137272 cycles=11.37272 ms/87.92971 FPS; 942-point noise1328620
=13.28620 ms/75.26607 FPS; zero1120667=11.20667 ms/89.23257 FPS. At 1 shared
beat/clock plus27% randomized channel/service stalls: ordinary1271175
=12.71175 ms/78.66737 FPS; noise1581607=15.81607 ms/63.22683 FPS; zero1204355
=12.04355 ms/83.03200 FPS. Total R+W traffic respectively6544712,8462552,
5731128 bytes/frame, identical across profiles. Stall counters sum per-port
eligible waits; they are not unique elapsed-cycle counts.

The constrained pressure case leaves0.85393 ms to16.67 ms and misses the14 ms
engineering target. These are equivalent-interconnect computer timings with
actual RTL and control setup, not Zynq DDR-PHY/cache/board measurements. Three
inputs/two seeds do not establish representative-video P99/max or sustained
board throughput. Changed-image bulk/FIFO/protocol integration and final PS
visibility/release/board gates remain. Primary routed100 MHz stays retained.

Next bounded design experiment retains custom HLS datapaths and AMD PS7/AXI/
clock/reset, replays byte-identical accepted kernel input snapshots at8 ns,
checks exact CSim/co-sim and real II/64-bit interfaces, then builds the complete
125 MHz routed top. The runner records explicit child job identities, verifies
source hashes and reports actual clocks/setup/hold/coverage/DRC/congestion/
hierarchical resources. It does not reuse10 ns IP to claim125 MHz, project
125 MHz FPS from old cycles, replace100 MHz, modify PS or program the board.

100 MHz bit/source publication 20261012_171954_bit_publication_d17fcf25
SUCCEEDED using the immutable accepted routed checkpoint. Fresh setup/hold/
coverage/routing/DRC checks passed; bit header identifies s_wrapper/2024.2 and
7z015clg485, payload3510668 bytes. Generation/checkpoint-open time116018 ms.
Bit SHA256 a80fe3fdff930a3266b2d8701a9dfbc36319010e56744ba0d20245eda7c1303d.
The complete ZIP is6819188 bytes/689 files, CRC and all payload hashes verified,
including the original frozen fixtures. Its SHA256 is
310427dc143b05d8957f450d520663d1dfb669a9c0d338e90b59db3900a1158a.
Local branch codex/orb60-100mhz-2ppc-pl-descriptor committed as
9f3ffdc3dd7081dbea143c00c8d3406de3c0b4ba; GitHub push still returned403 for
ymmzseu. User-authorized ZIP fallback is ready with source/docs/reports/bit.
Publication integrity recheck passed475 files and the ZIP SHA. No paired new
PS ELF, XSA or physical-board test is claimed; the historical three-core ELF
does not configure this two-core bitstream.

125 MHz experiment 20261012_161953_frequency125_4a92a648 FAILED in the strict
full-top timing gate. Both actual8 ns HLS jobs passed CSim/synthesis/co-sim and
II/64-bit checks (21 layer and38 descriptor transactions). Child route
20261012_164534_orb_125mhz_f9e13b14 completed51274/51274 nets with zero routing
errors, actual clock8.000 ns and zero uncovered checks, but WNS-0.341 ns,
TNS-6.608 ns/56 failing endpoints, WHS+0.050 ns/THS0. Complete routed resources:
27817 LUT(60.21%),29048 FF(31.44%),68 BRAM(71.58%),40 DSP(25%),
10090 slices(87.36%). Worst reducer token_reg[42] -> best_score_165 CE path
has11 levels/7.772 ns: logic2.321 ns, routing5.451 ns(70.14%), initial net
fanout185 and clock skew-0.308 ns. This is an actual timing violation, not a
tool startup or report parser failure. The original FAILED state is retained.

Next bounded implementation choice: retain custom HLS algorithms and AMD
infrastructure; use Vivado post-route AggressiveExplore on a separate copy of
that completed125 MHz top. It targets the measured routing/fanout hotspot and
does not change HLS/RTL sources, clock requirements or timing exceptions.
The new runner freezes parent report/check helpers, verifies parent DCP SHA,
checks actual8 ns clock before/after, and requires fresh complete-top setup/
hold/coverage/DRC/routing/resources/congestion reports. This is a physical
timing experiment; new125 MHz protocol/frame/release/board gates stay pending.

First post-route physical experiment
20261012_173058_physopt_125mhz_6aecd654 completed AggressiveExplore in244159 ms
but FAILED the real setup gate: WNS-0.341 ->-0.039 ns, TNS-6.608 ->-0.467 ns,
failing endpoints56 ->17. WHS+0.050 ns/THS0,51282/51282 nets fully routed,
zero route errors and all check_timing categories zero; DRC contains warnings
without Error/Critical Warning rows. Complete resources27825 LUT(60.23%),
29048 FF(31.44%),68 BRAM(71.58%),40 DSP(25%),10091 slices(87.37%). The new
worst path is best_score_17[2] ->best_score_203[1] CE,12 levels/7.633 ns,
logic2.438/routing5.195 ns. The negative39 ps is not relabelled as PASS.

The second and final bounded physical pass uses Explore on a separate copy of
that completed improved checkpoint. Runner validates agreement with the frozen
archive, preserves its SHA and8 ns requirement, records pass lineage/directive,
and repeats the same full-top strict acceptance. Neither PS nor HLS sources
are changed. If it still fails, further closure requires a separately validated
datapath/implementation change rather than an unbounded physical retry loop.

Second and final post-route physical experiment
20261012_174304_physopt_125mhz_17bedb6f completed Explore in97139 ms but
FAILED actual setup: WNS-0.039 ->-0.034 ns, TNS-0.467 ->-0.187 ns,
failing endpoints17 ->10, WHS+0.050 ns/THS0. All51283 routable nets are
fully routed without errors; actual clock8.000 ns, all12 check_timing
categories zero, no Error/Critical Warning DRC rows. Complete resources:
27826 LUT(60.23%),29048 FF(31.44%),68 BRAM(71.58%),40 DSP(25%),
10091 slices(87.37%). The reducer best_score_17[2] ->best_score_203[1]
CE remains the worst path,11 logic levels/7.628 ns data delay. Only5 ps
was recovered in this pass. The bounded physical comparison is concluded;
125 MHz remains rejected and no125 MHz bitstream is offered as accepted.
Retained100 MHz bitstream/source/kernel inputs are unchanged. Further125 MHz
closure would require a separate measured HLS selection/update restructuring
and its functional/protocol/complete-route gates. PS integration is deferred.

Comparison ZIP refresh 20261012_180418_100mhz_with_125comparison_b851dd23
FAILED the publication verifier before ZIP creation or Git staging: the child
Windows PowerShell5.1 could not resolve Get-FileHash in the inherited module
environment. The original100 MHz ZIP/bit are unchanged. Recovery discovers
pwsh via PATH, retains the same unmodified hash gate, and permits only the
declared uncommitted publication overlay into a new output job. No HLS/RTL,
clock, resource/timing post-check or frozen input is changed by this repair.

Comparison publication recovery
20261012_180704_100mhz_with_125comparison_80aa0462 completed ZIP_READY.
All564 published file hashes,778 ZIP payload entries/CRC, complete original
frozen input manifests and unchanged100 MHz bit SHA passed. ZIP7137629 bytes,
SHA256355b292480d43fc6984532bcbb25b55a6fb68019ab6a7601202841f391b4146d.
Local branch commit783516e0a4b279f10356ae95f4a780749f3f3176 contains concluded
failed125 MHz reports,8 ns HLS evidence and bounded reproduction scripts.
No further GitHub push was attempted; prior403/authorized ZIP fallback applies.
Only100 MHz is accepted; PS/ELF and board performance remain deferred.

PS firmware integration remains deferred by the user's latest instruction.
The installed Vitis2024.2 tree contains the HLS-only marker and no discovered
Cortex-A9 GCC toolchain; Vivado2024.2 has xsct-trim and standalone BSP sources,
but those alone are not an accepted embedded application build. No PS source
was changed, no BSP/ELF build was launched, and no historical ELF was relabelled
as paired with the new bitstream. The existing100 MHz source/bit ZIP remains
the delivered artifact; the separate125 MHz physical experiment is unaffected.

After equivalent baseline acceptance: balanced/pipelined FAST extrema,
II=1 reduction with real dependency handling, explicit 64-bit output, generated
21-bit resize ROM, a 100 MHz implementation, and an 8 ns/125 MHz comparison.
Then the shared-read 2PPC layer engine, exact PL orientation/BRIEF, buffer
ownership/frame aggregation, integrated DDR contention/native-Verilator gates,
and final routed release. Physical P99/max <=16.67 ms and sustained 60 FPS remain
separate board acceptance gates.

User-authorized independent GitHub publication completed at
https://github.com/ymmzseu/fpga-orb-r11-orb60 (private, main). Commit
152059a5d24a53a84d1b6d3e3b469f2a0f5ae735 and annotated tag
orb60-100mhz-20261012 preserve the accepted source/bit/report snapshot.
All771 Git blobs match the remote tree; the downloaded100MHz bit SHA256
remains a80fe3fdff930a3266b2d8701a9dfbc36319010e56744ba0d20245eda7c1303d.
565 ORB60 and199 historical source hash checks pass. Legacy Git checkout
line-ending conversion was restored to manifest bytes in the new clone,
with attributes preserving those bytes. No new CAD or board result is inferred.

Architecture stage1 authored implementation: eight independent HLS score banks
with real recurrence, LUTRAM payloads,256-leaf exact tournament, generator-owned
lossless paired-X/single-Y run tables, and separate moment/angle/BRIEF actors.
Custom HLS is selected for these changes; AMD infrastructure remains retained.
27host tests and38independent Python-vector/native descriptor cases pass.
The native harness now binds actor busy/FIFO real-handshake occupancy probes
without editing RTL or control registers. New HLS/AXI/frame/route acceptance
and4PPC implementation remain pending. See docs/ARCHITECTURE_STAGE1_ZH.md
and scripts/architecture_stage1.ps1. No new FPS/WNS/resource claim is made.

Architecture stage1 job20261012_202829_architecture_stage1_ceed5a35 completed
SUCCEEDED/HLS_GATES_COMPLETE:27host,38native descriptor,21layer/38descriptor
co-sim exact; eight score banksII=1, three descriptor stages and64-bit interfaces
verified. HLS-only estimates are recorded in docs/ARCHITECTURE_STAGE1_HLS_RESULTS_ZH.md;
new frame/route acceptance remains pending. The user's updated optimization plan
requires read-only200unique-endpoint/50physical-net/control-set baseline diagnostics,
then candidate randomAXI, expanded native shared-DDR profiling including40-60cycle
first-read latency, and complete route before larger architecture changes.
scripts/architecture_protocol.ps1 sequences diagnostics and isolated protocol gates;
long jobs launch/end according to the user's preference, without repeated polling.

Diagnostic recovery20261012_213518_architecture_protocol_525e560e failed at
report export: Vivado12-1365 rejects report_timing -of_objects together with
-max_paths. The authored script now selects200paths/nworst1 in get_timing_paths
and exports precisely that collection without repeated selection flags. The
strict200section/unique-endpoint Python checks remain; no HLS/RTL/checkpoint,
constraints or acceptance gate is changed. Original failure logs are retained.

Job20261012_213756_architecture_protocol_07011afd completed diagnostic export
and randomizedAXI at2026-10-12T12:44:31Z. Its protocol child675d818f passed
descriptor6/layer3transactions plus reset and final-response barrier checks.
Diagnostic source-path fanout aggregation was found to include the clock despite
-path_type full; the revised parser bounds actual source/destination resource
rows, including inverted pin annotations, without changing the original raw
report/checkpoint. New200-path/50-net independent summary reports FAST datafanout25,
selection cones184; original clockfanout29163 is not a data-path result.
Native harness adds actual AXI/outstanding/service counters and four DDR profiles
(original two preserved, plus corresponding40-60cycle first-read eligibility).
New actual-RTL wrapper lint and DDR pin-stub checks passed in native preflight
af0b0e33; full multi-frame regression and candidate routed results remain pending.

Native job e694713b completed SUCCEEDED/COMPLETE at2026-10-12T13:07:41Z:
12frames exact across original two DDR profiles and both40-60cycle-delay variants.
Ordinary/pressure:11.36729/13.23842ms (2beat,0stall),12.71047/15.81061ms
(1beat,27stall); high-delay pressure28.90985/30.83617ms. Original pressure
latency reductions are only0.360%/0.035%; HLS descriptor6.2% max reduction is
not a frame claim. High-delay patch ports max outstanding2, with poor service
utilization; actual cross-row issuer/receiver prefetch is now a higher priority.
See docs/ARCHITECTURE_STAGE1_FRAME_RESULTS_ZH.md and comparison221738_stage1_frame.
Native FIFO blocked pins can already be HLS-prequalified; zero observations do
not prove no backpressure. Preserve waits/occupancy/busy interpretation limits.
Complete100MHz route now accepts an explicitly hash-matched FrameJob and optional
extended200-path/50-net/control-set diagnostics. Aggregate TNS/THS/failing endpoint
metrics are parsed strictly from the design timing table and retained. No new
routed result/bitstream or board result exists at this point.

Route ae11f62c actually completed100MHz CAD/hard gates: WNS+.270/WHS+.040,
TNS/THS0,56445/56445nets routed,0route errors,0unclocked/unconstrained endpoints,
no seriousDRC. Root job retained FAILED due a diagnostics parser self-feedback
clock-pin ambiguity, not a design failure. Recovery225220_stage1_route_diagnostics_recovery
strictly revalidated immutable source/IP/tool/report/checkpoint evidence and the
200endpoint/50net diagnostics without rerouting or relabeling the original failure.
Actual routed resources30529LUT,29693FF,67BRAM,55DSP,10534Slice91.2%,1075controlsets.
Selection/tournament module6053LUT/16DSP vs3229/0 previously; generated tree memories
auto-bank3 with constant-multiply address mapping. New bounded custom-HLS parity
bank2 candidate explicitly partitions tree[512] and retains true dependencies and
II<=2; eight score banks/image2PPC/interfaces/algorithm remain unchanged. It has no
inherited route/frame result. scripts/tournament_banking.ps1 freezes and tests it.
Stage1 resource/frame tradeoff is not selected as a new release; descriptor real
cross-row prefetch remains a performance priority before further4PPC integration.

Two-bank HLS job5e01aac7 and wrapper7dbd9503 completed exact21co-sim, eight
score banksII1 and actual2treebanks/BuildII2. Relative HLS estimates:-2784LUT,
-2302FF,-5BRAM18,-6DSP; max356045cycles unchanged. User updated plan with a
code-only Slice专项, then explicitly requested fewer repeated baseline tests and
more directional optimization experiments. Accordingly, retain prior baseline
evidence and perform early100MHz two-bank full-route resource/timing evidence,
plus two independent descriptor exact-CSim/synthesis width probes, deferring
candidate protocol/frame/final-release gates. No failed check is weakened.
Width modes0(default original),1(moment21),2(moment21+CORDICxy43/z34) are build
parameters only, checked against a full integer range proof and identical source
snapshots. Use NoExport for fast synthesis probes. See docs/SLICE_DIRECTION_PROBES_ZH.md.
There is no new width RTL/frame/routed/board claim. Current HLS/RTL freezes remain
unchanged; only authored C++/types and build scripts are modified for new probes.

2026-10-13 direction probes completed: two-bank full route1cac1aa7 passed
WNS+.316/WHS+.046,TNS/THS0 and complete hard gates/extended diagnostics.
Actual top28902LUT/28748FF/64.5BRAM/39DSP/10239Slice88.65%,1058controlsets:
versus auto3bank -1627LUT/-945FF/-2.5BRAM/-16DSP/-295Slice/-17controlsets.
Still606moreSlice than original release; FAST lane1 remains worst13levels9.408ns.
Width probes73f38f26/5bdc19d5 each passed38exactCSim/II1/AXI/FIFO gates.
Mode2 estimate -1171LUT/-127FF/+2DSP,BRAMunchanged; co-sim/route pending.
Selected width2 original frozen probe is regenerated using explicit SourceProbe,
which does not confer prior co-sim acceptance; then paired with accepted2bank IP
for directional100MHz full route. No new frame/bitstream/board claim.

Performance work advances independently to custom-HLS cross-row manual burst
prefetch2/4/8. Separate request issuers and patch receivers retain block depth2,
exact patch bytes/point checks/error drain and unchanged MMIO requirements.
Initial host ownership model passed38independent exactcases; no credit/backpressure
claim. Run candidate-only CSim/synthesis/co-sim/IP matrix and inspect actual
actors/II/adapter config/registers; subsequent randomizedAXI/native frame must
measure real outstanding and high-delay pressure gain. Default prefetch0/width0
preserves existing loader/types. See docs/DESCRIPTOR_PREFETCH_EXPERIMENT_ZH.md.
Do not rerun retained baseline or publish directional candidates as releases.

User2026-10-13 requests an integrated major-hotspot optimization and fast4PPC
entry, then explicitly authorizes autonomous long-job continuation while asleep.
The earlier launch/end/no-poll preference is superseded for this run. No PS/board
authorization is added. No subagents were requested.

Integrated4 job7b296a51 passed fresh21layer/38descriptor C/RTL, trueII1, randomAXI
e33c74db, exact12nativeframes0e71ced4, fullroute6ff9e071 and production-source
serializer17legal-mask randomAXIS/reset2b4786a8. Device015/100MHz, statsversion
0x600003 identifies4PPC while externaltop/regmap/record algorithms remain exact.
Actual34671LUT/32558FF/71.5BRAM/44DSP/11391Slice98.62%,1089controlsets,
WNS+.579/WHS+.010,TNS/THS0. High-delay limited-DDR942points14.78215ms67.65fps
modeled vsold30.83617ms; normal9.98718/12.66252ms in originalDDRprofiles.
Computer gates do not prove board/representative-videoP99. Passed-checkpoint bit
hash640fdfe6be0698120cbaa9bee73e2f97e12f736505b417817fa41a0b5d08cee4 retained.
Source/RTL/frame/IP hashes paired in bit/joint_validation.json; no PS/programming.
See docs/INTEGRATED4_RESULTS_ZH.md for direction decisions and exact evidence.

Next consolidated candidate653984f3 keeps the accepted backend d3f49663 and
serializer behavior, adds two-credit image block DATAFLOW for DDR read/emit and
collect/write, plus BRAM binding for primary intermediateFIFOs. This follows
measured full source/blur FIFOs and only159freeSlices; no globalCE/reset rewrite.
Host21 exact pass, newHLS91b49663 is frozen/running; no inheritednewroute/frame.
Simulation profile capacity512 and nesteddataflow discovery support newactors
without adding productionMMIO. Revalidate newtiming/resources/pressure latency;
retain previouspassed4PPC if this tradeoff has no benefit or fails.

2026-10-13 integratedIO653984f3 now passes new21exactlayer C/RTL/II gates,
newrandomAXI548e2c95 with explicitly verified identical d3f descriptor reuse,
fullroute2c712921, sameproduction serializer2b4786a8, and12nativeframesbac72e5f.
Actual35347LUT/32979FF/74BRAM/44DSP/11405Slice98.74%,1104controlsets;
WNS+.188/WHS+.044,TNS/THS0 and extended200paths/50nets strictpass.
This is a performance improvement, not resource savings: original4PPC11391Slice
increases14. Worst path now reset-to-BRAM reset326loads,8.581ns routing.
Worst modeled942point frame12.59037ms79.43fps, allmatching12frames faster;
engineering14ms pass and board/P99/PS still unverified. Selected100MHz bitSHA
46c36be6a8758926f576fe6761434adddbf646ab2ed745709b1c0513b101abe2.

Native metricV1 pending counter omitted RVALID cycles, making conditional means
invalid. Raw historical evidence remains unchanged. MetricV2 separately counts
all outstanding-read cycles and waits without RVALID;12frame stat-only replay
matches original0dcccb9f cycles,traffic,selected,alllayer records exactly.
Counter consistency and100/125MHz DDR time normalization pass pin-model tests.
Norm keeps HP800MB/s, aggregate800/1600MB/s, initial/read andB delays in ns;
100MHz scheduler/PRNG stays exact,125MHz quantizes10ns service epochs and delay
ceil to8ns edges. Cross-frequency stochastic events are not identical traces.

Source/report/fixture package prepared in publication clone. Fresh3.12.12venv
and reproduce_integrated4 Inputs pass independent38case/32bin golden from
originalconstants.hpp. All hardware gates were independently run; do not claim
the new All orchestration was rerun. Main/historical100MHz artifacts preserved.
125MHz comparisona5b3269c regenerates2/4PPC+backend at8ns; allHLS21/38pass,
actual125MHz route/native gates running. Route2 first failed only for carrier
key mismatch, preserved under route2_startup_failure; fixedandfreshroute running.

Frequency a5b3269c COMPLETE: fresh8ns2PPC c9702f6b,4PPC f2546027,
descriptor2730a8cf exact21/38/II gates; randomAXI, reset/barrier, normalizedDDR
12nativeframes each d6a76172/543fa67f; fresh8ns17mask merger+randomAXIS pass.
125MHz fullroute2 4d17f0b7:28567LUT/31929FF/60.5BRAM/38DSP/10328Slice89.42%,
1102controlsets,WNS+.155/WHS+.038. Route4 6685ae8e:35551LUT/36122FF/74BRAM/
44DSP/11437Slice99.02%,1127controlsets,WNS+.167/WHS+.015. Bothstrictallgates
and extended200/50 pass,TNS/THS0. Newworst125 path tournamentBRAM feedback,
4PPC7levels3.267nslogic4.200nsrouting98loads. No further7ns probe this milestone.
Worstmodel2PPC12513.554ms;4PPC12512.063064ms82.90fps,4.19%fasterthan4PPC100
worst12.59037. Select4PPC125fastestcomputer candidate,retain4PPC100 pairedbit.
125bitSHA b892d2302049ce48077e82eada0bdd331eb40dc8b708b3605fd1b33f4a5d1fef.
Source/regdefinitions/pair checked independently across clocks; noPS/board gates.

Git publication first100MHz commitc0ccd7111f173bbb34d72d70cbb9c5d990302804
remotelyverified throughGitDataAPI aftergithub.com transportfailed and transient
oneblobHTTP502. TreeSHA/commitSHA exact; one missingblob recovered, oldbranch
parentlease checked, mainunchanged. Preserve originalfailed upload evidence.
100MHz ZIP23.7MB/1759files SHA c77b85c0ecbbef24c753565eba7d2f48ed9c9cc5641361c4bb79689309364245.
Final125comparison/bit append andcombinedpackage publication pending.

Final delivery2026-10-13: both100/125MHz pairedbits and allcomputer evidence
published to codex/orb60-4ppc, exactremotecommit e2aa82627af93ccff34c3b6b1d8c004458853bd8.
Main/historicalbaseline unchanged. GitAPI400 on125bit transport retained as
failed evidence; eventual tree/blob availability and exactcommitSHA verified,
noforce/no weakenedcheck. Complete32.4MB/2877file ZIP verifiedbyte-by-byte,
SHA161052655e22a584193c066caba852cdbaa0ea7320c720fa7a2d561da0ab66a1.
See build/optimized/publication/integrated4_final_20261013/delivery.json and
orb60_4ppc_100_125mhz_source_reports_bit.zip. No longcompute jobs remain.
This integrated4PPC+125comparison milestone is complete. Raw-load moment
fusion,2comparisonBRIEF,ResizeDDA,7ns andphysicalPS/board remain future scope;
no claim of board60FPS/P99 or newpairedELF/XSA.

2026-10-13 next-plan continuation: custom-HLS raw receive/moment fusion
probe0f99e715 passed independent9048points/1191553beats and38record/error-prefix
host cases. Automatic365e603e CSim/synthesis/realII1/64bit-data/32bit-address/
8request/generated-no-raw-block checks pass; HLS delta versus2730a8cf is
-1026LUT/-736FF/-4BRAM18/-1DSP. Not a routed resource/FPS claim.
ExplicitDSP82cb160c passedCSim but clang frontend crashed atHLS reflow;
matrix remainsFAILED and originalevidence retained. Only automatic candidate
continues, via freshSourceProbe C/RTL/IP plus protocol/native/fullroute.
See docs/RAW_MOMENT_FUSION_RESULTS_ZH.md and scripts/finish_moment_fusion.ps1.
User preference now: announce long-joblaunch and endturn; do not auto-poll.
Accepted release e2aa826 and bothpublishedbits remain unchanged; PS/board deferred.

Fusion accept4180a258 verified COMPLETE after user reports PID29676 ended.
Fresh8ns fba5c20d passed38exactC/RTL/IP, realII1, architecture/eightcredits/MMIO;
freshdescriptor randomizedAXI98322610 passes with unchanged-layer hash reuse.
Native03c665ef12frames exact and matching baseline bytes/counts/profiles.
Full125MHzroute a69fb5e4 hardgates/extended200paths50nets PASS:
35145LUT/35556FF/72BRAM/43DSP/11353Slice98.29%,1108controlsets,
WNS+.288/WHS+.042,TNS/THS0. Actual versus release -406LUT/-566FF/
-2BRAM/-1DSP/-84Slice/-19controlsets; HLS savings not substituted for top.
Worstmodeled942point frame11.998792ms83.34FPS versus12.063064ms(-.533%).
Normal frames essentially flat with small mixed changes. Traffic remains8.46MB;
this is mainly a resource/timing win, not a large whole-frame speedup.
Retain fusedbackend as candidate for later Slice-combination gates; no newbit/PS/board.
Independent Slice job57e7d94f/PID32312 launched separately with frozen
38/36bit tournament keys and mode3 BRAM-point-store alternatives; no polling
without user completion notice. Its route comparisons keep oldbackend2730a8cf
fixed to isolate frontend Slice/timing changes, then combined frame/route must
run with fba5c20d before any joint release. See docs/SLICE_COMPACT_STAGE2_ZH.md.

Slice57e7d94f partial inspection after user notice: mode2fresh03e05c30
exactC/RTL/IP + complete125route829043c3 passes allhard/extendedgates.
Fixed oldbackend2730a8cf top34919LUT/35972FF/73BRAM/44DSP/
11380Slice98.53%,1113controlsets,WNS+.248/WHS+.027,TNS/THS0.
Only57Slicesaved versus published11437; this is not fusion-combination proof.
All3probes passmillion-key/67sorted-grid/21CSim/II/storage gates;
mode3fresh69f26095 C/RTL accepted, routebbfaee64 stillRUNNING atsinglecheck,
main32312 androutewrapper29076 confirmedlive. Wholeexperiment notcomplete;
no newpoll orduplicate launch. Await user completion notice, then compare
mode3 actualSlice/BRAM/timing before newprotocol/frame/joint-route selection.

2026-10-13 ACZ7015 simulation-capacity update completed (separate from HLS optimization).
New entry scripts/board_ddr_frame.ps1 derives aggregate DDR capacity from the
frozen PS config:32bit/533.333333MHz ->4266666664bytes/s. Each64bit HP read/write
channel is independently limited to one beat per fabric clock (800/1000MB/s
at100/125MHz). Existing legacy800/1600MB/s command behavior remains unchanged.
100MHz board_ddr_efcdae87 and125MHz board_ddr_ced10303 both SUCCEEDED/COMPLETE:
24 new capacity-model frames exact,6 legacy replay frames preserve cycles,
traffic/layers/AXI/FIFO statistics; pin-model rate/duplex/backpressure/drain and
configuration guards pass. Cached Verilator RTL/wrapper/registers were byte
paired before relinking the new harness in isolated scratch directories.
No HLS/RTL/PS/bitstream/route change or physical-board effective-bandwidth claim.
DDRI pairing is recorded, not cycle-accurate; bank/refresh/turnaround and CPU
contention remain unmodeled. See docs/BOARD_DDR_CAPACITY_MODEL_ZH.md.

2026-10-13 Slice57e7d94f finished SUCCEEDED/DIRECTIONAL_ROUTES_COMPLETE.
Mode3 routebbfaee64 also hard-gate PASS:34748LUT/35708FF/81BRAM/44DSP,
11465Slice99.26%,1142controlsets,WNS+.260/WHS+.037,TNS/THS0.
Reject mode3 for resource headroom despite passing route; keep mode2 with
11380Slice98.53%. Neither frontend result yet substitutes for a joint fused
backend acceptance. Latest user steering supersedes launch/end/no-poll:
autonomously advance the plan to maximize real routed frequency, no PID report.
New frequency_headroom authored snapshot combines mode2 and moment fusion,
plus exact A32 reciprocal quantization and measured-control-path AMD slices;
AMD Clocking Wizard derives PL clocks from100MHz PS FCLK. No generated RTL
edits or timing exceptions. First target150MHz, with bounded adjacent tiers.
Fast-A32 host golden passed all23592960 valid angles plus1000000 full32 and
20 wrap/boundary cases. HLS/protocol/frame/route evidence still pending.

2026-10-13 frequency_pair_db4fcbb9 completed150MHz joint computer gates:
descriptor3c1f808b + layerd0f9b7ad, structure/MMIO/II, freshprotocol3251229c,
native14009231 exact12frames, fullrouteea031cb2 hardgates and200paths/50nets PASS.
34894LUT/36886FF/70.5BRAMtile/44DSP/11420Slice98.87%,1133controlsets,
WNS0.000/WHS+.041,TNS/THS0. Zero setup margin is not the+.2ns engineering goal.
Modeled frame maximum11.680690672ms with same800/1600MB/s as fused125 reference;
normal wide6.354137691ms, pressurewide7.154584378ms. Separate1GB/s capacity
jobdff2015e passes12new frames and3legacy replay frames; no board FPS claim.
joint_result.json validates exact pair/source/clock/route/frame; no newbit/PS.
Protocolbeb68d22 failed at0ps because cocotb's default clock rejected odd6667ps;
explicit floor/ceil halfperiod fixed the harness, then fresh3251229c passed.
Initial pin model6000ps test used40cycles instead of400ns; retained failure,
corrected reference-time observation, full10000/8000/7000/6667/6000/5000ps pass.

New measured150MHz critical path is bank2 token[45]→score CE,7levels6.105ns.
frequency_local_scores unrolls independent per-cell comparisons, leaves only
payload any-update reduction; same-cell and tie semantics preserved, no false
dependency pragma.67host sorted-grid/golden pass. New6ns layerc70afb11 C/RTL
running under pairedrooted118677, uses immutable6ns descriptoreeb1fc19 checked
against matching author headers/reference/vector hashes. Original-bank6ns
pair3dff35b6 C/RTL/II/MMIO PASS; freshprotocol pending, keep as timing control.

Latest steering: optimize whole-frame speed primarily, use4GB/s DDR capacity,
clock frequency is only a means. Explicitly do not rerun125MHz; retain its old
4266666664bytes/s history without pretending exact4000000000bytes/s comparison.
150MHz4GB/s model passes12new frames +3legacy replay: normal5.54077–5.86739ms,
pressure5.72213–6.09335ms. Only descriptorlevel6 slightly exceeds next-image
duration; image pipeline dominates, earlier restricted-DDR bottleneck moved.
Original-bank166MHz routed0bdc0bac FAILED WNS-.398/TNS-91.721/825setup endpoints,
worst8levels6.083ns tournamentBRAM read→write. Keep failure, not release/board claim.
Local-bank166 sourcec70afb11 II1/21C-RTL/26comparators×8 verified, freshlayerprotocol
11e3a029 with immutable6ns backend protocol reused after strict period/hash checks;
native9eea217a12frames PASS, fullroute70987753 RUNNING,4GB/s evaluation pending.

Measured throughput hotspot: scan_front4_quads_Pipeline_1 row initializer is
70-iteration memset,72cycles per row. Newfrequency_row_init unrolls explicit
7x10 and3x6 zero writes, same algorithm/state values. HLS150MHz paira3d021cf
RUNNING, accepted150 backend3c1f808b reused by exact dependency/vector hashes.
This isolates same-clock throughput change; no baseline125 repeat. Structural,
AXI/frame/4GB/s/fullroute must pass before retention. See SPEED_ROW_INIT_STAGE_ZH.md.

Local-bank166MHz route70987753 finished FAILED: WNS-.398/TNS-23.125/
197setup endpoints,hold+.036/THS0;36068LUT/37956FF/71BRAM/44DSP/
11404Slice98.74%. Score CE bottleneck improved, tournament read/write now
8levels6.085ns. Both166MHz shapes fail timing; their frame models are references,
not releasable clocks. No further frequency tier launch under speed-first steering.
150MHz row-init HLS removes actual72cycle helper; C/RTL still running.

Row-init150 paira3d021cf HLS finished21C/RTL transactions and IP export PASS;
fresh structure gate confirms serial72cycle helper gone, realbankII1/buildII2,
same register definitions/AXI64. Freshfrontend randomAXI/reset/B-response
protocolce88cf8c PASS, unchanged150backend source/test/RTL hashes reused.
Nativeframee1e9c565 PASS12exact frames. Complete150routee192c8da and exact
4GB/s capacity evaluation run in parallel; no retained timing/speed claim yet.

Row-init150 nativee1e9c565 and4GB/s capacity pass12exact frames each; matching
same-clock old150 DDR profiles show normal4.87011–5.60231ms and pressure
5.27982–5.98019ms. Whole-frame improvement is4.5–12.1%normal,1.9–7.7%pressure.
Routee192c8da FAILED WNS-.103/TNS-.103/1setup endpoint;hold+.025/THS0.
35040LUT/36872FF/70.5BRAM/44DSP/11420Slice98.87%. Worst tournamentBRAM
read->write8levels6.438ns; no releasebit or passing-clock claim for this candidate.

New frequency_speed_joint author combines registered tournament reads(latency2)
and continuous raw-moment receive(no31row drains), retaining row zero semantics.
Descriptor dac5ff1a independent9048points/1191553beats +38records and fresh38
C/RTL pass; actual ReceiveRawMomentWordsII1. Firstfrontend61c59e5f buildII3
does not satisfy retainedII2 gate. Secondsource separates true distance1 root
update after node255..2 build; new bounded synth probe pending. No dependency
exceptions or generatedRTL edits. See docs/SPEED_JOINT_STAGE_ZH.md.

Root-separated tree probe also actualII3; reject this schedule, originalII2
gate stays unchanged. Thirdsource restores original RAM read latency/build
order and splits36bit winner comparison into4parallel9bit chunks plus balanced
lexicographic combination.67sorted-grid cases +1000300 independent keys pass.
New bounded synth probe3 runs on frozen new inputs; descriptor dac5ff1a is
unchanged. Do not reuse initialfrontend61c59e5f as the retained source.

Probe833cf4d4 PASS new-source21Csim+synthesis actual BuildII2/bankII1 and
4x9bit comparison nets. Fresh frontend C/RTL/export replay of that frozen
probe runs, no dependency exceptions. New descriptor C/RTL38transactions
total697063->599189cycles(-14.04%) vs same150old descriptor; this is isolated
core evidence, not an end-to-end or physical-board improvement claim.
New bit guard supports only accepted150MHz joint/source/IP/4GB/s pairing;
old100/125 release scripts unchanged. Static old150 validation passes without
any baseline rerun or bit generation. AMD exact translate_off deadlock-monitor
export delta alone is allowed/recorded; any synthesizable HDL difference fails.

Speedjoint pair e7c3b8e6 fresh21/38C-RTL +protocol10e45748 +native and4GB/s
12frames each PASS, but route9e06a605 FAILED WNS-.351/TNS-9.852/85setup
endpoints;hold+.036/THS0.34914LUT/36818FF/70.5BRAM/44DSP/11455Slice99.18%.
Chunk comparator reduces worst logic8->5levels but routing rises(total6.690ns).

Latest explicit steering: DDR bandwidth is sufficient; synthetic worst-DDR
performance no longer selects candidates. Use sufficient4GB/s speed primarily;
retain randomAXI/reset/Bresponse functional checks. Continuous receive66d8e6ce
candidate therefore retained: pressure5.14646ms andnormal4.87438ms in0stall/
0–50ns model, not physical-board or passing-route results.
Newfrequency_tree_read frontend uses registered treeRAM read2, root outside
node255..2 loop, trueRAWdistance2 declaration. Exhaustive physicalbank/address
proof validates distance>=2(noWAR/WAW); HLSprobe confirms BuildII2/bankII1/
actualsecondreadregister. Fresh frontend C/RTL/export runs paired with same
accepted66d8e6ce backend; no new125test or timing exceptions.
### 2026-10-13 4GB/s与速度选择口径

本轮最终150MHz完整路由abbeb794通过：WNS+.093ns、WHS+.036ns、
TNS/THS与setup/hold失败端点均零，覆盖/路由/严格DRC通过。
34990LUT、37001FF、70.5BRAM tile、44DSP、11452Slice(99.15%)、
1131控制集。最差转到FAST maximum_stage_2→NMS判断，6.248ns/8级，
布线68.116%；树RAM反馈不再最差。
同一routed DCP的150MHz bit已生成并通过重新配对/检查点SHA校验，
SHA256 b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60。
MMCM输入PS FCLK100MHz，PS/BSP/ELF/XSA与板测仍暂停。

用户明确实际DDR带宽足够：不再用合成27%随机停顿/400–600ns首读下的
最差耗时决定优化方向。随机AXI、复位、最终写响应仍是功能门禁。
选择按相同4GB/s预算、无合成停顿、0–50ns首读的普通/942点压力帧。

注册树读pair `20261013_194658_frequency_pair_3b981caa`的新前端
c57267c5已通过21个C/RTL及随机协议，后端66d8e6ce按严格SHA复用；
12原生帧、12个4GB/s帧与3帧旧模型重放全部精确。
普通4.87438ms/205.15FPS、压力5.14584ms/194.33FPS、空点4.80405ms；
较原150MHz同带宽普通/压力耗时减少12.03%/10.07%。
这些是RTL仿真值；完整150route abbeb794在运行，bit/PS/板测尚未完成。

