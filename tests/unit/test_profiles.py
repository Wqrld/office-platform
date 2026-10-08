import pytest

import profiles


@pytest.mark.parametrize("selector, labels, want", [
    ({"matchLabels": {"app": "a"}}, {"app": "a", "x": "y"}, True),
    ({"matchLabels": {"app": "a"}}, {"app": "b"}, False),
    ({}, {"app": "a"}, False),                      # empty selector: refused, not "everything"
    (None, {"app": "a"}, False),
    ({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["web", "api"]}]}, {"tier": "api"}, True),
    ({"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["web"]}]}, {"tier": "web"}, False),
    ({"matchExpressions": [{"key": "tier", "operator": "Exists"}]}, {"tier": "x"}, True),
    ({"matchExpressions": [{"key": "tier", "operator": "DoesNotExist"}]}, {"tier": "x"}, False),
    ({"matchLabels": {"app": "a"}, "matchExpressions": [{"key": "tier", "operator": "Exists"}]},
     {"app": "a"}, False),
])
def test_selects(selector, labels, want):
    assert profiles.selects(selector, labels) is want


def test_sizing_keys():
    values = {
        "image": {"tag": "1"},
        "backend": {"replicas": 2, "resources": {"requests": {"cpu": "1"}}, "pdb": {"enabled": False}},
        "frontend": {"replicaCount": 1, "pdb": {"enabled": True, "minAvailable": 1}},
        "workers": [{"name": "w", "resources": {"limits": {"memory": "1Gi"}}}],
    }
    assert profiles.sizing_keys(values) == {
        "backend.replicas": 2,
        "backend.resources": {"requests": {"cpu": "1"}},
        "frontend.replicaCount": 1,
        "frontend.pdb": {"enabled": True, "minAvailable": 1},
        "workers[0].resources": {"limits": {"memory": "1Gi"}},
    }
