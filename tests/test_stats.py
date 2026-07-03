"""Тесты статистики: интервал Уилсона (DuckDB-макрос) и ярлыки архетипов."""
import numpy as np
import duckdb

from build_player_segments import label_clusters, FEATURES


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("""CREATE OR REPLACE MACRO wilson_low(p, n) AS
        (p + 1.96*1.96/(2*n) - 1.96*sqrt((p*(1-p) + 1.96*1.96/(4*n))/n)) / (1 + 1.96*1.96/n)""")
    con.execute("""CREATE OR REPLACE MACRO wilson_high(p, n) AS
        (p + 1.96*1.96/(2*n) + 1.96*sqrt((p*(1-p) + 1.96*1.96/(4*n))/n)) / (1 + 1.96*1.96/n)""")
    return con


def test_wilson_bounds_bracket_point_estimate():
    con = _con()
    lo, hi = con.execute("SELECT wilson_low(0.5, 100), wilson_high(0.5, 100)").fetchone()
    assert lo < 0.5 < hi


def test_wilson_wider_on_small_sample():
    con = _con()
    width_small = con.execute("SELECT wilson_high(0.5, 10) - wilson_low(0.5, 10)").fetchone()[0]
    width_large = con.execute("SELECT wilson_high(0.5, 1000) - wilson_low(0.5, 1000)").fetchone()[0]
    # чем меньше выборка — тем шире интервал
    assert width_small > width_large


def test_wilson_known_value():
    con = _con()
    lo = con.execute("SELECT wilson_low(0.5, 100)").fetchone()[0]
    # стандартное значение нижней границы Уилсона для 50/100 ≈ 0.4038
    assert abs(lo - 0.4038) < 0.01


def test_archetype_by_dominant_feature():
    # FEATURES = [kda, cs_per_min, damage_per_min, vision_per_min, gold_per_min]
    centers = np.array([
        [0, 0, 0, 2.0, 0],   # доминирует обзор
        [0, 0, 2.0, 0, 0],   # доминирует урон
    ])
    labels = label_clusters(centers, FEATURES)
    assert labels[0] == "Саппорт (обзор)"
    assert labels[1] == "Агрессивный (урон)"


def test_archetype_collision_disambiguated():
    centers = np.array([
        [0, 2.0, 0, 0, 1.0],   # фарм доминирует, золото — второе
        [0, 2.0, 1.0, 0, 0],   # фарм доминирует, урон — второй
    ])
    labels = label_clusters(centers, FEATURES)
    # оба кластера «фарм»-доминантные, но ярлыки не должны совпасть
    assert labels[0] != labels[1]
