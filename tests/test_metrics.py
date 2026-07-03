"""Тесты производных метрик (lol_utils.metrics.add_metrics)."""
import pandas as pd

from lol_utils.metrics import add_metrics


def _base() -> pd.DataFrame:
    return pd.DataFrame({
        "kills": [5], "deaths": [2], "assists": [7],
        "gold_earned": [12000], "total_damage_dealt_to_champions": [20000],
        "vision_score": [30], "game_duration_sec": [1800], "total_minions_killed": [150],
    })


def test_kda_basic():
    df = add_metrics(_base())
    assert df["kda"].iloc[0] == (5 + 7) / 2  # 6.0


def test_kda_no_division_by_zero_when_no_deaths():
    b = _base()
    b["deaths"] = 0
    df = add_metrics(b)
    # deaths.clip(lower=1) -> делим на 1, а не на 0
    assert df["kda"].iloc[0] == (5 + 7) / 1
    assert pd.notna(df["kda"].iloc[0])


def test_per_minute_metrics():
    df = add_metrics(_base())
    assert df["game_duration_min"].iloc[0] == 30.0
    assert df["gold_per_min"].iloc[0] == 12000 / 30
    assert df["damage_per_min"].iloc[0] == 20000 / 30
    assert df["vision_per_min"].iloc[0] == 30 / 30
    assert df["cs_per_min"].iloc[0] == 150 / 30


def test_cs_skipped_when_column_absent():
    b = _base().drop(columns=["total_minions_killed"])
    df = add_metrics(b)
    assert "cs_per_min" not in df.columns


def test_does_not_mutate_input():
    b = _base()
    add_metrics(b)
    assert "kda" not in b.columns  # работает на копии
