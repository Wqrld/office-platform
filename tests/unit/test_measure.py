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
