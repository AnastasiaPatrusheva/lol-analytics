"""
Ingest большого сырого датасета матчей (raw.zip от наставника).

Каждый матч хранится как сырой JSON Match-V5 (`_raw_json`). Скрипт разбирает их
в строки участников (переиспользуя `flatten_match` из коллектора — та же логика,
что и при сборе через API), приводит к общей схеме и сохраняет как новый источник
`data_source = 'riot_full'`.

Это главный объёмный источник: ~26k матчей по нескольким патчам (16.7–16.12),
что открывает анализ меты по патчам.

Запуск:  python scripts/ingest_riot_full.py   (или через main.py ingest)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from lol_utils import config as cfg, add_metrics, save_parquet_if_available  # noqa: E402
from riot_data_collector import flatten_match  # noqa: E402  (переиспользуем разбор JSON)
from build_common_analytics_layer import COMMON_COLUMNS, finalize_dtypes  # noqa: E402

MATCHES_GLOB = (cfg.DATA_DIR / "riot_full" / "raw" / "matches" / "*.parquet").as_posix()
OUT = cfg.NORMALIZED_DIR / "riot_full_common"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = duckdb.connect()
    raw = con.execute(
        f"SELECT match_id, _raw_json FROM read_parquet('{MATCHES_GLOB}')"
    ).df()
    print(f"Матчей в датасете: {len(raw)}")

    rows: list[dict] = []
    bad = 0
    for raw_json in raw["_raw_json"]:
        try:
            match = json.loads(raw_json)
        except Exception:
            bad += 1
            continue
        rows.extend(flatten_match(match, source_puuid=None, source_tier="riot_full"))

    flat = pd.DataFrame(rows)
    print(f"Строк участников: {len(flat)} (не разобрано матчей: {bad})")

    # только ранкед-соло, как и остальные источники
    flat = flat[flat["queue_id"] == cfg.RANKED_SOLO_QUEUE_ID].copy()

    flat["data_source"] = "riot_full"
    # пустые/Invalid роли помечаем UNDEFINED (как в Kaggle), не выкидываем
    flat["team_position"] = (
        flat["team_position"]
        .replace({"": "UNDEFINED", "Invalid": "UNDEFINED"})
        .fillna("UNDEFINED")
    )
    flat["game_start_utc"] = pd.to_datetime(
        flat["game_start_timestamp"], unit="ms", errors="coerce", utc=True
    ).dt.tz_localize(None)
    flat = add_metrics(flat)

    common = finalize_dtypes(flat.reindex(columns=COMMON_COLUMNS))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    common.to_csv(OUT.with_suffix(".csv"), index=False)
    save_parquet_if_available(common, OUT.with_suffix(".parquet"))

    print(f"Сохранено: {common.shape} -> {OUT}.parquet")
    print("Матчей после фильтра queue=420:", common["match_id"].nunique())
    print("Патчи:")
    patches = (
        common.assign(patch=common["game_version"].str.extract(r"^(\d+\.\d+)")[0])
        .groupby("patch")["match_id"].nunique().sort_values(ascending=False)
    )
    print(patches.head(10).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
