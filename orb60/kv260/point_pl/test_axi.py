"""Actual generated RTL: shared high-address DDR, randomized AXI and reset."""
import json,os,struct
from pathlib import Path
import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles,RisingEdge,ReadOnly
from common.axi_lite import AxiLiteMaster,drive_axi_sidebands
from axi_ram import AxiRamModel
from test_r11_axi import Monitor,reset
from orb60.kv260.point_pl.reference import compare

BASE=0x100000000;SIZE=0x80000
IN=BASE+0xff0;CFG=BASE+0x10000;OUT=BASE+0x20fe0;STATS=BASE+0x50000

@cocotb.test()
async def randomized_shared_memory(dut):
    cfg=json.loads(Path(os.environ['POINT_AXI_CONFIG']).read_text());vectors=Path(cfg['vectors']);offset=cfg['offsets']
    dut.ap_rst_n.value=0;cocotb.start_soon(Clock(dut.ap_clk,6666,unit='ps').start())
    memory=bytearray(b'\xa5'*SIZE);rams=[];monitors=[]
    for i,name in enumerate(['input_mem','output_mem']):
        prefix='m_axi_'+name;drive_axi_sidebands(dut,prefix)
        assert len(getattr(dut,prefix+'_ARADDR'))==64
        ram=AxiRamModel(dut,prefix,dut.ap_clk,dut.ap_rst_n,size=SIZE,base_address=BASE,stall_probability=.31,
                        read_latency=(0,7),write_response_latency=(3,33),seed=248+i,reset_active_level=0)
        ram.mem=memory;ram.start();m=Monitor(ram);monitors.append(m);cocotb.start_soon(m.run());rams.append(ram)
    ctrl=AxiLiteMaster(dut,'s_axi_control',dut.ap_clk);await reset(dut)
    async def start(case):
        await ctrl.read(0)
        for name,address in [('SAMPLES',IN),('CONFIG_R',CFG),('POINTS',OUT),('STATS',STATS)]:
            await ctrl.write(offset[name+'_DATA'],address&0xffffffff);await ctrl.write(offset[name+'_DATA']+4,address>>32)
        for name,value in [('COUNT',case['count']),('CAPACITY',case['capacity'])]:await ctrl.write(offset[name+'_DATA'],value)
        await ctrl.write(0,1)
    cases=json.loads((vectors/'vectors.json').read_text())['cases'][:-1]
    # Interrupt a transaction with outstanding traffic; reset and restart.
    interrupted=cases[4]
    for address,suffix in [(IN,'samples'),(CFG,'config')]:rams[0].write(address,(vectors/(interrupted['name']+'_'+suffix+'.bin')).read_bytes())
    monitors[1].allowed_writes=[(OUT,OUT+0x10000),(STATS,STATS+32)]
    await start(interrupted)
    for _ in range(1000):
        await ClockCycles(dut.ap_clk,1)
        if any(m.pending_reads or m.pending_writes for m in monitors):break
    else:raise AssertionError('Reset did not hit outstanding AXI')
    await reset(dut)
    results=[]
    for case in cases:
        memory[:]=b'\xa5'*SIZE;name=case['name'];n=case['written']
        for address,suffix in [(IN,'samples'),(CFG,'config')]:rams[0].write(address,(vectors/(name+'_'+suffix+'.bin')).read_bytes())
        before=bytes(memory);monitors[0].allowed_writes=[];monitors[1].allowed_writes=[(STATS,STATS+32)]
        if n:monitors[1].allowed_writes.append((OUT,OUT+n*32))
        began=cocotb.utils.get_sim_time(unit='ns');await start(case)
        # Check the actual HLS completion pulse, not delayed PS polling.
        for cycles in range(100000):
            await RisingEdge(dut.ap_clk);await ReadOnly()
            if int(dut.ap_done.value):
                assert all(m.pending_reads==m.pending_writes==0 for m in monitors),'ap_done before final AXI response'
                break
        else:raise AssertionError('RTL timeout')
        await ClockCycles(dut.ap_clk,2)
        assert await ctrl.read(offset['AP_RETURN'])==int.from_bytes((vectors/(name+'_stats.bin')).read_bytes()[12:16],'little')
        actual=rams[0].read(OUT,n*32);expected=(vectors/(name+'_points.bin')).read_bytes()
        compare(np.frombuffer(actual,'<u4').reshape(-1,8),np.frombuffer(expected,'<u4').reshape(-1,8))
        assert rams[0].read(STATS,32)==(vectors/(name+'_stats.bin')).read_bytes()
        # All bytes outside the permitted output regions stay untouched.
        after=bytearray(memory);original=bytearray(before)
        for addr,length in [(OUT,n*32),(STATS,32)]:after[addr-BASE:addr-BASE+length]=original[addr-BASE:addr-BASE+length]
        assert after==original,'Unexpected DDR mutation'
        results.append(dict(case=name,cycles=cycles,wall_sim_ns=cocotb.utils.get_sim_time(unit='ns')-began))
    counts=[m.counts for m in monitors]
    assert sum(c['stalls'] for c in counts)>0 and sum(c['boundary_bursts'] for c in counts)>0
    Path(cfg['output']).write_text(json.dumps(dict(status='PASS',transactions=len(results),reset_interruption=True,
        address_bits=64,shared_ddr=True,direct_completion_barrier=True,results=results,axi_counts=counts),indent=2)+'\n')
