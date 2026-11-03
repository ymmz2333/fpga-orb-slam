# Reuse the exact accepted routed checkpoint; only change the PCAP-readable ID.
set job [file normalize $::env(KV260_TAGGED_JOB)]
open_checkpoint [file join $job routed.dcp]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.USR_ACCESS 0x4F525050 [current_design]
puts "ACTUAL_USR_ACCESS [get_property BITSTREAM.CONFIG.USR_ACCESS [current_design]]"
write_bitstream -force -bin_file [file join $job kv260_dpu_points.bit]
write_hw_platform -fixed -include_bit -force -file [file join $job kv260_dpu_points_with_bit.xsa]
puts "TAGGED_EXPORT_COMPLETE_NOT_PROGRAMMED"
exit
