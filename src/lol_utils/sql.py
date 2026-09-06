"""SQL-макросы, общие для сборки витрин и для дашборда.

Единственное место, где живёт формула интервала Уилсона. Раньше она была
скопирована в build_star_schema.py, dashboard/data.py и в сам тест — правка в
одном месте молча расходилась с остальными.
"""
from __future__ import annotations

from statistics import NormalDist

# Уровень доверия 95% для одиночной оценки: этим z строится рейтинг чемпионов.
Z_95 = 1.96


def z_for_multiple_tests(n_tests: int, alpha: float = 0.05) -> float:
    """z с поправкой Бонферрони на n_tests одновременных проверок.

    Вердикт «значимо сильный» выносится не одному чемпиону, а всем сразу
    (~170 проверок). При alpha=0.05 и истинном winrate 50% у всех примерно
    9 чемпионов получили бы ярлык случайно. Поправка поднимает порог так,
    чтобы 5% относились ко всему набору, а не к каждой проверке отдельно.
    """
    n_tests = max(1, int(n_tests))
    return NormalDist().inv_cdf(1 - alpha / (2 * n_tests))


# Граница интервала Уилсона: p — доля успехов, n — число наблюдений,
# z — квантиль нормального распределения, sign — «-» для нижней, «+» для верхней.
# DuckDB не умеет перегружать макрос по числу аргументов, поэтому вариант с
# фиксированным z=1.96 живёт под отдельным именем, но собирается из этого же шаблона.
_BOUND = ("(p + {z}*{z}/(2*n) {sign} {z}*sqrt((p*(1-p) + {z}*{z}/(4*n))/n))"
          " / (1 + {z}*{z}/n)")

WILSON_MACROS = "\n".join(
    f"CREATE OR REPLACE MACRO {name}({params}) AS {_BOUND.format(z=z, sign=sign)};"
    for name, params, z in (("wilson_low", "p, n", Z_95), ("wilson_high", "p, n", Z_95),
                            ("wilson_low_z", "p, n, z", "z"), ("wilson_high_z", "p, n, z", "z"))
    for sign in ("-" if "low" in name else "+",)
)


def install_macros(con) -> None:
    """Регистрирует макросы Уилсона в подключении DuckDB."""
    con.execute(WILSON_MACROS)
