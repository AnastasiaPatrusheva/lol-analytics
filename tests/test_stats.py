"""Тесты статистики: интервал Уилсона (DuckDB-макрос) и ярлыки архетипов.

Макросы берутся из lol_utils.sql — того же модуля, что использует сборка витрин
и дашборд. Раньше тест держал собственную копию формулы и оставался зелёным,
даже если продакшн-формулу меняли.
"""
import numpy as np
import duckdb
import pytest

from lol_utils.sql import Z_95, install_macros, z_for_multiple_tests
from build_player_segments import label_clusters, FEATURES


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    install_macros(con)
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


def test_wilson_two_and_three_arg_forms_agree():
    # обе формы собираются из одного шаблона: при z = 1.96 они обязаны совпадать
    lo2, lo3 = _con().execute(
        f"SELECT wilson_low(0.55, 200), wilson_low_z(0.55, 200, {Z_95})").fetchone()
    assert lo2 == pytest.approx(lo3)


def test_bonferroni_widens_interval():
    z = z_for_multiple_tests(172)
    assert z > Z_95
    lo_single, lo_adj = _con().execute(
        f"SELECT wilson_low(0.55, 200), wilson_low_z(0.55, 200, {z})").fetchone()
    # поправка на множественные сравнения делает вердикт строже, а не мягче
    assert lo_adj < lo_single


def test_bonferroni_single_test_equals_95():
    assert z_for_multiple_tests(1) == pytest.approx(Z_95, abs=1e-3)


def test_archetype_by_dominant_feature():
    # FEATURES = [kda, cs_per_min, damage_per_min, vision_per_min, gold_per_min]
    centers = np.array([
        [0, 0, 0, 2.0, 0],   # доминирует обзор
        [0, 0, 2.0, 0, 0],   # доминирует урон
    ])
    labels = label_clusters(centers, FEATURES)
    assert labels[0] == "Играет на обзор"
    assert labels[1] == "Агрессивный"


def test_archetype_collision_disambiguated():
    centers = np.array([
        [0, 2.0, 0, 0, 1.0],   # фарм доминирует, золото — второе
        [0, 2.0, 1.0, 0, 0],   # фарм доминирует, урон — второй
    ])
    labels = label_clusters(centers, FEATURES)
    # оба кластера «фарм»-доминантные, но ярлыки не должны совпасть
    assert labels[0] != labels[1]
