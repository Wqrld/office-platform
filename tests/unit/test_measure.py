import pytest

import measure


@pytest.mark.parametrize("v, want", [
    (None, 0.0), ("", 0.0), ("garbage", 0.0),
    ("2", 2.0), (2, 2.0), ("500m", 0.5), ("1.5", 1.5),
    ("1k", 1e3), ("1M", 1e6), ("1G", 1e9),
    ("1Ki", 1024.0), ("128Mi", 128 * 2**20), ("2Gi", 2 * 2**30), ("1Ti", 2**40),
])
def test_quantity(v, want):
    assert measure.quantity(v) == pytest.approx(want)


def test_charge_limitrange_and_besteffort():
    pod = {"containers": [{"resources": {"requests": {"cpu": "100m", "memory": "1Mi"}}}, {}]}
    cpu, mem, note = measure.charge(pod, 2, None)
    assert (cpu, mem, note) == (pytest.approx(0.2), pytest.approx(2 * 2**20), "!NO REQUESTS")
    cpu, mem, note = measure.charge(pod, 2, (0.05, 2**20))
    assert (cpu, mem, note) == (pytest.approx(0.3), pytest.approx(4 * 2**20), "~limitrange")
    assert measure.charge({"containers": [{"resources": {"requests": {"cpu": "1"}}}]}, 1, None) == (1.0, 0.0, "")


@pytest.mark.parametrize("doc, want", [
    ({"kind": "Cluster", "spec": {"instances": 3, "resources": {"requests": {"cpu": "1"}}}}, (3, {"cpu": "1"})),
    ({"kind": "Keycloak", "spec": {}}, (1, {})),
    ({"kind": "GarageCluster", "spec": {"storage": {"replicas": 2}}}, (2, {})),
    ({"kind": "Deployment", "spec": {}}, None),
])
def test_operator_pods(doc, want):
    assert measure.operator_pods(doc) == want
