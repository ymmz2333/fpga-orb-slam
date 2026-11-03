import json
import pytest
from orb60.kv260 import packed_stream as stream


@pytest.mark.parametrize('value',['noport','host:0','host:65536','[fe80::1]18791','host:abc',':123'])
def test_stream_endpoint_requires_explicit_valid_port(value):
    with pytest.raises(ValueError):stream.endpoint(value)


def test_scoped_ipv6_receiver_is_preserved():
    assert stream.endpoint('[fe80::123%16]:18791')==('fe80::123%16',18791)
    assert stream.endpoint('192.168.26.2:18791')==('192.168.26.2',18791)


def test_stream_source_cannot_skip_master_or_header_checks(tmp_path):
    raw=tmp_path/'raw';raw.write_bytes(b'not a source')
    proof=tmp_path/'proof.json';proof.write_text(json.dumps(dict(status='RUNNING')))
    headers=tmp_path/'headers.bin';headers.write_bytes(b'')
    with pytest.raises(ValueError):stream.send(raw,proof,headers,'127.0.0.1:18791',tmp_path/'report.json')
    assert not (tmp_path/'report.json').exists()
