"""Recreate the paired ORB PL with Vivado 2018.3; stop after synthesis.

The user explicitly requested the 2024.2 -> 2018.3 migration. Never write to
the frozen handoff. HLS export RTL is reused, not regenerated with old HLS.
"""
from pathlib import Path, PurePosixPath
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_HANDOFF = PROJECT.parent / 'zynq7015_localization_handoff_20261022' / 'zynq7015_localization_handoff_20261022'
PROFILE = Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/xilinx-2018.3.cmd')
INPUTS = {
    'fpga_baseline/top_inputs/build_orb_frequency.tcl': '00be59a4391c99b19b7b8306a9cb5f37f3f50069eb0878a13154d68255fef666',
    'fpga_baseline/top_inputs/ps_config.tcl': 'f4ef126a6408ecb55a49ef00907b43129828e09163a7e2be757387a3ee718396',
    'fpga_baseline/ip/xilinx_com_hls_fastv2_descriptor_hls_1_0.zip': '08375c7be5a8ed77a8c5a8838e60fcaa20a3e42b832f0d8f7a7546f59e22fc6d',
    'fpga_baseline/ip/xilinx_com_hls_fastv2_layer2_hls_1_0.zip': '1be0cd1a494890ed5c40bfd61744f89cd75d47e1adc68d06651bff5b0a131e1b',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def run_profile(args, directory, log, env):
    # Only this fixed, isolated .cmd profile may initialize vendor PATH.
    words = [str(PROFILE), 'vivado', *map(str, args)]
    if any(any(c in w for c in '\"&|<>^%!\r\n') for w in words):
        raise ValueError('Unsupported command metacharacter in build path')
    # Use a generated batch file so cmd.exe never has to parse nested /c
    # quotation supplied through Python's Windows argv quoting rules.
    launcher = directory / (log.stem + '_launch.cmd')
    def quote(w):
        return '"' + w + '"' if any(c in w for c in ' /\\') else w
    launcher.write_text('@echo off\ncall ' + ' '.join(quote(w) for w in words)
                        + '\nexit /b %ERRORLEVEL%\n', encoding='ascii')
    with log.open('w', encoding='utf-8') as stream:
        return subprocess.run([r'C:\Windows\System32\cmd.exe', '/d', '/c', launcher.name], cwd=directory,
                              env=env, stdout=stream, stderr=subprocess.STDOUT).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--mem2-slices', action='store_true',
                        help='Insert outer register slices on mem2 S00/S01 to break the WREADY feedback path')
    parser.add_argument('--video2', action='store_true',help='Integrate HDMI_2 scanout and fixed double buffers')
    parser.add_argument('--ip-cache', type=Path, help='Copy a completed 2018.3 IP cache into this new run')
    a = parser.parse_args()
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    root = (a.output or PROJECT.parent / '.work' / 'z18' / stamp).resolve()
    root.mkdir(parents=True, exist_ok=False)
    state = {'status': 'PREPARING', 'tool_required': 'Vivado 2018.3',
             'part': 'xc7z015clg485-2', 'top': 's_wrapper', 'orb_mhz': 150,
             'ps_fclk_mhz': 100, 'control_slice_mode': 7, 'jobs': 1, 'max_threads': 1,
             'scope': 'paired ORB PL only; PS SLAM/UI are C++ software',
             'implementation_run': False, 'hardware_programmed': False,
             'mem2_slices': a.mem2_slices,
             'video2': a.video2,
             'input_hashes': INPUTS, 'output': str(root),
             'migration_authorization': 'User: no 2024.2 installation; change to 2018.3 project'}
    status = root / 'status.json'
    try:
        handoff = a.handoff.resolve()
        for name, expected in INPUTS.items():
            if digest(handoff / name) != expected:
                raise ValueError('Frozen input hash mismatch: ' + name)
        (root / 'inputs').mkdir()
        ps_text = (handoff / 'fpga_baseline/top_inputs/ps_config.tcl').read_text(encoding='utf-8')
        # Confirmed ignored/read-only in the first actual 2018.3 run. These
        # values propagate from interfaces; preserve all authored board fields.
        dropped = ['Component_Name', 'PCW_NUM_F2P_INTR_INPUTS',
                   *['PCW_' + port + '_FREQMHZ' for port in
                     ['M_AXI_GP0','M_AXI_GP1','S_AXI_ACP','S_AXI_GP0','S_AXI_GP1',
                      'S_AXI_HP0','S_AXI_HP1','S_AXI_HP2','S_AXI_HP3']]]
        pattern = r'CONFIG\.(' + '|'.join(dropped) + r')\s+([A-Za-z0-9_.+-]+)\s*'
        matches = re.findall(pattern, ps_text)
        if len(matches) != len(dropped):
            raise ValueError('Unexpected PS configuration token format')
        state['ps_config_omitted_readonly'] = dict(matches)
        (root / 'inputs' / 'ps_config.tcl').write_text(re.sub(pattern, '', ps_text), encoding='utf-8')
        files = []
        for name, folder in [('descriptor', 'desc'), ('layer2', 'layer')]:
            archive = handoff / ('fpga_baseline/ip/xilinx_com_hls_fastv2_' + name + '_hls_1_0.zip')
            target = root / 'ip' / folder
            with zipfile.ZipFile(archive) as z:
                bad = z.testzip()
                if bad:
                    raise ValueError('ZIP CRC failure: ' + bad)
                for entry in z.infolist():
                    relative = PurePosixPath(entry.filename)
                    if relative.is_absolute() or '..' in relative.parts or '\\' in entry.filename or ':' in entry.filename:
                        raise ValueError('Unsafe ZIP entry: ' + entry.filename)
                    destination = target.joinpath(*relative.parts)
                    if entry.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(z.read(entry))
                        files.append({'path': destination.relative_to(root).as_posix(), 'sha256': digest(destination)})
        write_json(root / 'staged_ip_hashes.json', files)
        original = (handoff / 'fpga_baseline/top_inputs/build_orb_frequency.tcl').read_text(encoding='utf-8')
        marker = 'set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]'
        if original.count(marker) != 1 or original.count('set_param general.maxThreads 8') != 1:
            raise ValueError('Unexpected baseline Tcl structure')
        # Preserve the original connections/configuration. Remove the complete
        # implementation section, and serialize synthesis to reduce peak RAM.
        body = original.split(marker)[0].replace('set_param general.maxThreads 8', 'set_param general.maxThreads 1')
        body = body.replace('set_property CONFIG.C_EXT_RESET_HIGH {0} $reset',
                            '# C_EXT_RESET_HIGH is propagated from FCLK_RESET0_N in Vivado 2018.3.')
        if a.ip_cache:
            cache = a.ip_cache.resolve()
            if not (cache / '2018.3').is_dir():
                raise ValueError('Expected a completed 2018.3 IP cache directory')
            shutil.copytree(cache, root / 'ip_cache')
            state['ip_cache_source'] = str(cache)
            body = body.replace('create_project p $output -part $part',
                                'create_project p $output -part $part\nconfig_ip_cache -use_cache_location [file join $root ip_cache]')
        if a.mem2_slices:
            needle = '    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $ic'
            if body.count(needle) != 1:
                raise ValueError('Unexpected interconnect configuration structure')
            body = body.replace(needle, needle + '''
    if {$hp == 2} {
        set_property -dict [list CONFIG.S00_HAS_REGSLICE {1} CONFIG.S01_HAS_REGSLICE {1}] $ic
    }''')
            body = body.replace('validate_bd_design\nsave_bd_design', '''validate_bd_design
foreach port {S00 S01} {
    if {[get_property CONFIG.${port}_HAS_REGSLICE [get_bd_cells mem2]] != 1} {
        error "mem2 $port register slice configuration did not take effect"
    }
}
save_bd_design''')
        if a.video2:
            if not a.mem2_slices:
                raise ValueError('--video2 requires the accepted --mem2-slices topology')
            video_dir=root/'video'
            video_dir.mkdir()
            video_inputs=sorted((PROJECT/'rtl/video').glob('*.v'))+sorted((PROJECT/'rtl/video').glob('*.xdc'))
            for path in video_inputs:
                shutil.copyfile(path,video_dir/path.name)
            state['video_inputs_sha256']={p.name:digest(p) for p in video_inputs}
            body=body.replace('create_bd_design s','''set_property XPM_LIBRARIES {XPM_FIFO XPM_CDC} [current_project]
add_files [glob [file join $root video *.v]]
add_files -fileset constrs_1 [glob [file join $root video *.xdc]]
create_bd_design s''')
            body=body.replace('CONFIG.NUM_MI {2}] $control','CONFIG.NUM_MI {3}] $control')
            body=body.replace('set converters [list $control]','''set video [create_bd_cell -type module -reference video_scanout video]
set phy [create_bd_cell -type module -reference hdmi_phy phy]
set video_slice [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 video_control_slice]
set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.ADDR_WIDTH {32} CONFIG.DATA_WIDTH {32} CONFIG.REG_AW {7} CONFIG.REG_W {7} CONFIG.REG_B {7} CONFIG.REG_AR {7} CONFIG.REG_R {7}] $video_slice
connect_bd_intf_net [get_bd_intf_pins control/M02_AXI] [get_bd_intf_pins $video_slice/S_AXI]
connect_bd_intf_net [get_bd_intf_pins $video_slice/M_AXI] [get_bd_intf_pins $video/S_AXI]
lappend control_slices $video_slice
set vclk [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 video_clock]
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} CONFIG.PRIM_SOURCE {No_buffer} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {371.250} CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {74.250} CONFIG.NUM_OUT_CLKS {2} CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.RESET_PORT {resetn} CONFIG.MMCM_DIVCLK_DIVIDE {5} CONFIG.MMCM_CLKFBOUT_MULT_F {37.125} CONFIG.MMCM_CLKOUT0_DIVIDE_F {2.000} CONFIG.MMCM_CLKOUT1_DIVIDE {10}] $vclk
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins $vclk/clk_in1]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins $vclk/resetn]
set vrst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 video_reset]
connect_bd_net [get_bd_pins $vclk/clk_out2] [get_bd_pins $vrst/slowest_sync_clk] [get_bd_pins $video/pixel_clk] [get_bd_pins $phy/pixel_clk]
connect_bd_net [get_bd_pins $vclk/clk_out1] [get_bd_pins $phy/serial_clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins $vrst/ext_reset_in]
connect_bd_net [get_bd_pins $vclk/locked] [get_bd_pins $vrst/dcm_locked]
connect_bd_net [get_bd_pins $vrst/peripheral_reset] [get_bd_pins $video/pixel_reset] [get_bd_pins $phy/reset]
foreach pin {rgb de hsync vsync} {connect_bd_net [get_bd_pins $video/$pin] [get_bd_pins $phy/$pin]}
foreach pin {hdmi_clk_p hdmi_clk_n} {
    connect_bd_net [get_bd_pins $phy/$pin] [create_bd_port -dir O $pin]
}
foreach pin {hdmi_dat_p hdmi_dat_n} {
    connect_bd_net [get_bd_pins $phy/$pin] [create_bd_port -dir O -from 2 -to 0 $pin]
}
set converters [list $control]''')
            needle='    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $ic'
            body=body.replace(needle,needle+'''
    if {$hp == 3} {
        set_property CONFIG.NUM_SI {3} $ic
        set_property CONFIG.S02_HAS_REGSLICE {1} $ic
        connect_bd_intf_net [get_bd_intf_pins $video/M_AXI] [get_bd_intf_pins $ic/S02_AXI]
    }''')
            body=body.replace('foreach core [list $layer $desc] {','''connect_bd_net $clock [get_bd_pins $video/aclk]
connect_bd_net $reset_n [get_bd_pins $video/aresetn]
foreach core [list $layer $desc] {''')
            body=body.replace('-offset 0x43C00000 -range 64K','-offset 0x43C00000 -range 32K')
            body=body.replace('assign_bd_address\nvalidate_bd_design','''assign_bd_address -offset 0x43C08000 -range 32K -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs video/S_AXI/reg0]
assign_bd_address
validate_bd_design''')
            state.update(scope='ORB PL + HDMI_2 720p60 scanout; PS SLAM/UI software',
                         video_control_address='0x43c08000',video_buffers=['0x20b00000','0x20d00000'])
        header = '''# Derived from hash-verified frozen top; user-authorized 2018.3 migration.
if {[version -short] ne "2018.3"} {error "This migration requires Vivado 2018.3"}
'''
        tail = '''report_ip_status -file [file join $output ip_status.rpt]
report_clocks -file [file join $output post_synth_clocks.rpt]
check_timing -verbose -file [file join $output post_synth_check_timing.rpt]
report_drc -file [file join $output post_synth_drc.rpt]
write_checkpoint [file join $output s_wrapper_synth.dcp]
set bb [get_cells -hier -quiet -filter {IS_BLACKBOX == 1}]
if {[llength $bb] != 0} {error "Synthesis has unresolved black boxes: $bb"}
set receipt [open [file join $output SYNTHESIS_COMPLETE.txt] w]
puts $receipt "Vivado [version -short]; xc7z015clg485-2; s_wrapper; 150 MHz target; synthesis flow only"
close $receipt
close_project
exit 0
'''
        script = root / 'synth_only.tcl'
        script.write_text(header + body + tail, encoding='utf-8')
        state['tcl_sha256'] = digest(script)
        state['status'] = 'PREPARED_NOT_RUN'
        write_json(status, state)
        print('Prepared', root, flush=True)
        if a.prepare_only:
            return 0
        if not PROFILE.is_file():
            raise FileNotFoundError(PROFILE)
        env = dict(os.environ)
        env.update(ORB60_ORB_TIMING_ROOT=root.as_posix(), ORB60_ORB_TIMING_JOBS='1',
                   ORB60_ORB_TIMING_FREQUENCY='150', ORB60_CONTROL_SLICE_MODE='7',
                   ORB60_ORB_TIMING_PPC='4')
        env.pop('ORB60_FREQUENCY_VALIDATE_ONLY', None)
        rc = run_profile(['-version'], root, root / 'version.log', env)
        version = (root / 'version.log').read_text(errors='replace')
        state['tool_version_output'] = version.strip()
        if rc or 'Vivado v2018.3 ' not in version:
            raise RuntimeError('Vivado 2018.3 version check failed')
        state['status'] = 'RUNNING'
        write_json(status, state)
        print('Starting Vivado 2018.3 synthesis only, jobs=1, threads=1', flush=True)
        rc = run_profile(['-mode', 'batch', '-notrace', '-source', script,
                          '-log', root / 'vivado.log', '-journal', root / 'vivado.jou'],
                         root, root / 'console.log', env)
        state['returncode'] = rc
        state['status'] = 'PASS' if rc == 0 and (root / 'vivado/SYNTHESIS_COMPLETE.txt').is_file() else 'FAIL'
        write_json(status, state)
        print(state['status'], status, flush=True)
        return 0 if state['status'] == 'PASS' else 1
    except Exception as e:
        state['status'] = 'FAIL'
        state['error'] = str(e)
        write_json(status, state)
        print('FAIL:', e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
