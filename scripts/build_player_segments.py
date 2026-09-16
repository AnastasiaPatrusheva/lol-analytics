"""
Витрина сегментации игроков (KMeans) — build-шаг, не рантайм дашборда.

Кластеризует игроков по стилю игры и присваивает читаемый архетип. Считается
ОДИН РАЗ при сборке (sklearn нужен только здесь), результат —
outputs/sql/star/player_segments.parquet + .csv, который дашборд просто читает.
Кластеризуем отдельно по каждому источнику (kaggle/riot_api/riot_full).

ВАЖНО про метрики. Сырые «золото/фарм/урон/обзор в минуту» механически задаются
ролью: у бота ~490 золота в минуту против ~315 у саппорта, у саппорта обзор в
разы выше. Кластеризация по сырым значениям неизбежно находит РОЛИ, а не стили —
и выдаёт их за открытие. Поэтому каждая метрика берётся относительно среднего по
основной роли игрока: 1.0 = «как типичный игрок моей роли», 1.3 = «на 30% выше».
После этого кластер означает именно манеру игры внутри роли.

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
from lol_utils.sql import install_macros  # noqa: E402

# --- параметры кластеризации ---
# KDA разложен на две части: убийства на смерть и помощь на смерть. После нормировки
# к роли они почти не связаны (корреляция 0.13), а сам KDA — это в основном «помощь
# на смерть» (0.86 против 0.54 у убийств). Одним числом два разных стиля сливались.
FEATURES = ["kd", "ad", "cs_per_min", "damage_per_min", "vision_per_min", "gold_per_min"]
# K=4: силуэт по riot_full почти не меняется на 2..6 (0.19–0.25), то есть чёткого
# «локтя» в данных нет. Из этого диапазона 4 даёт интерпретируемые и достаточно
# крупные сегменты; силуэт печатается при сборке, чтобы выбор можно было проверить.
K = 4                 # число архетипов
MIN_GAMES = 20        # игроки с меньшим числом игр — шумные, не кластеризуем
RANDOM_STATE = 42     # фиксируем: сборка воспроизводима

# Ярлык кластера = метрика, по которой он сильнее всего отличается от нормы своей
# роли, С УЧЁТОМ ЗНАКА. Отличие «вниз» такой же стиль, как отличие «вверх»: самый
# крупный сегмент отличается именно тем, что все метрики ниже нормы, и назвать его
# по слабо-положительной метрике значило бы соврать. Это НЕ официальные классы Riot.
ARCHETYPE_BY_FEATURE = {
    ("damage_per_min", +1): "Агрессивный",
    ("damage_per_min", -1): "Мало урона",
    ("cs_per_min", +1): "Фармящий",
    ("cs_per_min", -1): "Мало фарма",
    ("vision_per_min", +1): "Играет на обзор",
    ("vision_per_min", -1): "Не ставит варды",
    ("gold_per_min", +1): "Сильная экономика",
    ("gold_per_min", -1): "Слабая экономика",
    ("kd", +1): "Керри",
    ("kd", -1): "Часто умирает",
    ("ad", +1): "Командный игрок",
    ("ad", -1): "Играет сам по себе",
    ("kda", +1): "Осторожный",
    ("kda", -1): "Часто умирает",
}
# короткие имена метрик — для уточнения имени при совпадении доминирующей метрики
FEATURE_SHORT = {
    "damage_per_min": "урон",
    "cs_per_min": "фарм",
    "vision_per_min": "обзор",
    "gold_per_min": "золото",
    "kd": "убийства",
    "ad": "помощь",
    "kda": "KDA",
}


def aggregate_players(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Метрики игрока относительно средних по его основной роли.

    Три шага: (1) метрики каждого игрока и его основная роль — та, где он сыграл
    больше всего; (2) средние по роли внутри источника; (3) деление одного на
    другое. KDA считается пулированно ((убийства+помощи)/смерти по всем матчам),
    а не средним от KDA матчей: среднее отношений завышает игроков с редкими
    матчами без смертей.
    """
    fact = (cfg.STAR_DIR / "fact_participant.parquet").as_posix()
    player = (cfg.STAR_DIR / "dim_player.parquet").as_posix()
    roles = ", ".join(f"'{r}'" for r in cfg.STANDARD_POSITIONS)
    return con.execute(f"""
        WITH f AS (SELECT * FROM read_parquet('{fact}') WHERE puuid IS NOT NULL),
        -- основная роль игрока: где сыграно больше всего матчей
        main_role AS (
            SELECT data_source, puuid, role_key FROM (
                SELECT data_source, puuid, role_key,
                       ROW_NUMBER() OVER (PARTITION BY data_source, puuid
                                          ORDER BY COUNT(*) DESC, role_key) AS rn
                FROM f WHERE role_key IN ({roles})
                GROUP BY data_source, puuid, role_key
            ) WHERE rn = 1
        ),
        -- средние по роли внутри источника: это и есть «норма роли»
        role_avg AS (
            SELECT data_source, role_key,
                   kda_pooled(kills, deaths, assists) AS kda,
                   SUM(kills) * 1.0 / GREATEST(SUM(deaths), 1)   AS kd,
                   SUM(assists) * 1.0 / GREATEST(SUM(deaths), 1) AS ad,
                   AVG(cs_per_min) AS cs_per_min, AVG(damage_per_min) AS damage_per_min,
                   AVG(vision_per_min) AS vision_per_min, AVG(gold_per_min) AS gold_per_min
            FROM f WHERE role_key IN ({roles})
            GROUP BY data_source, role_key
        ),
        per_player AS (
            SELECT f.data_source, f.puuid,
                   ANY_VALUE(p.riot_id_game_name) AS name,
                   ANY_VALUE(p.source_tier)       AS source_tier,
                   COUNT(*)                       AS games,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
                   kda_pooled(f.kills, f.deaths, f.assists) AS kda,
                   SUM(f.kills) * 1.0 / GREATEST(SUM(f.deaths), 1)   AS kd,
                   SUM(f.assists) * 1.0 / GREATEST(SUM(f.deaths), 1) AS ad,
                   AVG(f.cs_per_min) AS cs_per_min, AVG(f.damage_per_min) AS damage_per_min,
                   AVG(f.vision_per_min) AS vision_per_min, AVG(f.gold_per_min) AS gold_per_min
            FROM f JOIN read_parquet('{player}') p
              ON f.data_source = p.data_source AND f.puuid = p.puuid
            GROUP BY f.data_source, f.puuid
            HAVING COUNT(*) >= {MIN_GAMES}
        )
        SELECT pp.data_source, pp.puuid, pp.name, pp.source_tier, pp.games, pp.winrate,
               mr.role_key AS main_role,
               pp.kda            / NULLIF(ra.kda, 0)            AS kda,
               pp.kd             / NULLIF(ra.kd, 0)             AS kd,
               pp.ad             / NULLIF(ra.ad, 0)             AS ad,
               pp.cs_per_min     / NULLIF(ra.cs_per_min, 0)     AS cs_per_min,
               pp.damage_per_min / NULLIF(ra.damage_per_min, 0) AS damage_per_min,
               pp.vision_per_min / NULLIF(ra.vision_per_min, 0) AS vision_per_min,
               pp.gold_per_min   / NULLIF(ra.gold_per_min, 0)   AS gold_per_min
        FROM per_player pp
        JOIN main_role mr ON pp.data_source = mr.data_source AND pp.puuid = mr.puuid
        JOIN role_avg  ra ON pp.data_source = ra.data_source AND ra.role_key = mr.role_key
    """).df()


def label_clusters(centers, features: list[str]) -> dict[int, str]:
    """Архетип кластера = метрика с наибольшим отклонением центроида от нормы роли.

    centers — cluster_centers_ (в стандартизованном пространстве, 0 = норма роли).
    Берём метрику по максимуму МОДУЛЯ отклонения и учитываем знак: «часто умирает»
    такой же стиль, как «осторожный». При совпадении доминирующей метрики у двух
    кластеров имя уточняется второй по силе метрикой, в крайнем случае номером.
    """
    labels: dict[int, str] = {}
    used: set[str] = set()
    for cid, center in enumerate(centers):
        order = list(abs(center).argsort()[::-1])  # метрики по убыванию |отклонения|

        def named(i: int) -> str:
            feat = features[i]
            sign = 1 if center[i] >= 0 else -1
            return ARCHETYPE_BY_FEATURE.get((feat, sign), feat)

        base = named(order[0])
        name = base
        if name in used and len(order) > 1:
            second = features[order[1]]
            name = f"{base} + {FEATURE_SHORT.get(second, second)}"
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
    from sklearn.metrics import silhouette_score
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
    # Силуэт печатаем, чтобы выбор K был проверяемым, а не «просто 4».
    # Значения около 0.2 означают слабую структуру: это разведочная сегментация,
    # а не жёсткая типология, и так она и подписана в дашборде.
    if len(usable) > K:
        sil = silhouette_score(X, km.labels_, sample_size=min(3000, len(X)),
                               random_state=RANDOM_STATE)
        print(f"  силуэт при K={K}: {sil:.3f}")
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
    install_macros(con)
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
