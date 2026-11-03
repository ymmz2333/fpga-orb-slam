"""Prepare XRT section inputs for the verified standalone DPU; no board loading."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def prepare(job: Path, kernel_xml: Path, output: Path, *, expected_kind="dpu_only") -> dict:
    manifest = json.loads((job / "release_manifest.json").read_text())
    if expected_kind not in ("dpu_only", "dpu_points") or not manifest.get("export_verified") or manifest.get("platform_kind") != expected_kind:
        raise ValueError("A verified matching platform export is required: " + expected_kind)
    for name, expected in manifest["sha256"].items():
        if sha(job / name) != expected:
            raise ValueError("Retained release changed: " + name)
    frequencies = manifest["clocks_mhz"]
    fingerprint = manifest["dpu_fingerprint"]
    if fingerprint != "0x101000016010407":
        raise ValueError("Unsupported DPU fingerprint")
    addresses = (job / "address_map.tsv").read_text()
    if expected_kind == "dpu_points":
        if frequencies != dict(control_mhz=150, dpu_mhz=250, dsp_mhz=500):
            raise ValueError("Unreviewed DPU+points clocks")
        mapping = {r.split('\t')[0]: tuple(int(x, 0) for x in r.split('\t')[1:]) for r in addresses.splitlines()}
        required = {'/ps/Data/SEG_point_project_Reg': (0xa2000000, 0x10000)}
        for name in ('input', 'output'):
            required['/point_project/Data_m_axi_'+name+'_mem/SEG_ps_HP2_DDR_LOW'] = (0, 0x80000000)
        if any(mapping.get(k) != v for k, v in required.items()):
            raise ValueError("Point-core control/shared DDR mapping differs")
    if "/ps/Data/SEG_dpu_reg0\t0x00A1000000\t0x0001000000" not in addresses:
        raise ValueError("DPU control window differs")
    for master, port in (("DPU0_M_AXI_INSTR", "HPC0"), ("DPU0_M_AXI_DATA0", "HP0"), ("DPU0_M_AXI_DATA1", "HP1")):
        if f"/dpu/{master}/SEG_ps_{port}_DDR_LOW\t0x0000000000\t0x0080000000" not in addresses:
            raise ValueError("DPU DDR mapping differs")
    source_kernel = ET.parse(kernel_xml).getroot().find("kernel")
    if source_kernel is None or source_kernel.attrib["name"] != "DPUCZDX8G":
        raise ValueError("Official DPU kernel metadata required")
    args = source_kernel.findall("args/arg")
    offsets = [0x40, 0x44, 0x48, 0x50, 0x58, *range(0x60, 0xA0, 8)]
    if len(args) != 13 or [int(a.attrib["id"]) for a in args] != list(range(13)) or [int(a.attrib["offset"], 0) for a in args] != offsets:
        raise ValueError("Unexpected DPU register ABI")
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")

    ip = {"m_type": "IP_KERNEL", "m_int_enable": "1", "m_interrupt_id": "0", "m_ip_control": "AP_CTRL_HS",
          "m_base_address": "0xa1000000", "m_name": "DPUCZDX8G:DPUCZDX8G_1"}
    save("IP_LAYOUT.json", {"ip_layout": {"m_count": "1", "m_ip_data": [ip]}})
    # Three AXI access ports alias the same low 2 GiB of PS DDR. These are not
    # independent memory chips; Linux CMA/XRT controls actual BO allocation.
    memories = [{"m_type": "MEM_DRAM", "m_used": "1", "m_sizeKB": "0x200000", "m_base_address": "0x0", "m_tag": tag}
                for tag in ("HPC0", "HP0", "HP1")]
    save("MEM_TOPOLOGY.json", {"mem_topology": {"m_count": "3", "m_mem_data": memories}})
    connections = [{"arg_index": str(i), "m_ip_layout_index": "0", "mem_data_index": str(0 if i <= 4 else 1 if i <= 8 else 2)}
                   for i in range(3, 13)]
    save("CONNECTIVITY.json", {"connectivity": {"m_count": "10", "m_connection": connections}})
    clocks = [{"m_freq_Mhz": str(freq), "m_type": typ, "m_name": name} for freq, typ, name in
              ((frequencies["control_mhz"], "SYSTEM", "s_axi_aclk"), (frequencies["dpu_mhz"], "KERNEL", "m_axi_dpu_aclk"), (frequencies["dsp_mhz"], "DATA", "dpu_2x_clk"))]
    save("CLOCK_FREQ_TOPOLOGY.json", {"clock_freq_topology": {"m_count": "3", "m_clock_freq": clocks}})
    project = ET.Element("project", name="kv260_" + expected_kind)
    platform_name = "kv260_" + expected_kind + "_" + str(frequencies["dpu_mhz"])
    platform = ET.SubElement(project, "platform", vendor="xilinx", boardid=platform_name, name=platform_name, featureRomTime="0")
    device = ET.SubElement(platform, "device")
    core = ET.SubElement(device, "core", name="OCL_REGION_0", target="bitstream", type="clc_region", clockFreq=str(frequencies["dpu_mhz"]) + "MHz", numComputeUnits="1")
    kernel = ET.SubElement(core, "kernel", source_kernel.attrib)
    for path in ("ports/port", "args/arg"):
        for element in source_kernel.findall(path):
            ET.SubElement(kernel, element.tag, element.attrib)
    instance = ET.SubElement(kernel, "instance", name="DPUCZDX8G_1")
    ET.SubElement(instance, "addrRemap", base="0xa1000000", range="0x1000000", port="S_AXI_CONTROL")
    ET.indent(project)
    ET.ElementTree(project).write(output / "EMBEDDED_METADATA.xml", encoding="utf-8", xml_declaration=True)
    if expected_kind == "dpu_points":
        # This platform uses /dev/dpu and UIO, not XRT CU execution. Do not
        # advertise native DPU registers as an ap_ctrl_hs scheduled kernel.
        save("IP_LAYOUT.json", {"ip_layout": {"m_count": "0", "m_ip_data": []}})
        save("CONNECTIVITY.json", {"connectivity": {"m_count": "0", "m_connection": []}})
        save("MEM_TOPOLOGY.json", {"mem_topology": {"m_count": "1", "m_mem_data": [dict(memories[0],m_tag="PS_DDR_HP2")]}})
        core.set("numComputeUnits", "0");core.remove(kernel)
        ET.ElementTree(project).write(output / "EMBEDDED_METADATA.xml", encoding="utf-8", xml_declaration=True)
    record = {"status": "SECTION_INPUTS_PREPARED_NOT_XRT_OR_DPU_VALIDATED", "hardware_loaded": False,
              "job": job.name, "platform_kind": expected_kind, "kernel_xml_sha256": sha(kernel_xml), "release_manifest_sha256": sha(job / "release_manifest.json"),
              "dpu_fingerprint": fingerprint, "clocks_mhz": frequencies, "control_base": "0xa1000000", "interrupt_index": 0,
              "memory_scope": "Three aliases of low PS DDR; actual kernel/XRT BO allocation must be checked on board",
              "execution_scope": "Metadata registration/BO allocation only; DPU executes through vivado_ioctl; optional point core through UIO, never XRT scheduled",
              "files": {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
    save("METADATA_INPUTS.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(os.environ.get("FPGA_PROJECT_ROOT", str(Path(__file__).resolve().parents[3])))
    kernel = root / "orb60/build/kv260_system/vendor_sources/dpu_trd/DPUCZDX8G/prj/Vitis/kernel_xml/dpu/kernel.xml"
    record = prepare(args.job.resolve(), kernel, args.output.resolve())
    print(json.dumps({key: record[key] for key in ("status", "control_base", "dpu_fingerprint")}))


if __name__ == "__main__":
    main()
