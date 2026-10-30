"""Random DDR/backpressure gate for the actual 4-master generated HLS cores."""
import json
import os
from pathlib import Path
import struct

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles,ReadOnly,RisingEdge
from cocotb.utils import get_sim_time
from common.axi_lite import AxiLiteMaster,drive_axi_sidebands
from axi_ram import AxiRamModel
from test_r11_axi import Monitor,reset

BASE=0x100000
MEMORY_BYTES=0x400000
RAW=0x100ff8
BLUR=0x200ff8
NEXT=0x300ff8
POINTS=0x400ff8
RESULT=0x420fc0
STATS=0x430fc0
DESCRIPTOR_POINTS=0x300ff8
FEATURES=0x400ff8
PORT_BYTES=691200


class DoneBarrier:
    def __init__(self,dut,monitors):
        self.dut=dut;self.monitors=monitors;self.enabled=False;self.pulses=0
        self.signal=dut.ap_done # Require actual done; delayed PS polling is insufficient.

    async def run(self):
        while True:
            await RisingEdge(self.dut.ap_clk)
            await ReadOnly()
            if self.enabled and int(self.dut.ap_rst_n.value) and int(self.signal.value):
                assert all(m.pending_reads==m.pending_writes==0 for m in self.monitors), 'ap_done precedes final AXI response'
                self.pulses+=1


def payloads(kernel,vectors,case):
    name=case['name']
    if kernel=='descriptor':
        return {RAW:(vectors/f'{name}_raw.bin').read_bytes(),BLUR:(vectors/f'{name}_blur.bin').read_bytes(),
                DESCRIPTOR_POINTS:(vectors/f'{name}_points.bin').read_bytes()}
    return {RAW:(vectors/f'{name}_input.bin').read_bytes()}


async def configure(control,kernel,case,offsets,controls):
    pointers={'RAW':RAW,'BLURRED':BLUR,'POINTS':DESCRIPTOR_POINTS,'FEATURES':FEATURES,'STATS':STATS} if kernel=='descriptor' else {
        'IMAGE_R':RAW,'BLURRED':BLUR,'RESIZED':NEXT,'SELECTED':POINTS,'RESULT':RESULT,'STATS':STATS}
    for key,value in pointers.items():await control.write(offsets[key],value)
    if kernel=='descriptor':
        fields=('WIDTH','HEIGHT','COUNT','LEVEL','FRAME_OFFSET','CAPACITY')
        values=controls[:6]
    else:
        fields=('LEVEL','BUDGET','HIGH_THRESHOLD','LOW_THRESHOLD','DUAL_THRESHOLD','SELECTED_CAPACITY')
        values=case['args']
    for key,value in zip(fields,values):await control.write(offsets[key],value&0xffffffff)
    await control.write(0,1)


def assign(expected,address,data):expected[address-BASE:address-BASE+len(data)]=data


@cocotb.test()
async def exact_datapath_random_axi_and_reset(dut):
    config=json.loads(Path(os.environ['ORB60_DATAPATH_CONFIG']).read_text())
    kernel=config['kernel'];vectors=Path(config['vectors'])
    vector_info=json.loads((vectors/'vectors.json').read_text())
    controls=[]
    if kernel=='descriptor':
        data=(vectors/'cases.bin').read_bytes()
        controls=[struct.unpack_from('<12i',data,16+48*i) for i in range(len(vector_info['cases']))]
    dut.ap_rst_n.value=0
    period_ps=config.get('clock_period_ps',10000)
    cocotb.start_soon(Clock(dut.ap_clk,period_ps,unit='ps',period_high=period_ps-period_ps//2).start())
    memory=bytearray(b'\xa5'*MEMORY_BYTES)
    rams=[];monitors=[]
    for i in range(4):
        prefix=f'm_axi_gmem{i}';drive_axi_sidebands(dut,prefix)
        assert len(getattr(dut,prefix+'_ARADDR'))==32
        ram=AxiRamModel(dut,prefix,dut.ap_clk,dut.ap_rst_n,size=MEMORY_BYTES,base_address=BASE,
            stall_probability=.27,read_latency=(0,5),write_response_latency=(2,31),seed=6600+i,reset_active_level=0)
        assert ram.data_bytes==8
        ram.mem=memory # All four masters access one physical address space.
        ram.start();monitor=Monitor(ram);cocotb.start_soon(monitor.run())
        rams.append(ram);monitors.append(monitor)
    barrier=DoneBarrier(dut,monitors);cocotb.start_soon(barrier.run())
    control=AxiLiteMaster(dut,'s_axi_control',dut.ap_clk)
    await reset(dut)
    interrupted=vector_info['cases'][config['reset_case']]
    for address,data in payloads(kernel,vectors,interrupted).items():rams[0].write(address,data)
    for monitor in monitors:monitor.allowed_writes=[(BASE,BASE+MEMORY_BYTES)]
    await configure(control,kernel,interrupted,config['offsets'],controls[config['reset_case']] if controls else ())
    await ClockCycles(dut.ap_clk,733)
    assert not(await control.read(0)&2), 'Reset target completed before interruption'
    # A descriptor may spend a while computing with both patches already loaded.
    # Wait for actual outstanding traffic instead of assuming a fixed cycle hits it.
    for _ in range(1024):
        if any(m.pending_reads or m.pending_writes for m in monitors):break
        await ClockCycles(dut.ap_clk,1)
    else:raise AssertionError('Reset did not interrupt outstanding traffic')
    await reset(dut)
    result=[]
    for index in config['cases']:
        case=vector_info['cases'][index];memory[:]=b'\xa5'*len(memory)
        for address,data in payloads(kernel,vectors,case).items():rams[0].write(address,data)
        for monitor in monitors:monitor.allowed_writes=[]
        expected=bytearray(memory)
        if kernel=='descriptor':
            args=controls[index]
            # Each selected protocol case resets its capacity-1000 frame.
            assert args[10]==1
            initial=b'\xc3'*64000;assign(memory,FEATURES,initial);assign(expected,FEATURES,(vectors/f"{case['name']}_features.bin").read_bytes())
            monitors[3].allowed_writes=[(STATS,STATS+64)]
            if args[7]:monitors[3].allowed_writes.append((FEATURES+args[4]*64,FEATURES+(args[4]+args[7])*64))
        else:
            valid=case['status']!=1
            for address,suffix in ((BLUR,'blur'),(NEXT,'resize')):
                initial=bytes.fromhex('f00f5a6aefbeadde')*(PORT_BYTES//8)
                assign(memory,address,initial);assign(expected,address,(vectors/f"{case['name']}_{suffix}.bin").read_bytes())
            assign(expected,POINTS,(vectors/f"{case['name']}_points.bin").read_bytes())
            assign(expected,RESULT,(vectors/f"{case['name']}_summary.bin").read_bytes())
            monitors[1].allowed_writes=[(RESULT,RESULT+64),(STATS,STATS+64)]
            if case['status']==0:monitors[1].allowed_writes.append((POINTS,POINTS+case['selected']*16))
            if valid:
                from oracle import WIDTHS,HEIGHTS
                level=case['level'];blur_bytes=(WIDTHS[level]*HEIGHTS[level]+7)//8*8
                next_bytes=(WIDTHS[level+1]*HEIGHTS[level+1]+7)//8*8 if level<7 else 0
                monitors[2].allowed_writes=[(BLUR,BLUR+blur_bytes)]
                monitors[3].allowed_writes=[(NEXT,NEXT+next_bytes)] if next_bytes else []
        before=[dict(m.counts) for m in monitors];pulses=barrier.pulses;barrier.enabled=True
        start_ps=int(get_sim_time(unit='ps'))
        await configure(control,kernel,case,config['offsets'],args if kernel=='descriptor' else ())
        poll_wait_cycles=0
        while (int(get_sim_time(unit='ps'))-start_ps)//period_ps<4_000_000:
            await ClockCycles(dut.ap_clk,200)
            poll_wait_cycles+=200
            if await control.read(0)&2:break
        else:raise TimeoutError(f'{kernel} case {index} exceeded cycle bound')
        barrier.enabled=False
        status=await control.read(config['offsets']['AP_RETURN'])
        assert status==case['status']&0xffffffff,(index,status,case['status'])
        assert barrier.pulses>pulses,'No direct ap_done observation'
        assert all(m.pending_reads==m.pending_writes==0 for m in monitors),'Outstanding AXI at completion'
        s=struct.unpack('<16I',rams[0].read(STATS,64))
        # Include configuration, polling and status-read handshakes in elapsed
        # clocks. Summing ClockCycles alone undercounts these synchronous waits.
        elapsed_cycles=(int(get_sim_time(unit='ps'))-start_ps)//period_ps
        progress=dict(status='RUNNING',kernel=kernel,completed_cases=result,current_case=index,
                      stats=s,elapsed_cycles=elapsed_cycles,poll_wait_cycles=poll_wait_cycles)
        Path(config['result']).write_text(json.dumps(progress,indent=2)+'\n')
        if kernel=='descriptor':
            width,height,count,level,offset,capacity,wanted,completed,raw_bytes,blur_bytes=args[:10]
            assert s[:10]==(0x600002,wanted&0xffffffff,level&0xffffffff,count&0xffffffff,completed,offset&0xffffffff,
                           raw_bytes,blur_bytes,0 if wanted==-1 else count*16,completed*64)
            assert s[11:]==((0 if wanted==-1 else 3),0,0,0,0)
            assert (s[10]==0) if wanted==-1 else (0<s[10]<=elapsed_cycles), \
                f'Counter exceeds actual elapsed clocks case={index} counter={s[10]} elapsed={elapsed_cycles}'
            expected_reads=(raw_bytes,blur_bytes,0 if wanted==-1 else count*16,0)
            expected_writes=(0,0,0,completed*64+64)
        else:
            from oracle import WIDTHS,HEIGHTS
            level=case['level'];valid=case['status']!=1
            width,height=(WIDTHS[level],HEIGHTS[level]) if valid else (0,0)
            raw_bytes=(width*height+7)//8*8
            nw,nh=(WIDTHS[level+1],HEIGHTS[level+1]) if valid and level<7 else (0,0)
            next_bytes=(nw*nh+7)//8*8
            ppc=config.get('layer_ppc',2);assert ppc in (2,4)
            version=0x600003 if ppc==4 else 0x600001
            resize_groups=((width+3)//4 if ppc==4 else (nw+1)//2)*nh
            assert s[:11]==(version,case['status'],level,width,height,raw_bytes,raw_bytes,next_bytes,
                            (width+ppc-1)//ppc*height,(width+ppc-1)//ppc*height,resize_groups)
            assert s[12:]==((ppc|(1 if level<7 else 0)) if valid else 0,0,0,0)
            assert (0<s[11]<=elapsed_cycles) if valid else (s[11]==0), \
                f'Counter exceeds actual elapsed clocks case={index} counter={s[11]} elapsed={elapsed_cycles}'
            expected_reads=(raw_bytes,0,0,0)
            expected_writes=(0,128+(case['selected']*16 if case['status']==0 else 0),raw_bytes,next_bytes)
        assign(expected,STATS,struct.pack('<16I',*s))
        assert memory==expected,f'Whole DDR image/feature/summary/guard mismatch {kernel} case {index}'
        differences=[{k:m.counts[k]-before[i][k] for k in m.counts} for i,m in enumerate(monitors)]
        assert tuple(d['read_bytes'] for d in differences)==expected_reads,'Read counter/payload mismatch'
        assert tuple(d['write_bytes'] for d in differences)==expected_writes,'Write counter/payload mismatch'
        result.append(dict(case=index,cycles_ps_upper_bound=elapsed_cycles,poll_wait_cycles=poll_wait_cycles,stats=s,axi=differences))
        dut._log.info('ORB60_DATAPATH_AXI_CASE_PASS kernel=%s case=%d elapsed_cycles=%d',kernel,index,elapsed_cycles)
    assert sum(m.counts['boundary_bursts'] for m in monitors)>0
    assert sum(m.counts['stalls'] for m in monitors)>0
    Path(config['result']).write_text(json.dumps(dict(status='PASS',kernel=kernel,transactions=len(result),
        direct_completion_barrier=True,reset_interruption=True,cases=result,counts=[m.counts for m in monitors]),indent=2)+'\n')
