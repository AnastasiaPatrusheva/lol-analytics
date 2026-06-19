"""
Справочники из Data Dragon (статический источник Riot, без API-ключа).

Делает воспроизводимыми измерения звёздной схемы:
- champions.csv — id, имя, титул, классы (tags);
- items.csv     — id, имя, цена, классы (tags).

Раньше champions.csv был просто скопирован из старого сэмпла. Теперь оба
справочника тянутся свежими, как и рекомендует стек наставника (Data Dragon).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg  # noqa: E402

DDRAGON = "https://ddragon.leagueoflegends.com"


def latest_version() -> str:
    return requests.get(f"{DDRAGON}/api/versions.json", timeout=30).json()[0]


def fetch_champions(version: str) -> pd.DataFrame:
    data = requests.get(
        f"{DDRAGON}/cdn/{version}/data/en_US/champion.json", timeout=30
    ).json()["data"]
    rows = [
        {
            "champion_id": int(info["key"]),
            "champion_name": info["name"],
            "title": info["title"],
            "tags": ",".join(info.get("tags", [])),
        }
        for info in data.values()
    ]
    return pd.DataFrame(rows).sort_values("champion_name").reset_index(drop=True)


def fetch_items(version: str) -> pd.DataFrame:
    data = requests.get(
        f"{DDRAGON}/cdn/{version}/data/en_US/item.json", timeout=30
    ).json()["data"]
    rows = [
        {
            "item_id": int(item_id),
            "item_name": info.get("name"),
            "gold_total": info.get("gold", {}).get("total"),
            "purchasable": info.get("gold", {}).get("purchasable"),
            "tags": ",".join(info.get("tags", [])),
        }
        for item_id, info in data.items()
    ]
    return pd.DataFrame(rows).sort_values("item_id").reset_index(drop=True)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cfg.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    version = latest_version()
    print(f"Версия Data Dragon: {version}")

    champions = fetch_champions(version)
    champions.to_csv(cfg.CHAMPIONS_REF, index=False, encoding="utf-8")
    print(f"  champions.csv: {len(champions)} чемпионов")

    items = fetch_items(version)
    items_path = cfg.REFERENCE_DIR / "items.csv"
    items.to_csv(items_path, index=False, encoding="utf-8")
    print(f"  items.csv: {len(items)} предметов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
