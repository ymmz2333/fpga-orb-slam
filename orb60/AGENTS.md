# ORB60 development contract

This independent workspace implements the user-approved R11 migration and ORB60
plan. Root D:/pld rules apply. R11 archives and baseline inputs are immutable.

- Device xc7z015clg485-2, primary clock 100 MHz, exact 960x720 eight-level A32 ORB.
- Tools: Vivado/Vitis HLS/Vitis 2024.2. Host compiler discovered through the project
  environment; record actual versions with each job. No historical user paths.
- Custom HLS for image/descriptor datapaths; AMD IP for PS7/AXI/clocks/reset;
  software for scheduling/cache visibility. Change authored sources/generators.
- Keep existing 17 host gates and 11/13/14 RTL transactions. New datapaths require
  independent golden, CSim, synthesis, cosim, randomized AXI cocotb, OOC/top route.
- Foreground long jobs, bounded polling and concise reports. Do not infer PASS
  from tool exit alone. No automatic JTAG or nonvolatile programming.
- Record failed candidates and exact source hashes. Production timing is
  COMPLETE_UNVERIFIED; physical-board FPS remains an explicit board-stage gate.
