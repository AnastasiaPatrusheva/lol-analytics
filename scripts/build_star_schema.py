"""
Сборка звёздной схемы (слой Transform → витрины).

Читает общую таблицу `all_matches_common` (Parquet — основной формат, CSV — запасной)
и строит факт + измерения через DuckDB, сохраняя их в outputs/sql/star/ как Parquet и CSV.

Та же логика присутствует в ноутбуке LOL_sql_layer.ipynb; здесь она оформлена
отдельным скриптом, чтобы звёздную схему можно было собирать из оркестратора main.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg, save_parquet_if_available  # noqa: E402
from lol_utils.sql import install_macros, z_for_multiple_tests  # noqa: E402


def source_relation(base: Path) -> str:
    """DuckDB-таблица-источник: предпочитаем Parquet, иначе CSV."""
    parquet = base.with_suffix(".parquet")
    csv = base.with_suffix(".csv")
    if parquet.exists():
        return f"read_parquet('{parquet.as_posix()}')"
    if csv.exists():
        return f"read_csv_auto('{csv.as_posix()}', header=true)"
    raise FileNotFoundError(
        f"Нет {parquet.name} или {csv.name}. Сначала запустите transform "
        f"(build_common_analytics_layer.py)."
    )


def build(con: duckdb.DuckDBPyConnection) -> None:
    common_rel = source_relation(cfg.COMMON_TABLE)
    con.execute(f"CREATE OR REPLACE VIEW matches_common AS SELECT * FROM {common_rel}")

    # Доверительный интервал Уилсона — общие макросы из lol_utils.sql
    # (одна формула на витрины, дашборд и тесты).
    install_macros(con)

    # Матчи, пригодные для анализа: полные (10 участников) и не ремейки.
    # PUUID заменяем на устойчивый хеш: витрины лежат в публичном репозитории,
    # а PUUID — постоянный идентификатор аккаунта Riot. Для джойнов хеша хватает.
    con.execute(f"""
        CREATE OR REPLACE VIEW complete_matches AS
        WITH mc AS (
            SELECT data_source, match_id, COUNT(*) AS participants
            FROM matches_common GROUP BY data_source, match_id
        )
        SELECT m.* REPLACE (substr(md5(m.puuid), 1, {cfg.PLAYER_KEY_LEN}) AS puuid)
        FROM matches_common m
        JOIN mc ON m.data_source = mc.data_source AND m.match_id = mc.match_id
        WHERE mc.participants = 10
          AND m.game_duration_min >= {cfg.MIN_MATCH_MINUTES}
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
    # dim_player + очки лиги (LP) из players_api.csv (LP есть только у собранных через API; иначе NULL)
    players_api_path = cfg.API_DIR / "players_api.csv"
    if players_api_path.exists():
        # puuid хешируем так же, как в complete_matches, иначе джойн не сойдётся.
        lp_cte = f""",
        lp AS (
            SELECT substr(md5(puuid), 1, {cfg.PLAYER_KEY_LEN}) AS puuid,
                   MAX(league_points) AS league_points
            FROM read_csv_auto('{players_api_path.as_posix()}', header=true)
            GROUP BY 1
        )"""
        # LP собраны только через API: ограничиваем джойн источником riot_api,
        # иначе очки того же игрока протекают на строки kaggle/riot_full.
        lp_select = "l.league_points"
        lp_join = "LEFT JOIN lp l ON b.puuid = l.puuid AND b.data_source = 'riot_api'"
    else:
        lp_cte, lp_select, lp_join = "", "CAST(NULL AS BIGINT) AS league_points", ""
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_player AS
        WITH base AS (
            SELECT data_source, puuid,
                   ANY_VALUE(source_tier) AS source_tier,
                   ANY_VALUE(summoner_name) AS summoner_name,
                   ANY_VALUE(riot_id_game_name) AS riot_id_game_name,
                   COUNT(*) AS appearances
            FROM complete_matches WHERE puuid IS NOT NULL GROUP BY data_source, puuid
        ){lp_cte}
        SELECT b.*, {lp_select}
        FROM base b {lp_join}
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
    items_csv = cfg.ITEMS_REF
    con.execute(f"""
        CREATE OR REPLACE TABLE items_ref AS
        SELECT CAST(item_id AS BIGINT) AS item_id, item_name, gold_total, tags
        FROM read_csv_auto('{items_csv.as_posix()}', header=true)
    """)

    # мост: разворачиваем item0..item6 (широкий вид -> длинный),
    # пустые слоты (0 / NULL) исключаем. 1 строка = 1 предмет у игрока в матче.
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

    # витрина "Предмет в финальной сборке x Winrate".
    #
    # ВАЖНО про интерпретацию: item0..item6 — это инвентарь НА КОНЕЦ матча, а не
    # покупки по ходу игры. Победители дольше живут и успевают достроить дорогие
    # предметы, поэтому высокий winrate дорогого предмета — в значительной мере
    # следствие победы, а не её причина. Витрина отвечает на вопрос «что обычно
    # стоит в финальной сборке у победителей», а не «что покупать, чтобы выиграть».
    # Поэтому колонка называется appearances (появления), а не purchases.
    con.execute("""
        CREATE OR REPLACE TABLE item_stats AS
        WITH agg AS (
            SELECT b.data_source,
                   COALESCE(d.item_name, CAST(b.item_id AS VARCHAR)) AS item_name,
                   b.item_id,
                   d.gold_total,
                   COUNT(*) AS appearances,
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
        SELECT *, wilson_low(winrate, appearances) AS wilson_low
        FROM agg
        ORDER BY appearances DESC
    """)

    # витрина "Сила чемпиона" со статистической строгостью:
    # доверительный интервал Уилсона (95%) на winrate + вердикт по аномалии.
    # 60% при 5 играх даёт широкий интервал (ненадёжно), 53% при 500 играх — узкий.
    # Поэтому tier-list строится по нижней границе wilson_low.
    #
    # Вердикт «значимо сильный/слабый» считается по ОТДЕЛЬНОМУ, более широкому
    # интервалу: проверка идёт сразу по всем чемпионам источника, и без поправки
    # на множественные сравнения около 9 из ~170 получили бы ярлык случайно.
    # Поэтому для вердикта берём z с поправкой Бонферрони, а для рейтинга — 1.96.
    n_tests = con.execute("""
        SELECT MAX(cnt) FROM (
            SELECT COUNT(*) AS cnt FROM (
                SELECT f.data_source, f.champion_id, COUNT(DISTINCT f.match_id) AS games
                FROM fact_participant f GROUP BY 1, 2 HAVING COUNT(DISTINCT f.match_id) >= 5
            ) GROUP BY data_source
        )
    """).fetchone()[0] or 1
    z_adj = z_for_multiple_tests(n_tests)
    con.execute(f"""
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
                   wilson_low(wins * 1.0 / games, games) AS wilson_low,
                   wilson_high(wins * 1.0 / games, games) AS wilson_high,
                   wilson_low_z(wins * 1.0 / games, games, {z_adj}) AS wilson_low_adj,
                   wilson_high_z(wins * 1.0 / games, games, {z_adj}) AS wilson_high_adj
            FROM base WHERE games >= 5
        )
        SELECT *,
               CASE WHEN wilson_low_adj > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high_adj < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
        FROM ci
        ORDER BY data_source, wilson_low DESC
    """)
    print(f"  champion_strength: вердикт с поправкой Бонферрони на {n_tests} чемпионов "
          f"(z={z_adj:.2f} вместо 1.96)")

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

    # Метаданные сборки — когда собрано и сколько строк в каждой витрине.
    build_info = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "tables": {t: int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                   for t in cfg.STAR_TABLES},
    }
    (cfg.STAR_DIR / "_build_info.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"_build_info.json: собрано {build_info['built_at']}")

    # Проверки целостности звезды. Прежняя проверка (fact/10 == dim_match) не могла
    # упасть: complete_matches по построению оставляет ровно 10 участников. Здесь —
    # то, что действительно может сломаться: уникальность зерна факта, дубли в
    # измерениях (из-за них факт размножится при джойне) и сироты.
    checks = {
        "зерно факта уникально": """
            SELECT COUNT(*) FROM (
                SELECT data_source, match_id, participant_id FROM fact_participant
                GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)""",
        "dim_champion без дублей id": """
            SELECT COUNT(*) FROM (
                SELECT champion_id FROM dim_champion GROUP BY 1 HAVING COUNT(*) > 1)""",
        "dim_player без дублей ключа": """
            SELECT COUNT(*) FROM (
                SELECT data_source, puuid FROM dim_player GROUP BY 1, 2 HAVING COUNT(*) > 1)""",
        "нет сирот факт -> dim_champion": """
            SELECT COUNT(*) FROM fact_participant f
            LEFT JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.champion_id IS NOT NULL AND c.champion_id IS NULL""",
        "нет сирот факт -> dim_match": """
            SELECT COUNT(*) FROM fact_participant f
            LEFT JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE m.match_id IS NULL""",
        "PUUID заменён хешем": f"""
            SELECT COUNT(*) FROM dim_player
            WHERE puuid IS NOT NULL AND length(puuid) <> {cfg.PLAYER_KEY_LEN}""",
    }
    ok = True
    for name, sql in checks.items():
        bad = con.execute(sql).fetchone()[0]
        ok &= bad == 0
        print(f"Целостность: {name} -> {'OK' if bad == 0 else f'НАРУШЕНО ({bad})'}")
    print(f"Звёздная схема сохранена в: {cfg.STAR_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
