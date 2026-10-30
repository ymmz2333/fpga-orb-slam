"""ORB60 AXI RAM, adapted from the established tb/common/axi_ram.py workflow.

Adds bus-lane-correct narrow transfers and inclusive 4 KB burst checks for the
R11 512-bit point/summary port. The shared workflow model is left untouched.

Supported features:
- 32/64/... bit data buses determined from the DUT signals
- single-beat and INCR/FIXED bursts
- byte write strobes
- independent read and write channels
- randomized ready/response delays
- direct preload/readback helpers

It intentionally models the AXI-visible behavior of memory, not DDR PHY
training, refresh, bank timing, or board-level electrical behavior.
"""
import random

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge


class AxiRamModel(object):
    OKAY = 0
    SLVERR = 2

    def __init__(
        self,
        dut,
        prefix,
        clock,
        reset,
        size=1 << 20,
        base_address=0,
        stall_probability=0.0,
        read_latency=(0, 3),
        write_response_latency=(0, 3),
        seed=1234,
        reset_active_level=1,
    ):
        self.dut = dut
        self.prefix = prefix
        self.clock = clock
        self.reset = reset
        self.base_address = int(base_address)
        self.mem = bytearray(size)
        self.stall_probability = float(stall_probability)
        self.read_latency = read_latency
        self.write_response_latency = write_response_latency
        self.write_random = random.Random(seed)
        self.read_random = random.Random(seed + 1)
        self.reset_active_level = int(reset_active_level)

        names = (
            "awaddr", "awlen", "awsize", "awburst", "awvalid", "awready",
            "wdata", "wstrb", "wlast", "wvalid", "wready",
            "bresp", "bvalid", "bready",
            "araddr", "arlen", "arsize", "arburst", "arvalid", "arready",
            "rdata", "rresp", "rlast", "rvalid", "rready",
        )
        for name in names:
            # Hand-written RTL in this template uses lower-case AXI suffixes,
            # while Vitis HLS preserves upper-case channel names (AWADDR,
            # WDATA, ...).  Supporting both lets the same DDR model exercise
            # generated HLS RTL without a project-specific wrapper.
            candidates = (
                prefix + "_" + name,
                prefix + "_" + name.upper(),
            )
            signal = None
            for candidate in candidates:
                try:
                    signal = getattr(dut, candidate)
                    break
                except AttributeError:
                    pass
            if signal is None:
                raise AttributeError(
                    "AXI signal not found; tried {}".format(", ".join(candidates))
                )
            setattr(self, name, signal)

        self.data_bytes = len(self.wstrb)
        self.awready.value = 0
        self.wready.value = 0
        self.bresp.value = self.OKAY
        self.bvalid.value = 0
        self.arready.value = 0
        self.rdata.value = 0
        self.rresp.value = self.OKAY
        self.rlast.value = 0
        self.rvalid.value = 0

    def start(self):
        return (
            cocotb.start_soon(self._write_loop()),
            cocotb.start_soon(self._read_loop()),
        )

    def _range(self, address, length):
        offset = int(address) - self.base_address
        if offset < 0 or offset + length > len(self.mem):
            raise IndexError("AXI memory access outside modeled range")
        return offset, offset + length

    def write(self, address, data):
        start, end = self._range(address, len(data))
        self.mem[start:end] = bytes(data)

    def read(self, address, length):
        start, end = self._range(address, length)
        return bytes(self.mem[start:end])

    @staticmethod
    def _next_address(address, size, burst):
        if burst == 0:  # FIXED
            return address
        if burst == 1:  # INCR
            return ((address >> size) + 1) << size
        raise ValueError("WRAP/reserved AXI bursts are not supported")

    def _allow(self, generator):
        return generator.random() >= self.stall_probability

    def _in_reset(self):
        return int(self.reset.value) == self.reset_active_level

    async def _write_loop(self):
        state = "AW"
        address = 0
        size = 0
        burst = 1
        beats = 0
        beat_index = 0
        response = self.OKAY
        delay = 0

        while True:
            await FallingEdge(self.clock)

            if self._in_reset():
                state = "AW"
                self.awready.value = 0
                self.wready.value = 0
                self.bvalid.value = 0
                continue

            if state == "AW":
                self.awready.value = 1 if self._allow(self.write_random) else 0
                self.wready.value = 0
                self.bvalid.value = 0
            elif state == "W":
                self.awready.value = 0
                self.wready.value = 1 if self._allow(self.write_random) else 0
            elif state == "B_DELAY":
                self.awready.value = 0
                self.wready.value = 0
                if delay == 0:
                    self.bresp.value = response
                    self.bvalid.value = 1
                    state = "B"
                else:
                    delay -= 1
            elif state == "B":
                self.awready.value = 0
                self.wready.value = 0
                self.bvalid.value = 1

            await RisingEdge(self.clock)

            if self._in_reset():
                continue

            if state == "AW" and int(self.awvalid.value) and int(self.awready.value):
                address = int(self.awaddr.value)
                size = int(self.awsize.value)
                burst = int(self.awburst.value)
                beats = int(self.awlen.value) + 1
                beat_index = 0
                response = self.OKAY
                if (1 << size) > self.data_bytes or burst not in (0, 1):
                    response = self.SLVERR
                if burst == 1:
                    last_address = (address & ~((1 << size) - 1)) + beats * (1 << size) - 1
                    if (address >> 12) != (last_address >> 12):
                        response = self.SLVERR
                state = "W"

            elif state == "W" and int(self.wvalid.value) and int(self.wready.value):
                strobe = int(self.wstrb.value)
                expected_last = beat_index == beats - 1
                if bool(int(self.wlast.value)) != expected_last:
                    response = self.SLVERR

                word_address = address & ~(self.data_bytes - 1)
                first_lane = address - word_address
                last_lane = min(((address >> size) + 1) * (1 << size) - word_address, self.data_bytes)
                allowed_strobe = ((1 << (last_lane - first_lane)) - 1) << first_lane
                if strobe & ~allowed_strobe:
                    response = self.SLVERR
                data_bits = str(self.wdata.value).lower()
                for lane in range(first_lane, last_lane):
                    if (strobe >> lane) & 1:
                        # HLS is allowed to leave byte lanes as X when WSTRB
                        # masks them off (most visibly on a partial final
                        # beat).  Decode only strobed lanes, exactly as a real
                        # AXI memory does, and still reject X on valid bytes.
                        right = len(data_bits) - 8 * lane
                        lane_bits = data_bits[right - 8:right]
                        if any(bit not in "01" for bit in lane_bits):
                            raise ValueError(
                                "{} AXI WDATA contains X/Z at address 0x{:x}, "
                                "beat {}/{}, strobed lane {}: {} (WSTRB=0x{:x})"
                                .format(
                                    self.prefix,
                                    address,
                                    beat_index,
                                    beats,
                                    lane,
                                    lane_bits,
                                    strobe,
                                )
                            )
                        lane_value = int(lane_bits, 2)
                        try:
                            start, _ = self._range(word_address + lane, 1)
                            self.mem[start] = lane_value
                        except IndexError:
                            response = self.SLVERR

                beat_index += 1
                if expected_last:
                    delay = self.write_random.randint(*self.write_response_latency)
                    state = "B_DELAY"
                else:
                    try:
                        address = self._next_address(address, size, burst)
                    except ValueError:
                        response = self.SLVERR

            elif state == "B" and int(self.bvalid.value) and int(self.bready.value):
                self.bvalid.value = 0
                state = "AW"

    async def _read_loop(self):
        state = "AR"
        address = 0
        size = 0
        burst = 1
        beats = 0
        beat_index = 0
        delay = 0
        transaction_response = self.OKAY

        while True:
            await FallingEdge(self.clock)

            if self._in_reset():
                state = "AR"
                self.arready.value = 0
                self.rvalid.value = 0
                self.rlast.value = 0
                continue

            if state == "AR":
                self.arready.value = 1 if self._allow(self.read_random) else 0
                self.rvalid.value = 0
                self.rlast.value = 0
            elif state == "R_DELAY":
                self.arready.value = 0
                self.rvalid.value = 0
                if delay == 0:
                    word_address = address & ~(self.data_bytes - 1)
                    first_lane = address - word_address
                    last_lane = min(((address >> size) + 1) * (1 << size) - word_address, self.data_bytes)
                    value = 0
                    response = transaction_response
                    for lane in range(first_lane, last_lane):
                        try:
                            start, _ = self._range(word_address + lane, 1)
                            value |= self.mem[start] << (8 * lane)
                        except IndexError:
                            response = self.SLVERR
                    self.rdata.value = value
                    self.rresp.value = response
                    self.rlast.value = 1 if beat_index == beats - 1 else 0
                    self.rvalid.value = 1
                    state = "R"
                else:
                    delay -= 1
            elif state == "R":
                self.arready.value = 0
                self.rvalid.value = 1

            await RisingEdge(self.clock)

            if self._in_reset():
                continue

            if state == "AR" and int(self.arvalid.value) and int(self.arready.value):
                address = int(self.araddr.value)
                size = int(self.arsize.value)
                burst = int(self.arburst.value)
                beats = int(self.arlen.value) + 1
                beat_index = 0
                transaction_response = self.OKAY
                if (1 << size) > self.data_bytes or burst not in (0, 1):
                    transaction_response = self.SLVERR
                if burst == 1:
                    last_address = (address & ~((1 << size) - 1)) + beats * (1 << size) - 1
                    if (address >> 12) != (last_address >> 12):
                        transaction_response = self.SLVERR
                delay = self.read_random.randint(*self.read_latency)
                state = "R_DELAY"

            elif state == "R" and int(self.rvalid.value) and int(self.rready.value):
                self.rvalid.value = 0
                if beat_index == beats - 1:
                    self.rlast.value = 0
                    state = "AR"
                else:
                    beat_index += 1
                    try:
                        address = self._next_address(address, size, burst)
                    except ValueError:
                        pass
                    delay = self.read_random.randint(*self.read_latency)
                    state = "R_DELAY"
