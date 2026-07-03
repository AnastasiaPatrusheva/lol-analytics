from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Делаем общий пакет lol_utils импортируемым при прямом запуске и через runpy.
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import add_metrics, save_parquet_if_available, config as cfg  # noqa: E402

# Только ранкед-соло на Summoner's Rift, как в выборке через Riot API (queue=420).
# ARAM/флекс сделали бы сравнение чемпионов и ролей между источниками
# несопоставимым («яблоки с апельсинами»).
RANKED_SOLO_QUEUE_ID = cfg.RANKED_SOLO_QUEUE_ID

API_PATH = PROJECT_ROOT / "data" / "api" / "matches_api_enriched.csv"
KAGGLE_PATH = PROJECT_ROOT / "data" / "raw" / "league_data.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "normalized"

API_OUTPUT = OUTPUT_DIR / "api_matches_common.csv"
KAGGLE_OUTPUT = OUTPUT_DIR / "kaggle_matches_common.csv"
COMBINED_OUTPUT = OUTPUT_DIR / "all_matches_common.csv"
SCHEMA_OUTPUT = OUTPUT_DIR / "common_schema_columns.csv"


COMMON_COLUMNS = [
    "data_source",
    "match_id",
    "source_tier",
    "game_start_utc",
    "game_duration_sec",
    "game_duration_min",
    "game_mode",
    "game_type",
    "game_version",
    "map_id",
    "platform_id",
    "queue_id",
    "participant_id",
    "puuid",
    "summoner_id",
    "summoner_name",
    "summoner_level",
    "champion_id",
    "champion_name",
    "team_id",
    "win",
    "team_position",
    "individual_position",
    "lane",
    "role",
    "kills",
    "deaths",
    "assists",
    "kda",
    "gold_earned",
    "gold_spent",
    "gold_per_min",
    "total_damage_dealt_to_champions",
    "damage_per_min",
    "riot_id_game_name",
    "total_minions_killed",
    "cs_per_min",
    "total_damage_taken",
    "vision_score",
    "vision_per_min",
    "wards_placed",
    "wards_killed",
    "dragon_kills",
    "baron_kills",
    "item0",
    "item1",
    "item2",
    "item3",
    "item4",
    "item5",
    "item6",
]


KAGGLE_COLUMNS = [
    "game_id",
    "game_start_utc",
    "game_duration",
    "game_mode",
    "game_type",
    "game_version",
    "map_id",
    "platform_id",
    "queue_id",
    "participant_id",
    "puuid",
    "summoner_id",
    "summoner_name",
    "summoner_level",
    "champion_id",
    "champion_name",
    "team_id",
    "win",
    "team_position",
    "individual_position",
    "lane",
    "role",
    "kills",
    "deaths",
    "assists",
    "gold_earned",
    "gold_spent",
    "total_damage_dealt_to_champions",
    "total_damage_taken",
    "vision_score",
    "wards_placed",
    "wards_killed",
    "dragon_kills",
    "baron_kills",
    "item0",
    "item1",
    "item2",
    "item3",
    "item4",
    "item5",
    "item6",
]


def normalize_match_id(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalize_api() -> pd.DataFrame:
    api_df = pd.read_csv(API_PATH)
    api_df = api_df.copy()

    api_df["data_source"] = "riot_api"
    api_df["match_id"] = api_df["match_id"].map(normalize_match_id)
    if "game_start_utc" not in api_df.columns:
        api_df["game_start_utc"] = pd.to_datetime(
            api_df["game_start_timestamp"], unit="ms", errors="coerce", utc=True
        ).dt.strftime("%Y-%m-%d %H:%M:%S")

    return api_df.reindex(columns=COMMON_COLUMNS)


def normalize_kaggle() -> pd.DataFrame:
    kaggle_df = pd.read_excel(KAGGLE_PATH, usecols=KAGGLE_COLUMNS)
    kaggle_df = kaggle_df.rename(
        columns={
            "game_id": "match_id",
            "game_duration": "game_duration_sec",
        }
    )

    # Оставляем только ранкед-соло, чтобы Kaggle совпадал по рамке с API-выборкой.
    # Это заодно убирает ~9.7k строк ARAM, у которых team_position = "Invalid".
    kaggle_df = kaggle_df[kaggle_df["queue_id"] == RANKED_SOLO_QUEUE_ID].copy()

    kaggle_df["data_source"] = "kaggle"
    kaggle_df["source_tier"] = "kaggle"
    kaggle_df["match_id"] = kaggle_df["match_id"].map(normalize_match_id)

    # Роль может законно отсутствовать (ливеры, крайние случаи). Помечаем её
    # UNDEFINED, а не выкидываем — чтобы число игроков и полнота матчей
    # сохранялись для последующей фильтрации.
    kaggle_df["team_position"] = (
        kaggle_df["team_position"]
        .fillna(kaggle_df["individual_position"])
        .replace({"": "UNDEFINED", "Invalid": "UNDEFINED"})
        .fillna("UNDEFINED")
    )
    kaggle_df = add_metrics(kaggle_df)

    return kaggle_df.reindex(columns=COMMON_COLUMNS)


def finalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Приводим типы к единому виду, чтобы Parquet записался без ошибок:
    - game_start_utc -> единый datetime (источники дают то строку, то Timestamp);
    - текстовые колонки -> string (смесь str/int в object-колонке ломает запись Parquet)."""
    df = df.copy()
    if "game_start_utc" in df.columns:
        df["game_start_utc"] = pd.to_datetime(
            df["game_start_utc"], errors="coerce", utc=True
        ).dt.tz_localize(None)
    text_cols = [
        "data_source", "match_id", "source_tier", "game_mode", "game_type",
        "game_version", "platform_id", "puuid", "summoner_id", "summoner_name",
        "riot_id_game_name", "champion_name", "team_position", "individual_position",
        "lane", "role",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Нормализую данные Riot API...")
    api_common = finalize_dtypes(normalize_api())
    api_common.to_csv(API_OUTPUT, index=False)
    save_parquet_if_available(api_common, API_OUTPUT.with_suffix(".parquet"))

    print("Нормализую данные Kaggle (может занять минуту — источник xlsx)...")
    kaggle_common = finalize_dtypes(normalize_kaggle())
    kaggle_common.to_csv(KAGGLE_OUTPUT, index=False)
    save_parquet_if_available(kaggle_common, KAGGLE_OUTPUT.with_suffix(".parquet"))

    # Большой источник riot_full (из архива raw.zip) подключаем, если он уже
    # разобран ingest-скриптом. Это главный объёмный источник с несколькими патчами.
    parts = [api_common, kaggle_common]
    riot_full_path = OUTPUT_DIR / "riot_full_common.parquet"
    if riot_full_path.exists():
        riot_full = finalize_dtypes(pd.read_parquet(riot_full_path))
        parts.append(riot_full)
        print(f"Источник riot_full: {riot_full.shape} <- {riot_full_path.name}")

    combined = pd.concat(parts, ignore_index=True)
    combined.to_csv(COMBINED_OUTPUT, index=False)
    save_parquet_if_available(combined, COMBINED_OUTPUT.with_suffix(".parquet"))

    pd.DataFrame({"column": COMMON_COLUMNS}).to_csv(SCHEMA_OUTPUT, index=False)

    print("Готово.")
    print(f"API: {api_common.shape} -> {API_OUTPUT}")
    print(f"Kaggle: {kaggle_common.shape} -> {KAGGLE_OUTPUT}")
    print(f"Объединённая таблица: {combined.shape} -> {COMBINED_OUTPUT}")
    print("Строк по источникам:")
    print(combined["data_source"].value_counts().to_string())
    print("Уникальных матчей по источникам:")
    print(combined.groupby("data_source")["match_id"].nunique().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
