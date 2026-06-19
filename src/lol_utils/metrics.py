"""Derived game metrics.

These formulas used to be duplicated in four places (pipeline notebook,
kaggle analysis notebook, and the normalization script). Keeping them here
means every layer computes kda / per-minute stats the exact same way.
"""

from __future__ import annotations

import pandas as pd


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with standard derived columns added.

    Expected input columns: kills, deaths, assists, gold_earned,
    total_damage_dealt_to_champions, vision_score, game_duration_sec.

    deaths.clip(lower=1) guards against division by zero when a player
    never died (a perfect KDA still gets a finite, comparable number).
    """
    df = df.copy()
    df["kda"] = (df["kills"] + df["assists"]) / df["deaths"].clip(lower=1)
    df["game_duration_min"] = df["game_duration_sec"] / 60
    df["damage_per_min"] = (
        df["total_damage_dealt_to_champions"] / df["game_duration_min"]
    )
    df["gold_per_min"] = df["gold_earned"] / df["game_duration_min"]
    df["vision_per_min"] = df["vision_score"] / df["game_duration_min"]
    return df
