"""
ETL-оркестратор проекта LoL.

Один управляющий файл, который рулит всем пайплайном через argparse — стадию
выбираешь аргументом, внутри происходит ветвление. Весь прогон пишется в `etl.log`
(и в консоль), чтобы видеть, какая стадия когда шла, сколько и чем закончилась.

Слои:
  reference  — справочники Data Dragon (champions, items)
  ingest     — разбор большого датасета raw.zip → источник riot_full
  extract    — сбор из Riot API (нужен ключ; аргументы пробрасываются коллектору)
  transform  — нормализация источников в общую схему (Parquet + CSV)
  quality    — проверки Data Quality
  star       — сборка звёздной схемы (Parquet + CSV)
  load       — загрузка звезды в БД: --target local (SQLite) | supabase (Postgres)
  all        — ingest -> transform -> quality -> star -> load(local)

Примеры:
  python main.py transform
  python main.py extract --tier master --max-players 10 --matches-per-player 5
  python main.py load --target supabase
  python main.py all
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
LOG_FILE = ROOT / "etl.log"

sys.path.insert(0, str(ROOT / "src"))
from lol_utils.logging_setup import setup_logging  # noqa: E402


def run_script(name: str, *args: str, env: dict | None = None) -> None:
    """Запускает скрипт-стадию, стримит его вывод в лог (консоль + etl.log)."""
    log = logging.getLogger("etl")
    label = f"{name} {' '.join(args)}".strip()
    log.info("START  %s", label)
    started = time.time()

    proc = subprocess.Popen(
        [sys.executable, str(SCRIPTS / name), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log.info("   | %s", line)
    proc.wait()

    took = time.time() - started
    if proc.returncode != 0:
        log.error("FAILED %s (код %s, %.1fs)", label, proc.returncode, took)
        raise SystemExit(proc.returncode)
    log.info("DONE   %s (%.1fs)", label, took)


def env_without_database_url() -> dict:
    # Для локальной загрузки (SQLite) убираем DATABASE_URL, чтобы не утащить в Supabase.
    return {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}


def main() -> int:
    log = setup_logging(LOG_FILE)

    parser = argparse.ArgumentParser(description="LoL ETL orchestrator")
    sub = parser.add_subparsers(dest="stage", required=True)

    sub.add_parser("reference", help="справочники Data Dragon (champions, items)")
    sub.add_parser("ingest", help="разбор большого датасета raw.zip → источник riot_full")
    sub.add_parser("extract", add_help=False, help="сбор из Riot API (проброс аргументов коллектору)")
    sub.add_parser("transform", help="нормализация источников в общую схему")
    sub.add_parser("quality", help="проверки Data Quality")
    sub.add_parser("star", help="сборка звёздной схемы")
    p_load = sub.add_parser("load", help="загрузка звезды в БД")
    p_load.add_argument("--target", choices=["local", "supabase"], default="local")
    sub.add_parser("all", help="ingest -> transform -> quality -> star -> load(local)")

    args, extra = parser.parse_known_args()
    log.info("===== Стадия: %s =====", args.stage)
    started = time.time()

    if args.stage == "reference":
        run_script("fetch_reference.py")
    elif args.stage == "ingest":
        run_script("ingest_riot_full.py")
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
                log.error("Для --target supabase задай переменную окружения DATABASE_URL.")
                return 1
            run_script("load_to_warehouse.py")
        else:
            run_script("load_to_warehouse.py", env=env_without_database_url())
    elif args.stage == "all":
        if (ROOT / "data" / "riot_full" / "raw" / "matches").exists():
            run_script("ingest_riot_full.py")
        run_script("build_common_analytics_layer.py")
        run_script("run_data_quality.py")
        run_script("build_star_schema.py")
        run_script("load_to_warehouse.py", env=env_without_database_url())

    log.info("Готово за %.1fs. Полный лог: %s", time.time() - started, LOG_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
