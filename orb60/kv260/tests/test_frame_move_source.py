import pytest
from orb60.kv260.ps.check_frame_move import transform


def test_frame_members_and_copy_constructor_remain_unchanged():
    source='class Frame {\npublic:\n    Frame(const Frame &frame);\nprivate:\n    int N;\n    std::vector<size_t> mGrid[64][48];\n};\n'
    changed=transform(source)
    added='\n    Frame& operator=(const Frame&) = default;\n    Frame& operator=(Frame&&) = default;'
    assert changed.replace(added,'')==source
    with pytest.raises(ValueError):transform(source+source)
    with pytest.raises(ValueError):transform(source.replace('Frame(const Frame &frame);','Frame(const Frame &);'))
    with pytest.raises(ValueError):transform(source+'Frame& operator=(const Frame&);')
