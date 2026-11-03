"""Native board version formats, without the optional model-export dependencies."""
import pytest
from orb60.dense.kv260.preflight import validate, parse_xrt_version, check_xrt


def test_native_vart_release_string_and_wrong_versions():
    release = {'ID': 'ubuntu', 'VERSION_ID': '22.04'}
    query = {'kernels': [{'fingerprint': '0x101000016010407'}]}
    arch = {'fingerprint': '0x101000016010407'}
    assert validate(release, 'aarch64', query, arch,
                    'Xilinx vart-runner Version: 2.5.0-c26eae36 2026-11-02') == ['0x101000016010407']
    for text in ('Xilinx vart-runner Version: 3.5.0', '12.5.0', 'unversioned'):
        with pytest.raises(RuntimeError):
            validate(release, 'aarch64', query, arch, text)


def test_native_xrt_output_retains_explicit_version_gate():
    text = 'Version              : 2.13.0\nBranch : \nHash : \nZOCL : 2.13.0, \n'
    actual = parse_xrt_version(text)
    assert check_xrt({'XRT Runtime Probe': {'version': actual}}, '2.13') == ['2.13.0']
    with pytest.raises(RuntimeError):
        check_xrt({'XRT Runtime Probe': {'version': actual}}, '2.14')


@pytest.mark.parametrize('text', ['ZOCL : 2.13.0\n', 'Version : unknown\n',
                                  'Version : 2.13.0\nVersion : 2.14.0\n'])
def test_missing_or_ambiguous_version_is_rejected(text):
    with pytest.raises(RuntimeError):
        parse_xrt_version(text)
