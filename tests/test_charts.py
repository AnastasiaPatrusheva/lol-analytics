"""Тесты общей геометрии радара (dashboard/charts.py)."""
import numpy as np
import pandas as pd

from dashboard.charts import normalize, ring


def test_ring_starts_at_top_and_goes_clockwise():
    pts = ring(1.0, 4)
    assert len(pts) == 4                        # контур замыкает Altair, лишней точки нет
    np.testing.assert_allclose(pts[["x", "y"]].to_numpy(),
                               [[0, -1], [1, 0], [0, 1], [-1, 0]], atol=1e-9)
    assert list(pts["order"]) == [0, 1, 2, 3]   # порядок обхода вершин


def test_ring_scales_each_vertex_by_its_own_radius():
    pts = ring(np.array([1.0, 0.5, 0.0]), 3)
    np.testing.assert_allclose(np.hypot(pts["x"], pts["y"]), [1.0, 0.5, 0.0], atol=1e-9)


def test_normalize_is_share_of_column_max():
    df = pd.DataFrame({"a": [2.0, 1.0], "b": [0.0, 0.0]}, index=["x", "y"])
    out = normalize(df, ["a", "b"])
    assert out.loc["x", "a"] == 1.0 and out.loc["y", "a"] == 0.5
    assert out["b"].tolist() == [0.0, 0.0]      # нулевая колонка -> 0, не NaN
