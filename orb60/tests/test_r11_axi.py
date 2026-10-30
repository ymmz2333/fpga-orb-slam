"""Exact R11 RTL gate: random stalls, narrow lanes, 4 KB edges and reset restart."""
import json
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from common.axi_lite import AxiLiteMaster, drive_axi_sidebands
from axi_ram import AxiRamModel

SOURCE_BASE, OUTPUT_BASE = 0x100000, 0x200000
SOURCE = SOURCE_BASE + 0xff8
OUTPUT = OUTPUT_BASE + 0xfc0
SUMMARY = OUTPUT_BASE + 0x10fc0
PORT_BYTES = 691200


class Monitor:
    """Check the actual accepted AXI channels and completion response barrier."""
    def __init__(self, ram):
        self.ram = ram
        self.counts = dict(read_bytes=0, write_bytes=0, ar=0, aw=0, r=0, w=0, b=0,
                           stalls=0, boundary_bursts=0, narrow_bursts=0)
        self.pending_reads = self.pending_writes = 0
        self.allowed_writes = []
        self.aborting = False

    async def run(self):
        r = self.ram
        payload = {'ar': ('araddr', 'arlen', 'arsize', 'arburst'),
                   'aw': ('awaddr', 'awlen', 'awsize', 'awburst'),
                   'w': ('wdata', 'wstrb', 'wlast')}
        held = {}
        while True:
            await RisingEdge(r.clock)
            if r._in_reset():
                held.clear()
                self.pending_reads = self.pending_writes = 0
                continue
            for channel, fields in payload.items():
                valid = int(getattr(r, channel + 'valid').value)
                ready = int(getattr(r, channel + 'ready').value)
                now = tuple(str(getattr(r, f).value) for f in fields)
                if channel in held:
                    assert valid and now == held[channel], f'{r.prefix} {channel} changed under stall'
                if valid and not ready:
                    held[channel] = now
                    self.counts['stalls'] += 1
                else:
                    held.pop(channel, None)
                if valid and ready and channel in ('ar', 'aw'):
                    address, length, size, burst = (int(getattr(r, f).value) for f in fields)
                    step, beats = 1 << size, length + 1
                    assert step <= r.data_bytes and burst == 1
                    end = (address & ~(step - 1)) + step * beats - 1
                    assert address >> 12 == end >> 12, f'AXI crosses 4 KB: {address:x}..{end:x}'
                    self.counts[channel] += 1
                    self.counts['boundary_bursts'] += (address & 4095) >= 4032 or (end & 4095) == 4095
                    self.counts['narrow_bursts'] += step < r.data_bytes
                    if channel == 'ar':
                        r._range(address, end - address + 1)
                        self.pending_reads += 1
                        self.read_size = size
                    else:
                        self.pending_writes += 1
                        self.write_address = address
                        self.write_size = size
                        self.write_remaining = beats
            if int(r.rvalid.value) and int(r.rready.value):
                assert int(r.rresp.value) == 0, f'{r.prefix} RRESP error'
                self.counts['r'] += 1
                self.counts['read_bytes'] += 1 << self.read_size
                if int(r.rlast.value):
                    self.pending_reads -= 1
                    assert self.pending_reads >= 0
            if int(r.wvalid.value) and int(r.wready.value):
                self.counts['w'] += 1
                strobe = int(r.wstrb.value)
                self.counts['write_bytes'] += strobe.bit_count()
                base = self.write_address & ~(r.data_bytes - 1)
                for lane in range(r.data_bytes):
                    if (strobe >> lane) & 1:
                        a = base + lane
                        assert any(lo <= a < hi for lo, hi in self.allowed_writes), f'Unexpected write {r.prefix}@{a:x}'
                self.write_remaining -= 1
                assert bool(int(r.wlast.value)) == (self.write_remaining == 0)
                self.write_address = ((self.write_address >> self.write_size) + 1) << self.write_size
            if int(r.bvalid.value) and int(r.bready.value):
                assert int(r.bresp.value) == 0, f'{r.prefix} BRESP error'
                self.counts['b'] += 1
                self.pending_writes -= 1
                assert self.pending_writes >= 0


async def reset(dut):
    await FallingEdge(dut.ap_clk)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 12)
    await FallingEdge(dut.ap_clk)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 5)


async def configure(control, kernel, case, offsets):
    is_front = kernel in ('front', 'front2')
    await control.write(offsets['IMAGE_R' if is_front else 'SOURCE'], SOURCE)
    await control.write(offsets['SELECTED' if is_front else 'DESTINATION'], OUTPUT)
    if is_front:
        await control.write(offsets['RESULT'], SUMMARY)
        for key, value in zip(('WIDTH', 'HEIGHT', 'BUDGET', 'HIGH_THRESHOLD', 'LOW_THRESHOLD', 'DUAL_THRESHOLD', 'SELECTED_CAPACITY'), case['args']):
            await control.write(offsets[key], value & 0xffffffff)
    else:
        await control.write(offsets['SOURCE_LEVEL' if kernel == 'resize' else 'LEVEL'], case['level'] & 0xffffffff)
    await control.write(0, 1)


@cocotb.test()
async def exact_random_axi_and_reset(dut):
    config = json.loads(Path(os.environ['ORB60_AXI_CONFIG']).read_text())
    kernel = config['kernel']
    vectors = Path(config['vectors'])
    cases = [c for c in json.loads((vectors / 'vectors.json').read_text())['cases'] if c['kernel'] == kernel]
    if os.environ.get('ORB60_AXI_SMOKE') == '1':
        cases = [next(c for c in cases if c['status'] == 1), next(c for c in cases if c.get('pattern') == 1)]
    dut.ap_rst_n.value = 0
    cocotb.start_soon(Clock(dut.ap_clk, 10, unit='ns').start())
    memories, monitors = [], []
    for i, base in enumerate((SOURCE_BASE, OUTPUT_BASE)):
        prefix = f'm_axi_gmem{i}'
        drive_axi_sidebands(dut, prefix)
        ram = AxiRamModel(dut, prefix, dut.ap_clk, dut.ap_rst_n,
                          size=0xc0000, base_address=base, stall_probability=.27,
                          read_latency=(0, 5), write_response_latency=(2, 19),
                          seed=6000 + i, reset_active_level=0)
        ram.start()
        monitor = Monitor(ram)
        cocotb.start_soon(monitor.run())
        memories.append(ram)
        monitors.append(monitor)
    src, dst = memories
    control = AxiLiteMaster(dut, 's_axi_control', dut.ap_clk)
    await reset(dut)
    # Cancel a live transaction with AXI responses in flight, then reuse the IP.
    interrupted = next(c for c in cases if c['status'] == 0)
    src.write(SOURCE, (vectors / f"{interrupted['name']}_input.bin").read_bytes())
    monitors[1].allowed_writes = [(OUTPUT, OUTPUT + PORT_BYTES), (SUMMARY, SUMMARY + 64)]
    await configure(control, kernel, interrupted, config['offsets'])
    await ClockCycles(dut.ap_clk, 733)
    assert not (await control.read(0) & 2), 'Reset-interruption job unexpectedly completed'
    await reset(dut)
    results = []
    for case in cases:
        name = case['name']
        before = [dict(m.counts) for m in monitors]
        src.write(SOURCE, (vectors / f'{name}_input.bin').read_bytes())
        dst.mem[:] = b'\xa5' * len(dst.mem)
        expected = bytearray(dst.mem)
        if kernel in ('front', 'front2'):
            points = (vectors / f'{name}_points.bin').read_bytes()
            summary = (vectors / f'{name}_summary.bin').read_bytes()
            expected[OUTPUT - OUTPUT_BASE:OUTPUT - OUTPUT_BASE + len(points)] = points
            expected[SUMMARY - OUTPUT_BASE:SUMMARY - OUTPUT_BASE + 64] = summary
            monitors[1].allowed_writes = [(SUMMARY, SUMMARY + 64)]
            if case['status'] == 0:
                monitors[1].allowed_writes += [(OUTPUT, OUTPUT + 16 * case['selected'])]
        else:
            initial = bytes.fromhex('f00f5a6aefbeadde') * (PORT_BYTES // 8)
            dst.write(OUTPUT, initial)
            expected[OUTPUT - OUTPUT_BASE:OUTPUT - OUTPUT_BASE + PORT_BYTES] = (vectors / f'{name}_output.bin').read_bytes()
            active = (case['active_bytes'] + 7) // 8 * 8
            monitors[1].allowed_writes = [(OUTPUT, OUTPUT + active)]
        await configure(control, kernel, case, config['offsets'])
        cycles = 0
        while cycles < 4_000_000:
            await ClockCycles(dut.ap_clk, 1000)
            cycles += 1000
            if (await control.read(0)) & 2:
                break
        else:
            raise TimeoutError(f'{kernel} case={case["index"]} exceeded cycle bound')
        status = await control.read(config['offsets']['AP_RETURN'])
        assert status == case['status'], (kernel, case['index'], status, case['status'])
        assert dst.mem == expected, f'{kernel} output/summary/guard mismatch case {case["index"]}'
        assert all(m.pending_reads == m.pending_writes == 0 for m in monitors), 'Done precedes final AXI response'
        differences = [{k: m.counts[k] - before[i][k] for k in m.counts} for i, m in enumerate(monitors)]
        if case['status'] == 1:
            assert differences[0]['ar'] == differences[0]['aw'] == 0
        results.append(dict(case=case['index'], cycles_upper_bound=cycles, axi=differences))
        dut._log.info('ORB60_AXI_CASE_PASS kernel=%s case=%d cycle_upper_bound=%d', kernel, case['index'], cycles)
    assert monitors[0].counts['boundary_bursts'] > 0
    assert sum(m.counts['stalls'] for m in monitors) > 0
    Path(config['result']).write_text(json.dumps(dict(status='PASS', kernel=kernel, transactions=len(cases),
        reset_interruption=True, counts=[m.counts for m in monitors], cases=results), indent=2) + '\n')
