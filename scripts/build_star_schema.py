"""
Сборка звёздной схемы (слой Transform → витрины).

Читает общую таблицу `all_matches_common` (Parquet — основной формат, CSV — запасной)
и строит факт + измерения через DuckDB, сохраняя их в outputs/sql/star/ как Parquet и CSV.

Раньше эта логика жила только в ноутбуке LOL_sql_layer.ipynb. Вынос в скрипт нужен,
чтобы звёздную схему можно было собирать из оркестратора main.py, а не только руками.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg, save_parquet_if_available  # noqa: E402


def source_relation(base: Path) -> str:
    """DuckDB-таблица-источник: предпочитаем Parquet, иначе CSV."""
    parquet = base.with_suffix(".parquet")
    csv = base.with_suffix(".csv")
    if parquet.exists():
        return f"read_parquet('{parquet.as_posix()}')"
    if csv.exists():
        return f"read_csv_auto('{csv.as_posix()}', header=true)"
    raise FileNotFoundError(
        f"Нет {parquet.name} или {csv.name}. Сначала запусти transform "
        f"(build_common_analytics_layer.py)."
    )


def build(con: duckdb.DuckDBPyConnection) -> None:
    common_rel = source_relation(cfg.COMMON_TABLE)
    con.execute(f"CREATE OR REPLACE VIEW matches_common AS SELECT * FROM {common_rel}")

    # только полные матчи (10 участников)
    con.execute("""
        CREATE OR REPLACE VIEW complete_matches AS
        WITH mc AS (
            SELECT data_source, match_id, COUNT(*) AS participants
            FROM matches_common GROUP BY data_source, match_id
        )
        SELECT m.* FROM matches_common m
        JOIN mc ON m.data_source = mc.data_source AND m.match_id = mc.match_id
        WHERE mc.participants = 10
    """)

    # справочник чемпионов + основной класс из tags
    con.execute(f"""
        CREATE OR REPLACE TABLE champions_ref AS
        SELECT CAST(champion_id AS BIGINT) AS champion_id, champion_name, title, tags,
               split_part(tags, ',', 1) AS primary_class
        FROM read_csv_auto('{cfg.CHAMPIONS_REF.as_posix()}', header=true)
    """)

    # измерения
    con.execute("""
        CREATE OR REPLACE TABLE dim_champion AS
        WITH ff AS (
            SELECT DISTINCT TRY_CAST(champion_id AS BIGINT) AS champion_id, champion_name
            FROM complete_matches WHERE champion_id IS NOT NULL
        )
        SELECT ff.champion_id, ff.champion_name, r.title,
               COALESCE(r.primary_class, 'Unknown') AS primary_class
        FROM ff LEFT JOIN champions_ref r ON ff.champion_id = r.champion_id
    """)
    con.execute("""
        CREATE OR REPLACE TABLE dim_match AS
        SELECT data_source, match_id,
               ANY_VALUE(game_start_utc) AS game_start_utc,
               ANY_VALUE(game_duration_min) AS game_duration_min,
               ANY_VALUE(game_version) AS game_version,
               ANY_VALUE(queue_id) AS queue_id,
               ANY_VALUE(source_tier) AS source_tier
        FROM complete_matches GROUP BY data_source, match_id
    """)
    con.execute("""
        CREATE OR REPLACE TABLE dim_player AS
        SELECT data_source, puuid,
               ANY_VALUE(source_tier) AS source_tier,
               ANY_VALUE(summoner_name) AS summoner_name,
               ANY_VALUE(riot_id_game_name) AS riot_id_game_name,
               COUNT(*) AS appearances
        FROM complete_matches WHERE puuid IS NOT NULL GROUP BY data_source, puuid
    """)
    con.execute("""
        CREATE OR REPLACE TABLE dim_role AS
        SELECT role_key, CASE role_key
            WHEN 'TOP' THEN 'Топ' WHEN 'JUNGLE' THEN 'Лес' WHEN 'MIDDLE' THEN 'Мид'
            WHEN 'BOTTOM' THEN 'Бот / керри' WHEN 'UTILITY' THEN 'Саппорт'
            ELSE 'Не определена' END AS role_name_ru
        FROM (SELECT DISTINCT team_position AS role_key FROM complete_matches)
    """)

    # факт: 1 строка = игрок в матче (ключи + меры)
    con.execute("""
        CREATE OR REPLACE TABLE fact_participant AS
        SELECT data_source, match_id, participant_id,
               TRY_CAST(champion_id AS BIGINT) AS champion_id,
               puuid, team_position AS role_key, team_id, win,
               kills, deaths, assists, kda, gold_earned, gold_per_min,
               total_damage_dealt_to_champions, damage_per_min, vision_score, vision_per_min,
               total_minions_killed, cs_per_min
        FROM complete_matches
    """)

    # --- ПРЕДМЕТЫ (связь многие-ко-многим через мост) ---
    # справочник предметов из Data Dragon
    items_csv = cfg.REFERENCE_DIR / "items.csv"
    con.execute(f"""
        CREATE OR REPLACE TABLE items_ref AS
        SELECT CAST(item_id AS BIGINT) AS item_id, item_name, gold_total, tags
        FROM read_csv_auto('{items_csv.as_posix()}', header=true)
    """)

    # мост: разворачиваем item0..item6 (широкий вид -> длинный),
    # пустые слоты (0 / NULL) выкидываем. 1 строка = 1 предмет у игрока в матче.
    con.execute("""
        CREATE OR REPLACE TABLE fact_participant_item AS
        SELECT data_source, match_id, participant_id, CAST(item_id AS BIGINT) AS item_id
        FROM (
            UNPIVOT (
                SELECT data_source, match_id, participant_id,
                       item0, item1, item2, item3, item4, item5, item6
                FROM complete_matches
            )
            ON item0, item1, item2, item3, item4, item5, item6
            INTO NAME slot VALUE item_id
        )
        WHERE item_id IS NOT NULL AND item_id <> 0
    """)

    # измерение предметов: только реально встречающиеся, обогащённые справочником
    con.execute("""
        CREATE OR REPLACE TABLE dim_item AS
        WITH used AS (SELECT DISTINCT item_id FROM fact_participant_item)
        SELECT u.item_id, r.item_name, r.gold_total, r.tags
        FROM used u LEFT JOIN items_ref r ON u.item_id = r.item_id
    """)

    # витрина "Покупки x Winrate" (как в эталоне наставника):
    # по каждому предмету — покупки, winrate и нижняя граница Уилсона
    # (консервативный winrate с поправкой на размер выборки).
    con.execute("""
        CREATE OR REPLACE TABLE item_stats AS
        WITH agg AS (
            SELECT b.data_source,
                   COALESCE(d.item_name, CAST(b.item_id AS VARCHAR)) AS item_name,
                   b.item_id,
                   d.gold_total,
                   COUNT(*) AS purchases,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
            FROM fact_participant_item b
            JOIN fact_participant f
              ON b.data_source = f.data_source
             AND b.match_id = f.match_id
             AND b.participant_id = f.participant_id
            LEFT JOIN dim_item d ON b.item_id = d.item_id
            GROUP BY b.data_source, d.item_name, b.item_id, d.gold_total
            HAVING COUNT(*) >= 10
        )
        SELECT *,
               (winrate + 1.96*1.96/(2*purchases)
                - 1.96*sqrt((winrate*(1-winrate) + 1.96*1.96/(4*purchases))/purchases))
               / (1 + 1.96*1.96/purchases) AS wilson_low
        FROM agg
        ORDER BY purchases DESC
    """)

    # витрина "Сила чемпиона" со статистической строгостью:
    # доверительный интервал Уилсона (95%) на winrate + вердикт по аномалии.
    # Идея: 60% при 5 играх — это шум (широкий интервал), а 53% при 500 играх —
    # надёжно. Поэтому tier-list честно строить по нижней границе wilson_low,
    # а "значимо сильный/слабый" = интервал НЕ накрывает 50%.
    con.execute("""
        CREATE OR REPLACE TABLE champion_strength AS
        WITH base AS (
            SELECT f.data_source, c.champion_name, c.primary_class,
                   COUNT(DISTINCT f.match_id) AS games,
                   SUM(CASE WHEN f.win THEN 1 ELSE 0 END) AS wins
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            GROUP BY f.data_source, c.champion_name, c.primary_class
        ),
        ci AS (
            SELECT data_source, champion_name, primary_class, games, wins,
                   wins * 1.0 / games AS winrate,
                   (wins*1.0/games + 1.96*1.96/(2*games)
                    - 1.96*sqrt((wins*1.0/games*(1-wins*1.0/games) + 1.96*1.96/(4*games))/games))
                   / (1 + 1.96*1.96/games) AS wilson_low,
                   (wins*1.0/games + 1.96*1.96/(2*games)
                    + 1.96*sqrt((wins*1.0/games*(1-wins*1.0/games) + 1.96*1.96/(4*games))/games))
                   / (1 + 1.96*1.96/games) AS wilson_high
            FROM base WHERE games >= 5
        )
        SELECT *,
               CASE WHEN wilson_low > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
        FROM ci
        ORDER BY data_source, wilson_low DESC
    """)

    # витрина "Чемпион × длительность матча": кто как играет в коротких/средних/длинных
    # играх. Разница winrate (длинные − короткие) показывает "скейлящихся" чемпионов
    # (поздняя игра) против "ранних". Длительность берём из dim_match.
    con.execute("""
        CREATE OR REPLACE TABLE champion_by_duration AS
        WITH j AS (
            SELECT f.data_source, c.champion_name, c.primary_class, f.win,
                   CASE WHEN m.game_duration_min < 25 THEN '1. Короткие (<25м)'
                        WHEN m.game_duration_min < 32 THEN '2. Средние (25-32м)'
                        ELSE '3. Длинные (>32м)' END AS duration_bucket
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
        )
        SELECT data_source, champion_name, primary_class, duration_bucket,
               COUNT(*) AS games,
               AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM j
        GROUP BY data_source, champion_name, primary_class, duration_bucket
        ORDER BY data_source, champion_name, duration_bucket
    """)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = duckdb.connect()
    build(con)

    cfg.STAR_DIR.mkdir(parents=True, exist_ok=True)
    for table in cfg.STAR_TABLES:
        df = con.execute(f"SELECT * FROM {table}").df()
        df.to_csv(cfg.STAR_DIR / f"{table}.csv", index=False, encoding="utf-8")
        save_parquet_if_available(df, cfg.STAR_DIR / f"{table}.parquet")
        print(f"  {table}: {len(df)} строк")

    # проверка целостности факта
    fact_rows = con.execute("SELECT COUNT(*) FROM fact_participant").fetchone()[0]
    dim_matches = con.execute("SELECT COUNT(*) FROM dim_match").fetchone()[0]
    ok = fact_rows // 10 == dim_matches
    print(f"Целостность: fact/10={fact_rows // 10}, dim_match={dim_matches} ->",
          "OK" if ok else "РАСХОЖДЕНИЕ")
    print(f"Звёздная схема сохранена в: {cfg.STAR_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
