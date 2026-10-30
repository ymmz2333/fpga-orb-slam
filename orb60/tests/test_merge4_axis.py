"""Legal quad masks, finite backpressure, stable AXIS payload and reset restart."""
import json
import os
from pathlib import Path
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles,FallingEdge,ReadOnly,RisingEdge,Timer


def vectors(mode,n=128):
    packets=[];expected=[]
    for i in range(n):
        mask=mode if mode<16 else (i*13+i//7)&15
        words=[4*i+k+1 for k in range(4)]
        packets.append(sum(w<<(64*k) for k,w in enumerate(words))|(mask<<256))
        expected.extend(w for k,w in enumerate(words) if mask&(1<<k))
    end=(1<<63)|len(expected);packets.append(end);expected.append(end)
    return packets,expected


@cocotb.test()
async def quad_masks_random_backpressure_reset(dut):
    assert len(dut.packets_TDATA)==264 and len(dut.tokens_TDATA)==64
    dut.ap_rst_n.value=0;dut.ap_start.value=0;dut.packets_TVALID.value=0
    dut.packets_TDATA.value=0;dut.tokens_TREADY.value=0
    cocotb.start_soon(Clock(dut.ap_clk,int(os.environ.get('ORB60_MERGE4_CLOCK_PS','10000')),unit='ps').start())
    rng=random.Random(604404)
    async def reset():
        await FallingEdge(dut.ap_clk)
        dut.ap_rst_n.value=0;dut.ap_start.value=0;dut.packets_TVALID.value=0;dut.tokens_TREADY.value=0
        await ClockCycles(dut.ap_clk,12)
        await FallingEdge(dut.ap_clk);dut.ap_rst_n.value=1
        await ClockCycles(dut.ap_clk,4)

    async def transfer(mode,abort=False):
        packets,expected=vectors(mode);sent=received=cycles=0;pending=False;held=None
        input_stalls=output_stalls=0;done=False
        for cycle in range(100000):
            await FallingEdge(dut.ap_clk)
            dut.ap_start.value=int(sent<len(packets))
            if not pending and sent<len(packets) and rng.random()>.18:pending=True
            dut.packets_TVALID.value=int(pending)
            if pending:dut.packets_TDATA.value=packets[sent]
            # Deliberate long sink pauses, plus random ready. Reset interruption
            # holds the sink with in-flight tokens instead of assuming a clock.
            paused=(20<=cycle<180 or 500<=cycle<650) if not abort else cycle>=5
            ready=not paused and rng.random()>.31;dut.tokens_TREADY.value=int(ready)
            await Timer(1,unit='ns');await ReadOnly()
            ir=int(dut.packets_TREADY.value);ov=int(dut.tokens_TVALID.value)
            value=int(dut.tokens_TDATA.value) if ov else 0
            if held is not None:assert ov and value==held,'AXIS payload changed under output stall'
            held=value if ov and not ready else None
            done|=bool(int(dut.ap_done.value))
            await RisingEdge(dut.ap_clk);cycles+=1
            if pending and ir:sent+=1;pending=False
            elif pending:input_stalls+=1
            if ov and ready:
                assert received<len(expected) and value==expected[received],(mode,received,value)
                received+=1
            elif ov:output_stalls+=1
            if abort and cycle==96:
                assert sent>0 and received<len(expected) and held is not None,'Reset did not interrupt live stalled output'
                return dict(reset_live=True,cycles=cycles)
            if sent==len(packets) and received==len(expected):break
        else:raise TimeoutError('Quad serializer did not drain under finite backpressure')
        # A buffered AXIS interface can complete internally before the last
        # external transfer; this test checks data drain independently of done.
        for _ in range(12):
            await FallingEdge(dut.ap_clk);dut.ap_start.value=0;dut.packets_TVALID.value=0;dut.tokens_TREADY.value=1
            await Timer(1,unit='ns');await ReadOnly();done|=bool(int(dut.ap_done.value))
            assert not int(dut.tokens_TVALID.value),'Extra output after the exact sentinel'
            await RisingEdge(dut.ap_clk)
        assert done and int(dut.ap_idle.value),'Missing completion/idle after drain'
        return dict(mode=mode,groups=len(packets)-1,outputs=len(expected)-1,cycles=cycles,
                    input_stalls=input_stalls,output_stalls=output_stalls)

    await reset();interrupted=await transfer(15,True);await reset()
    rows=[await transfer(mode) for mode in range(17)]
    assert sum(r['input_stalls'] for r in rows)>0 and sum(r['output_stalls'] for r in rows)>0
    result=dict(status='PASS',cases=17,legal_masks=list(range(16)),mixed=True,reset=interrupted,
                scope='Same production serializer source; isolated AXIS protocol/reset, no routed/DDR/frame claim',results=rows)
    Path(os.environ['ORB60_MERGE4_RESULT']).write_text(json.dumps(result,indent=2)+'\n')
