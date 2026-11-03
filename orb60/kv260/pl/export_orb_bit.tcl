# Invoked only after the Python static checker passed and its SHA was captured.
set job [file normalize $::env(KV260_UNIFIED_JOB)]
open_checkpoint [file join $job routed.dcp]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream -force -bin_file [file join $job kv260_orb_only.bit]
write_hw_platform -fixed -include_bit -force -file [file join $job kv260_orb_only_with_bit.xsa]
puts "ORB_ONLY_BITSTREAM_EXPORTED_NOT_PROGRAMMED"
exit
