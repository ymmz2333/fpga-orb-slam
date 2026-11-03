import pytest
from orb60.kv260.cpu_policy import validate_policy


def test_optional_policy_preserves_default_and_disjoint_cores():
    assert validate_policy({},[0,1,2,3]) is None
    assert validate_policy({'tracking_core':3,'background_cores':[0,1,2]},[0,1,2,3])==(3,(0,1,2))


@pytest.mark.parametrize('config',[
    {'tracking_core':3,'background_cores':[0,3]},
    {'tracking_core':4,'background_cores':[0,1,2]},
    {'tracking_core':3,'background_cores':[0,0]},
    {'tracking_core':3,'background_cores':[]},
    {'tracking_core':True,'background_cores':[0,2]},
])
def test_invalid_policy_is_rejected_instead_of_partially_applied(config):
    with pytest.raises(ValueError):validate_policy(config,[0,1,2,3])
