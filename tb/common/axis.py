"""Small AXI4-Stream source and sink for cocotb tests."""
import random

from cocotb.triggers import FallingEdge, RisingEdge, Timer


class AxisSource(object):
    def __init__(self, dut, prefix, clock, seed=1):
        self.clock = clock
        self.random = random.Random(seed)
        self.data = getattr(dut, prefix + "_tdata")
        self.valid = getattr(dut, prefix + "_tvalid")
        self.ready = getattr(dut, prefix + "_tready")
        self.user = getattr(dut, prefix + "_tuser")
        self.last = getattr(dut, prefix + "_tlast")
        self.valid.value = 0
        self.data.value = 0
        self.user.value = 0
        self.last.value = 0

    async def send(self, payload, width, gap_probability=0.0):
        for index, value in enumerate(bytearray(payload)):
            # Optional source bubbles exercise valid handling.
            while self.random.random() < gap_probability:
                await FallingEdge(self.clock)
                self.valid.value = 0
                await RisingEdge(self.clock)

            accepted = False
            while not accepted:
                await FallingEdge(self.clock)
                self.data.value = value
                self.user.value = 1 if index == 0 else 0
                self.last.value = 1 if (index % width) == (width - 1) else 0
                self.valid.value = 1
                await RisingEdge(self.clock)
                accepted = bool(int(self.ready.value))

        await FallingEdge(self.clock)
        self.valid.value = 0
        self.user.value = 0
        self.last.value = 0


class AxisSink(object):
    def __init__(self, dut, prefix, clock, seed=2):
        self.clock = clock
        self.random = random.Random(seed)
        self.data = getattr(dut, prefix + "_tdata")
        self.valid = getattr(dut, prefix + "_tvalid")
        self.ready = getattr(dut, prefix + "_tready")
        self.user = getattr(dut, prefix + "_tuser")
        self.last = getattr(dut, prefix + "_tlast")
        self.ready.value = 0

    async def recv(self, count, backpressure_probability=0.0):
        payload = bytearray()
        users = []
        lasts = []
        held_transfer = None
        while len(payload) < count:
            await FallingEdge(self.clock)

            # Check halfway through the cycle, before changing TREADY.  Checking
            # after the next rising edge would be too late: if TREADY became 1,
            # a legal transfer occurred and the producer may already present
            # the following item.
            if held_transfer is not None:
                valid_midcycle = int(self.valid.value)
                transfer_midcycle = (
                    int(self.data.value),
                    int(self.user.value),
                    int(self.last.value),
                )
                assert valid_midcycle, (
                    "AXI4-Stream violation: TVALID was removed before TREADY"
                )
                assert transfer_midcycle == held_transfer, (
                    "AXI4-Stream violation: TDATA/TUSER/TLAST changed while "
                    "TVALID=1 and TREADY=0; held={}, now={}".format(
                        held_transfer, transfer_midcycle
                    )
                )

            self.ready.value = (
                0 if self.random.random() < backpressure_probability else 1
            )
            # Capture the values that will be sampled at the upcoming rising
            # edge.  Reading after that edge can observe the producer's next
            # registered value and incorrectly attribute it to this transfer.
            await Timer(1, unit="ns")
            valid_before_edge = int(self.valid.value)
            ready_before_edge = int(self.ready.value)
            transfer_before_edge = (
                int(self.data.value),
                int(self.user.value),
                int(self.last.value),
            )
            await RisingEdge(self.clock)

            if valid_before_edge and ready_before_edge:
                payload.append(transfer_before_edge[0])
                users.append(transfer_before_edge[1])
                lasts.append(transfer_before_edge[2])
                held_transfer = None
            elif valid_before_edge:
                held_transfer = transfer_before_edge
            else:
                held_transfer = None

        await FallingEdge(self.clock)
        self.ready.value = 0
        return bytes(payload), users, lasts
