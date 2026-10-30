"""Package the already accepted volatile Linux runtime; does not program a board."""
from pathlib import Path
import tarfile
from prepare import ROOT,copy
from common import sha

def main():
    folder=ROOT/'.work/handoff/recovery_20261022_lf'
    folder.mkdir(parents=True,exist_ok=False)
    base=ROOT/'orb60/build/linux/reproduce_bringup150_v2'
    for name in ('load_board.sh','board-probe','orb60_150mhz.bit.bin','firmware.sha256','acz7015-orb60.dtbo'):
        copy(base/name,folder/'orb60-150'/name)
    copy(ROOT/'orb60/build/linux/frame_pipeline_20261021/orb60-server-arm',folder/'orb60-server-pipeline')
    if sha(folder/'orb60-server-pipeline')!='b433953a6faa98dd2c36db24fc96e5c855e6ea0bbe6c5b56f5476c22d6aa60d8':
        raise ValueError('Server identity mismatch')
    wc=ROOT/'orb60/build/linux/writecombine_20261021_side'
    copy(wc/'module/orb60_wc_uio.ko',folder/'orb60-wc-uio.ko')
    copy(wc/'ddr-bench-arm',folder/'orb60-wc-ddr-bench-arm')
    copy(ROOT/'orb60/linux/switch_server.sh',folder/'orb60-switch-server.sh')
    for src,dst in (('activate_board.sh','orb60-wc-activate.sh'),('restore_board.sh','orb60-wc-restore.sh')):
        copy(ROOT/'orb60/experiments/ps_writecombine'/src,folder/dst)
    for p in folder.rglob('*.sh'):p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
    (folder/'handoff-runtime.sha256').write_bytes(''.join(sha(p)+'  '+p.relative_to(folder).as_posix()+'\n'
        for p in sorted(folder.rglob('*')) if p.is_file()).encode('ascii'))
    script='''#!/bin/sh
set -eu
cd /tmp
test ! -d /sys/kernel/config/device-tree/overlays/orb60
test ! -e /tmp/orb60-150/server.pid
sha256sum -c handoff-runtime.sha256
chmod 755 orb60-150/board-probe orb60-server-pipeline orb60-wc-ddr-bench-arm
sh orb60-150/load_board.sh
sh orb60-switch-server.sh /tmp/orb60-server-pipeline /tmp/orb60-pipeline.log --profile --pipeline
sh orb60-wc-activate.sh
test "$(cat /sys/class/uio/uio0/name)" = orb60-writecombine-experiment
echo HANDOFF_VOLATILE_RUNTIME_RESTORED
'''
    (folder/'handoff-restore-runtime.sh').write_bytes(script.encode('ascii'))
    archive=folder.with_suffix('.tar.gz')
    with tarfile.open(archive,'w:gz') as t:
        for p in sorted(folder.rglob('*')):
            if p.is_file():t.add(p,arcname=p.relative_to(folder).as_posix())
    print(archive,sha(archive))

if __name__=='__main__':main()
