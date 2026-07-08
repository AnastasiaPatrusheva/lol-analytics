"""Снимок текущих витрин звёздной схемы в датированную папку (версионирование данных).

Копирует outputs/sql/star/*.parquet (+ _build_info.json) в outputs/snapshots/<дата>/,
чтобы можно было сравнить «было/стало» или откатиться к прошлой сборке.

Запуск:  python scripts/snapshot_data.py   (или через main.py snapshot)
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg  # noqa: E402

SNAPSHOTS_DIR = cfg.OUTPUTS_DIR / "snapshots"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    files = sorted(cfg.STAR_DIR.glob("*.parquet"))
    if not files:
        print("Нет витрин для снимка. Сначала собери звёздную схему: python main.py star")
        return 1

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    dest = SNAPSHOTS_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    build_info = cfg.STAR_DIR / "_build_info.json"
    if build_info.exists():
        shutil.copy2(build_info, dest / build_info.name)

    print(f"Снимок сохранён: {dest} ({len(files)} витрин)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
