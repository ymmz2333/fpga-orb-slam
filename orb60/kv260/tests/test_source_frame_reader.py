import pytest
from orb60.kv260.source_frame_map import SourceFrameMapReader,FrozenFrameIdentities


def test_partial_lines_are_consumed_once_and_timestamps_remain_exact(tmp_path):
    p=tmp_path/'source.csv';p.write_bytes(b'timestamp_ns,source_frame_')
    reader=SourceFrameMapReader(p);assert reader.update()=={}
    stamp=1793620000000000001
    with p.open('ab') as f:f.write(('index\n%d,0\n%d,'%(stamp,stamp+33333333)).encode())
    assert reader.update()=={stamp:0}
    for _ in range(10):assert reader.update()=={stamp:0}
    assert reader.rows_parsed==1 and reader.bytes_read==p.stat().st_size
    with p.open('ab') as f:f.write(b'1\n')
    assert reader.update()=={stamp:0,stamp+33333333:1}
    assert reader.rows_parsed==2 and reader.bytes_read==p.stat().st_size


def test_atomic_rotation_clears_old_generation(tmp_path):
    p=tmp_path/'source.csv';p.write_text('timestamp_ns,source_frame_index\n100,0\n')
    reader=SourceFrameMapReader(p);assert reader.update()=={100:0}
    replacement=tmp_path/'replacement.csv';replacement.write_text('timestamp_ns,source_frame_index\n200,4096\n300,4097\n')
    replacement.replace(p)
    assert reader.update()=={200:4096,300:4097}


@pytest.mark.parametrize('row',('100,1','101,0','nan,2','100.1,2','101,2,3'))
def test_duplicate_reordered_or_noninteger_identity_is_rejected(tmp_path,row):
    p=tmp_path/'source.csv';p.write_text('timestamp_ns,source_frame_index\n100,0\n'+row+'\n')
    with pytest.raises(ValueError):SourceFrameMapReader(p).update()


def test_bounded_reader_retains_latest_rows_without_parsing_twice(tmp_path):
    p=tmp_path/'source.csv';p.write_text('timestamp_ns,source_frame_index\n'+''.join('%d,%d\n'%(i+1,i) for i in range(8300)))
    reader=SourceFrameMapReader(p);value=reader.update()
    assert len(value)==8192 and value[8300]==8299 and 1 not in value
    reader.update();assert reader.rows_parsed==8300


def test_native_color_preview_retains_independent_frozen_identity_check(tmp_path):
    p=tmp_path/'identities.csv';p.write_text('source_frame_id,timestamp_ns,gray_crc\n0,1793620000000000001,334455\n')
    frozen=FrozenFrameIdentities(p)
    meta=dict(frame_index=0,timestamp_ns=1793620000000000001,raw_gray_crc=334455)
    frozen.check(meta)
    for field in meta:
        corrupted={**meta,field:meta[field]+1}
        with pytest.raises(ValueError):frozen.check(corrupted)
