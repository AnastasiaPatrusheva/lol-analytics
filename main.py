"""
ETL-оркестратор проекта LoL.

Один управляющий файл, который рулит всем пайплайном через argparse —
ровно та структура «junior+», которую рекомендовал наставник: стадию выбираешь
аргументом, внутри происходит ветвление, что запускать.

Слои:
  extract    — сбор данных из Riot API (нужен ключ; аргументы пробрасываются коллектору)
  transform  — нормализация источников в общую схему (Parquet + CSV)
  quality    — проверки Data Quality
  star       — сборка звёздной схемы (Parquet + CSV)
  load       — загрузка звезды в БД: --target local (SQLite) | supabase (Postgres)
  all        — transform -> quality -> star -> load(local), без extract

Примеры:
  python main.py transform
  python main.py extract --tier master --max-players 10 --matches-per-player 5
  python main.py load --target supabase
  python main.py all
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run_script(name: str, *args: str, env: dict | None = None) -> None:
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    print(f"\n=== {name} {' '.join(args)} ===", flush=True)
    subprocess.run(cmd, check=True, env=env)


def env_without_database_url() -> dict:
    # Для локальной загрузки (SQLite) гарантируем, что не утащит данные в Supabase,
    # даже если DATABASE_URL остался в окружении от прошлого запуска.
    return {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="LoL ETL orchestrator")
    sub = parser.add_subparsers(dest="stage", required=True)

    sub.add_parser("reference", help="справочники Data Dragon (champions, items)")
    sub.add_parser("extract", add_help=False, help="сбор из Riot API (проброс аргументов коллектору)")
    sub.add_parser("transform", help="нормализация источников в общую схему")
    sub.add_parser("quality", help="проверки Data Quality")
    sub.add_parser("star", help="сборка звёздной схемы")
    p_load = sub.add_parser("load", help="загрузка звезды в БД")
    p_load.add_argument("--target", choices=["local", "supabase"], default="local")
    sub.add_parser("all", help="transform -> quality -> star -> load(local)")

    args, extra = parser.parse_known_args()

    if args.stage == "reference":
        run_script("fetch_reference.py")
    elif args.stage == "extract":
        run_script("riot_data_collector.py", *extra)
    elif args.stage == "transform":
        run_script("build_common_analytics_layer.py")
    elif args.stage == "quality":
        run_script("run_data_quality.py")
    elif args.stage == "star":
        run_script("build_star_schema.py")
    elif args.stage == "load":
        if args.target == "supabase":
            if not os.environ.get("DATABASE_URL"):
                print("Для --target supabase задай переменную окружения DATABASE_URL.")
                return 1
            run_script("load_to_warehouse.py")
        else:
            run_script("load_to_warehouse.py", env=env_without_database_url())
    elif args.stage == "all":
        run_script("build_common_analytics_layer.py")
        run_script("run_data_quality.py")
        run_script("build_star_schema.py")
        run_script("load_to_warehouse.py", env=env_without_database_url())

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
