"""Read-only preflight for the local WSL SLAM checkout and physical FPGA."""
import hashlib
import json
from pathlib import Path
import socket


def find_project():
    candidates=[Path.home()/'orbslam3_cpu_baseline']+list(Path('/home').glob('*/orbslam3_cpu_baseline'))
    roots=list(dict.fromkeys(p.resolve() for p in candidates if (p/'vendor/ORB_SLAM3/Examples/Monocular/mono_euroc').is_file()))
    if len(roots)!=1:raise RuntimeError('Set the WSL SLAM project explicitly: '+str(roots))
    return roots[0]


def find_fpga():
    for _,name in socket.if_nameindex():
        if not name.startswith('eth'):continue
        try:
            if (Path('/sys/class/net')/name/'operstate').read_text().strip()!='up':continue
            with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as conn:
                conn.settimeout(1.5);conn.connect(('fe80::20a:35ff:fe00:122',5600,0,socket.if_nametoindex(name)))
            return '[fe80::20a:35ff:fe00:122%'+name+']:5600',name
        except OSError:pass
    raise RuntimeError('No active WSL Ethernet interface can reach the FPGA feature service')


if __name__=='__main__':
    project=find_project();source=project/'vendor/ORB_SLAM3';host,interface=find_fpga()
    print(json.dumps(dict(project=str(project),host=host,interface=interface,
                         telemetry_header_sha256=hashlib.sha256((source/'include/OrbTelemetry.h').read_bytes()).hexdigest(),
                         build_dirs=[str(x) for x in source.glob('build*')]),indent=2))
