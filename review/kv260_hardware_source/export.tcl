# Export only the checkpoint whose digest passed the full-top static gate.
set job [file normalize $::env(KV260_DPU_ONLY_JOB)]
if {![file exists [file join $job static_pass.stamp]]} {error "Full static acceptance stamp missing"}
open_checkpoint [file join $job routed.dcp]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream -force -bin_file [file join $job kv260_dpu_points.bit]
write_hw_platform -fixed -include_bit -force -file [file join $job kv260_dpu_points_with_bit.xsa]
puts "DPU_ONLY_BITSTREAM_EXPORTED_NOT_PROGRAMMED"
exit
