"""SQL-макросы, общие для сборки витрин и для дашборда.

Единственное место, где живут формулы интервала Уилсона, пулированного KDA и
разбора номера патча. Раньше она была
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


# KDA пулированный: суммы убийств, помощей и смертей за все матчи, потом деление.
# Суммы внутри макроса, чтобы его нельзя было применить к KDA отдельных матчей:
# среднее отношений завышает игроков с редкими матчами без смертей.
# Патч из game_version: «16.11.673.4372» -> «16.11».
OTHER_MACROS = """
CREATE OR REPLACE MACRO kda_pooled(kills, deaths, assists) AS
    (SUM(kills) + SUM(assists)) * 1.0 / GREATEST(SUM(deaths), 1);
CREATE OR REPLACE MACRO patch_of(game_version) AS
    split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2);
"""


def patch_key(patch: str) -> list[int]:
    """Ключ сортировки патчей по номеру: 16.9 < 16.10, а не как строки."""
    return [int(x) for x in patch.split(".") if x.isdigit()]


def install_macros(con) -> None:
    """Регистрирует макросы (Уилсон, KDA, патч) в подключении DuckDB."""
    con.execute(WILSON_MACROS)
    con.execute(OTHER_MACROS)
