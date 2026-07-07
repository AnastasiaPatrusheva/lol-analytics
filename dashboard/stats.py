"""Статистические помощники дашборда."""
from __future__ import annotations

from statistics import NormalDist


def two_proportion_pvalue(wins_a: float, n_a: float, wins_b: float, n_b: float) -> float:
    """Двусторонний p-value two-proportion z-теста (сравнение двух долей побед).

    H0: доли (winrate) равны. Приближение: наблюдения считаются независимыми,
    хотя матчи не полностью независимы (один игрок встречается в нескольких).
    """
    if not n_a or not n_b:
        return 1.0
    p_a, p_b = wins_a / n_a, wins_b / n_b
    pool = (wins_a + wins_b) / (n_a + n_b)
    se = (pool * (1 - pool) * (1 / n_a + 1 / n_b)) ** 0.5
    if se == 0:
        return 1.0
    z = (p_b - p_a) / se
    return 2 * (1 - NormalDist().cdf(abs(z)))
