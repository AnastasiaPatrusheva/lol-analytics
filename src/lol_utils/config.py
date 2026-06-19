"""
Единый конфиг проекта.

Наставник рекомендовал выносить настройки в отдельный файл: пути к данным,
параметры API, пороги анализа. Так все «ручки» проекта лежат в одном месте,
а скрипты их импортируют, а не хранят у себя копии констант.
"""

from __future__ import annotations

from pathlib import Path

# src/lol_utils/config.py -> родитель[2] = корень проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# --- Riot API / сбор данных ---
REGION = "euw1"
MATCH_REGION = "europe"
RANKED_SOLO_QUEUE = "RANKED_SOLO_5x5"
RANKED_SOLO_QUEUE_ID = 420  # только ранкед-соло на Summoner's Rift

# --- директории данных ---
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
API_DIR = DATA_DIR / "api"
NORMALIZED_DIR = DATA_DIR / "normalized"
REFERENCE_DIR = DATA_DIR / "reference"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
SQL_DIR = OUTPUTS_DIR / "sql"
STAR_DIR = SQL_DIR / "star"
DQ_DIR = OUTPUTS_DIR / "data_quality"
WAREHOUSE_DIR = OUTPUTS_DIR / "warehouse"

# --- ключевые файлы ---
KAGGLE_XLSX = RAW_DIR / "league_data.xlsx"
CHAMPIONS_REF = REFERENCE_DIR / "champions.csv"
# базовое имя общей таблицы без расширения: рядом лежат .parquet (основной) и .csv (для BI-выгрузки)
COMMON_TABLE = NORMALIZED_DIR / "all_matches_common"

# --- пороги анализа ---
MIN_GAMES_BY_SOURCE = {"kaggle": 30, "riot_api": 10}
UNDEFINED_SHARE_WARN = 0.05

# --- таблицы звёздной схемы ---
# факт + измерения + мост предметов + витрина по предметам
STAR_TABLES = [
    "fact_participant", "dim_champion", "dim_match", "dim_player", "dim_role",
    "fact_participant_item", "dim_item", "item_stats", "champion_strength",
    "champion_by_duration",
]

# --- роли ---
STANDARD_POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
