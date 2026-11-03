"""Owned latest-preview storage; RAM mode retains a final disk evidence copy."""
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile
from .native_products import digest


def validate_final_preview(snapshot,backend):
    if backend=='file_jpeg':return
    if backend!='ram_bmp' or snapshot.meta.get('image_codec')!='bmp' or not snapshot.jpeg.startswith(b'BM'):
        raise ValueError('Selected lossless preview codec does not match the native packet')
    import cv2
    import numpy as np
    import zlib
    image=cv2.imdecode(np.frombuffer(snapshot.jpeg,np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape!=(720,960,3) or image.dtype!=np.uint8:
        raise ValueError('Invalid original-size lossless preview')
    if 'source_bgr_crc' in snapshot.meta:
        # Direct source Y and BGR->gray are intentionally distinct contracts.
        # FrozenFrameIdentities checks both independent source CRCs in the caller.
        if zlib.crc32(image.tobytes())!=int(snapshot.meta['source_bgr_crc']):
            raise ValueError('Lossless RGB preview differs from the verified source frame')
    else:
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        if zlib.crc32(gray.tobytes())!=int(snapshot.meta['raw_gray_crc']):
            raise ValueError('Lossless preview pixels differ from the verified source frame')


class PreviewTransport:
    def __init__(self,backend,run_root,control):
        if backend not in ('file_jpeg','ram_bmp'):raise ValueError('Explicit supported preview transport required')
        self.backend=backend;self.run_root=Path(run_root).resolve();self.control=Path(control).resolve()
        self.temporary=None;self.path=None;self.shared_root=None;self.persisted=[]

    def _ram_root(self):
        if platform.system()!='Linux':raise ValueError('RAM preview requires Linux tmpfs')
        root=Path('/dev/shm').resolve()
        kind=subprocess.check_output(['stat','-f','-c','%T',str(root)],text=True).strip()
        if kind!='tmpfs' or shutil.disk_usage(root).free<16*1024*1024:
            raise ValueError('Preview requires at least16MiB of available tmpfs')
        return root

    def start(self):
        if self.path is not None:raise ValueError('Preview storage already started')
        if self.backend=='file_jpeg':return None
        self.shared_root=self._ram_root().resolve()
        self.temporary=tempfile.TemporaryDirectory(prefix='orb60_preview_',dir=self.shared_root)
        self.path=Path(self.temporary.name).resolve()
        if self.path.parent!=self.shared_root:raise ValueError('Unexpected owned RAM preview directory')
        return self.path

    def close(self):
        if self.temporary is None:return self.persisted
        try:
            destination=(self.run_root/'tracking/telemetry') if self.run_root.is_dir() else (self.control/'preview_failure')
            destination.mkdir(parents=True,exist_ok=True)
            for name in ('latest.orbv','status.json'):
                source=self.path/name
                if source.is_symlink():raise ValueError('Symlink in owned preview storage')
                if not source.exists():continue
                if not source.is_file():raise ValueError('Invalid preview evidence file')
                target=destination/name;part=target.with_name(name+'.preview_part')
                shutil.copyfile(source,part);part.replace(target)
                self.persisted.append(dict(path=str(target),bytes=target.stat().st_size,sha256=digest(target)))
        finally:
            # The directory was created by TemporaryDirectory, never supplied as
            # a cleanup target by a caller. No project output is removed.
            if self.path.parent!=self.shared_root or not self.path.name.startswith('orb60_preview_'):
                raise ValueError('Owned temporary preview path changed')
            self.temporary.cleanup();self.temporary=None
        return self.persisted
