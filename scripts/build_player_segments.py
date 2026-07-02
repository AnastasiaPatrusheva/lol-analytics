"""
Витрина сегментации игроков (KMeans) — build-шаг, не рантайм дашборда.

Кластеризует игроков по стилю игры (KDA, фарм/урон/золото/обзор в минуту) и
присваивает читаемый архетип. Считается ОДИН РАЗ при сборке (sklearn нужен только
здесь), результат — outputs/sql/star/player_segments.parquet + .csv, который дашборд
просто читает. Кластеризуем отдельно по каждому источнику (kaggle/riot_api/riot_full).

Запуск:  python scripts/build_player_segments.py   (или через main.py segments)
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg, save_parquet_if_available  # noqa: E402

# --- параметры кластеризации ---
FEATURES = ["kda", "cs_per_min", "damage_per_min", "vision_per_min", "gold_per_min"]
K = 4                 # число архетипов
MIN_GAMES = 20        # игроки с меньшим числом игр — шумные, не кластеризуем
RANDOM_STATE = 42     # фиксируем: сборка воспроизводима

# доминирующая (самая «выше среднего») метрика кластера -> описательный стиль игры.
# Это НЕ официальные классы Riot — просто читаемые ярлыки для найденных сегментов.
ARCHETYPE_BY_FEATURE = {
    "damage_per_min": "Агрессивный (урон)",
    "cs_per_min": "Кэрри (фарм)",
    "vision_per_min": "Саппорт (обзор)",
    "gold_per_min": "Скейлер (экономика)",
    "kda": "Командный игрок",
}
# короткие имена метрик — для уточнения имени при совпадении доминирующей метрики
FEATURE_SHORT = {
    "damage_per_min": "урон",
    "cs_per_min": "фарм",
    "vision_per_min": "обзор",
    "gold_per_min": "золото",
    "kda": "KDA",
}


def aggregate_players(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Средние метрики по каждому игроку из звёздной схемы (fact + dim_player)."""
    fact = (cfg.STAR_DIR / "fact_participant.parquet").as_posix()
    player = (cfg.STAR_DIR / "dim_player.parquet").as_posix()
    return con.execute(f"""
        SELECT f.data_source, f.puuid,
               ANY_VALUE(p.riot_id_game_name) AS name,
               ANY_VALUE(p.source_tier)       AS source_tier,
               COUNT(*)                       AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               AVG(f.kda)            AS kda,
               AVG(f.cs_per_min)     AS cs_per_min,
               AVG(f.damage_per_min) AS damage_per_min,
               AVG(f.vision_per_min) AS vision_per_min,
               AVG(f.gold_per_min)   AS gold_per_min
        FROM read_parquet('{fact}') f
        JOIN read_parquet('{player}') p
          ON f.data_source = p.data_source AND f.puuid = p.puuid
        WHERE f.puuid IS NOT NULL
        GROUP BY f.data_source, f.puuid
        HAVING COUNT(*) >= {MIN_GAMES}
    """).df()


def label_clusters(centers, features: list[str]) -> dict[int, str]:
    """Архетип кластера = метрика, по которой его центроид выше всего (в стандарт. шкале).

    centers — cluster_centers_ (в стандартизованном пространстве). При совпадении
    доминирующей метрики у двух кластеров имя уточняется второй по силе метрикой
    («… + урон»), а в крайнем случае — номером, чтобы ярлыки не дублировались.
    """
    labels: dict[int, str] = {}
    used: set[str] = set()
    for cid, center in enumerate(centers):
        order = list(center.argsort()[::-1])  # индексы метрик по убыванию центроида
        base = ARCHETYPE_BY_FEATURE.get(features[order[0]], features[order[0]])
        name = base
        if name in used and len(order) > 1:
            name = f"{base} + {FEATURE_SHORT.get(features[order[1]], features[order[1]])}"
        n = 2
        while name in used:
            name = f"{base} #{n}"
            n += 1
        used.add(name)
        labels[cid] = name
    return labels


def segment_source(df_src: pd.DataFrame) -> pd.DataFrame:
    """KMeans по одному источнику. Возвращает df с колонками cluster + archetype.

    Кластеризуем только по метрикам, реально заполненным у этого источника
    (напр. у kaggle нет cs_per_min), и по строкам без пропусков в них.
    """
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    df_src = df_src.copy()
    # только метрики с данными и ненулевым разбросом (иначе стандартизация даёт NaN/деление на 0)
    feats = [f for f in FEATURES if df_src[f].notna().any() and df_src[f].std(skipna=True) > 0]
    usable = df_src.dropna(subset=feats)

    if len(feats) < 2 or len(usable) < K * 2:
        df_src["cluster"] = -1
        df_src["archetype"] = "Мало данных"
        return df_src

    # Стандартизация обязательна: у метрик разный масштаб (gold ~400, vision ~1),
    # иначе KMeans будет мерить расстояние в основном по золоту.
    X = StandardScaler().fit_transform(usable[feats])
    km = KMeans(n_clusters=K, n_init=10, random_state=RANDOM_STATE).fit(X)
    usable = usable.copy()
    usable["cluster"] = km.labels_
    names = label_clusters(km.cluster_centers_, feats)
    usable["archetype"] = usable["cluster"].map(names)

    # игроков с пропусками в метриках (не попали в кластеризацию) помечаем отдельно
    df_src = df_src.merge(usable[["puuid", "cluster", "archetype"]], on="puuid", how="left")
    df_src["cluster"] = df_src["cluster"].fillna(-1).astype(int)
    df_src["archetype"] = df_src["archetype"].fillna("Не классифицирован")
    return df_src


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = duckdb.connect()
    players = aggregate_players(con)
    if players.empty:
        print("Нет игроков после фильтра по числу игр — витрина не построена.")
        return 1

    parts = []
    for source, grp in players.groupby("data_source"):
        seg = segment_source(grp)
        parts.append(seg)
        sizes = {k: int(v) for k, v in seg["archetype"].value_counts().items()}
        print(f"{source}: {len(seg)} игроков -> {sizes}")

    result = pd.concat(parts, ignore_index=True)

    cfg.STAR_DIR.mkdir(parents=True, exist_ok=True)
    out = cfg.STAR_DIR / "player_segments"
    result.to_csv(out.with_suffix(".csv"), index=False, encoding="utf-8")
    save_parquet_if_available(result, out.with_suffix(".parquet"))
    print(f"Готово: {result.shape} -> {out}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
