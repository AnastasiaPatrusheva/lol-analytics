"""Доступ к данным дашборда: подключение DuckDB к Parquet-витринам, кэш, помощники."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# Витрины звёздной схемы лежат в outputs/sql/star/*.parquet (в корне проекта).
STAR_DIR = Path(__file__).resolve().parent.parent / "outputs" / "sql" / "star"

TABLES = [
    "fact_participant", "dim_champion", "dim_match", "dim_player", "dim_role",
    "fact_participant_item", "dim_item", "item_stats",
    "champion_strength", "champion_by_duration", "player_segments",
]
SOURCES = ["riot_full", "kaggle", "riot_api"]
POSITIONS = ["Все", "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

SOURCE_DESC = {
    "riot_full": "Большой набор: ~26 000 матчей, 7 патчей (16.7–16.12), регион EUW.",
    "kaggle": "Исторический срез матчей с Kaggle.",
    "riot_api": "Собственная свежая выборка, собранная через Riot API.",
}


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    """Одно подключение DuckDB (in-memory) с view поверх каждого Parquet-файла."""
    con = duckdb.connect(database=":memory:")
    # Доверительный интервал Уилсона — макросами (та же формула, что в build_star_schema).
    con.execute("""CREATE OR REPLACE MACRO wilson_low(p, n) AS
        (p + 1.96*1.96/(2*n) - 1.96*sqrt((p*(1-p) + 1.96*1.96/(4*n))/n)) / (1 + 1.96*1.96/n)""")
    con.execute("""CREATE OR REPLACE MACRO wilson_high(p, n) AS
        (p + 1.96*1.96/(2*n) + 1.96*sqrt((p*(1-p) + 1.96*1.96/(4*n))/n)) / (1 + 1.96*1.96/n)""")
    for table in TABLES:
        parquet = STAR_DIR / f"{table}.parquet"
        # Витрина может отсутствовать (напр. player_segments до сборки) — пропускаем.
        if parquet.exists():
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{parquet.as_posix()}')")
    return con


def table_exists(name: str) -> bool:
    return (STAR_DIR / f"{name}.parquet").exists()


@st.cache_data
def run(sql: str) -> pd.DataFrame:
    """Выполнить SQL и вернуть DataFrame (результат кэшируется)."""
    return get_connection().execute(sql).df()


def check_source(source: str) -> str:
    """Валидация источника по белому списку.

    Значения приходят из фиксированного selectbox, поэтому SQL-инъекция через
    подстановку `source` невозможна; проверка — защита на всякий случай.
    """
    if source not in SOURCES:
        raise ValueError(f"Неизвестный источник данных: {source}")
    return source


def download_csv(df: pd.DataFrame, filename: str, *, key: str, label: str = "⬇️ Скачать CSV") -> None:
    """Кнопка скачивания таблицы в CSV."""
    st.download_button(
        label, df.to_csv(index=False).encode("utf-8"),
        file_name=filename, mime="text/csv", key=key,
    )
