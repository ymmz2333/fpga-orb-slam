# Only the first flop of each explicitly marked two-flop synchronizer is
# asynchronous. The second stage and all ordinary datapaths remain timed.
# XPM_FIFO supplies its own Gray-counter CDC constraints.
set_false_path -to [get_pins -of_objects [get_cells -hier -regexp {.*video.*/(req_sync_reg|uf_sync_reg|en_sync_reg|pattern_sync_reg|ack_sync_reg)\[0\]}] -filter {REF_PIN_NAME == D}]
