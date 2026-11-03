import pytest
from orb60.kv260.preview_transport import PreviewTransport


def test_lossless_color_identity_keeps_direct_y_separate_from_bgr_gray():
    import cv2
    import numpy as np
    import zlib
    from types import SimpleNamespace
    from orb60.kv260.preview_transport import validate_final_preview
    image=np.full((720,960,3),[20,60,200],np.uint8)
    ok,packet=cv2.imencode('.bmp',image);assert ok
    meta=dict(image_codec='bmp',source_bgr_crc=zlib.crc32(image.tobytes()),raw_gray_crc=123)
    snap=SimpleNamespace(meta=meta,jpeg=packet.tobytes())
    validate_final_preview(snap,'ram_bmp')
    meta['source_bgr_crc']^=1
    with pytest.raises(ValueError):validate_final_preview(snap,'ram_bmp')
    del meta['source_bgr_crc']
    with pytest.raises(ValueError):validate_final_preview(snap,'ram_bmp')
    meta['raw_gray_crc']=zlib.crc32(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).tobytes())
    validate_final_preview(snap,'ram_bmp')


def test_default_does_not_create_run_or_ram_files(tmp_path):
    run=tmp_path/'run';control=tmp_path/'control'
    t=PreviewTransport('file_jpeg',run,control)
    assert t.start() is None and t.close()==[]
    assert not run.exists() and not control.exists()


def test_ram_is_bounded_owned_and_final_packet_is_preserved(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir();control=tmp_path/'control'
    monkeypatch.setattr(PreviewTransport,'_ram_root',lambda self:tmp_path)
    t=PreviewTransport('ram_bmp',run,control);ram=t.start()
    assert ram.parent==tmp_path and ram!=run
    (ram/'latest.orbv').write_bytes(b'exact final packet');(ram/'status.json').write_text('{"state":"COMPLETED"}')
    with pytest.raises(ValueError):t.start()
    receipts=t.close();assert len(receipts)==2
    assert (run/'tracking/telemetry/latest.orbv').read_bytes()==b'exact final packet'
    assert not ram.exists() and t.close()==receipts


def test_native_start_failure_keeps_debug_evidence_without_creating_run(tmp_path,monkeypatch):
    monkeypatch.setattr(PreviewTransport,'_ram_root',lambda self:tmp_path)
    run=tmp_path/'absent';control=tmp_path/'control';control.mkdir()
    t=PreviewTransport('ram_bmp',run,control);ram=t.start();(ram/'status.json').write_text('{"state":"ERROR"}')
    t.close();assert not run.exists()
    assert (control/'preview_failure/status.json').is_file() and not ram.exists()


def test_unknown_transport_rejected(tmp_path):
    with pytest.raises(ValueError):PreviewTransport('automatic',tmp_path/'run',tmp_path/'control')
