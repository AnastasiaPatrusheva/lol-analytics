"""
ETL-оркестратор проекта.

Единая точка запуска пайплайна. Нужная стадия задаётся аргументом командной строки
(через модуль argparse); в зависимости от неё запускается соответствующий скрипт из
папки scripts/. Ход выполнения записывается в файл etl.log и одновременно в консоль.

Доступные стадии:
  reference  — загрузка справочников Data Dragon (чемпионы, предметы)
  ingest     — разбор большого датасета (raw.zip) в источник riot_full
  extract    — сбор данных через Riot API (доп. аргументы передаются коллектору)
  transform  — приведение источников к общей схеме (Parquet + CSV)
  quality    — проверки качества данных
  star       — построение звёздной схемы (Parquet + CSV)
  segments   — витрина сегментации игроков (KMeans; нужен scikit-learn)
  load       — загрузка звезды в БД: --target local (SQLite) или supabase (PostgreSQL)
  all        — последовательность: ingest -> transform -> quality -> star -> segments -> load(local)

Примеры запуска:
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

# Базовые пути проекта.
ROOT = Path(__file__).resolve().parent      # папка, где лежит main.py (корень проекта)
SCRIPTS = ROOT / "scripts"                  # папка со скриптами-стадиями
LOG_FILE = ROOT / "etl.log"                 # файл лога

# Делаем пакет src/lol_utils импортируемым и подключаем настройку логирования.
sys.path.insert(0, str(ROOT / "src"))
from lol_utils.logging_setup import setup_logging  # noqa: E402


def run_script(name: str, *args: str, env: dict | None = None) -> None:
    """Запускает скрипт-стадию из папки scripts/ и пишет его вывод в лог.

    name — имя файла скрипта; args — аргументы командной строки для него;
    env  — переменные окружения для дочернего процесса (по умолчанию текущие).
    Если скрипт завершается с ненулевым кодом, выполнение прерывается.
    """
    log = logging.getLogger("etl")
    label = f"{name} {' '.join(args)}".strip()
    log.info("START  %s", label)
    started = time.time()

    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS / name), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,         # ошибки скрипта направляем в тот же поток
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    # Вывод дочернего процесса читается построчно и сразу записывается в лог.
    for line in process.stdout:
        line = line.rstrip()
        if line:
            log.info("   | %s", line)
    process.wait()

    took = time.time() - started
    if process.returncode != 0:
        log.error("FAILED %s (код %s, %.1fs)", label, process.returncode, took)
        raise SystemExit(process.returncode)
    log.info("DONE   %s (%.1fs)", label, took)


def env_without_database_url() -> dict:
    """Копия текущего окружения без DATABASE_URL.

    Используется для локальной загрузки (SQLite): без этой переменной скрипт
    загрузки не попытается записать данные во внешнюю БД (Supabase).
    """
    return {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}


def main() -> int:
    log = setup_logging(LOG_FILE)

    # Описание аргументов командной строки. Каждая стадия — отдельная подкоманда.
    parser = argparse.ArgumentParser(description="LoL ETL orchestrator")
    sub = parser.add_subparsers(dest="stage", required=True)

    sub.add_parser("reference", help="справочники Data Dragon (champions, items)")
    sub.add_parser("ingest", help="разбор большого датасета raw.zip в источник riot_full")
    sub.add_parser("extract", add_help=False, help="сбор из Riot API (проброс аргументов коллектору)")
    sub.add_parser("transform", help="приведение источников к общей схеме")
    sub.add_parser("quality", help="проверки качества данных")
    sub.add_parser("star", help="построение звёздной схемы")
    sub.add_parser("segments", help="витрина сегментации игроков (KMeans)")
    sub.add_parser("snapshot", help="снимок витрин звёздной схемы в outputs/snapshots/<дата>/")
    p_load = sub.add_parser("load", help="загрузка звезды в БД")
    p_load.add_argument("--target", choices=["local", "supabase"], default="local")
    p_all = sub.add_parser("all", help="ingest -> transform -> quality -> star -> segments -> load(local)")
    p_all.add_argument("--skip-quality", action="store_true", help="пропустить проверки качества (для отладки)")

    # parse_known_args возвращает распознанные аргументы и остаток (extra)
    # — остаток пробрасывается стадии extract как параметры коллектора.
    args, extra = parser.parse_known_args()
    log.info("===== Стадия: %s =====", args.stage)
    started = time.time()

    # Ветвление: выбор скрипта по запрошенной стадии.
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
    elif args.stage == "segments":
        run_script("build_player_segments.py")
    elif args.stage == "snapshot":
        run_script("snapshot_data.py")
    elif args.stage == "load":
        if args.target == "supabase":
            if not os.environ.get("DATABASE_URL"):
                log.error("Для --target supabase требуется переменная окружения DATABASE_URL.")
                return 1
            run_script("load_to_warehouse.py")
        else:
            run_script("load_to_warehouse.py", env=env_without_database_url())
    elif args.stage == "all":
        # ingest запускается только при наличии распакованного большого датасета.
        if (ROOT / "data" / "riot_full" / "raw" / "matches").exists():
            run_script("ingest_riot_full.py")
        run_script("build_common_analytics_layer.py")
        if args.skip_quality:
            log.warning("quality пропущена (--skip-quality)")
        else:
            run_script("run_data_quality.py")
        run_script("build_star_schema.py")
        # segments — опциональная витрина: нужен scikit-learn; без него не рушим пайплайн
        try:
            run_script("build_player_segments.py")
        except SystemExit:
            log.warning("segments пропущен (нужен scikit-learn: pip install -r requirements-build.txt)")
        run_script("load_to_warehouse.py", env=env_without_database_url())

    log.info("Готово за %.1fs. Полный лог: %s", time.time() - started, LOG_FILE)
    return 0


# Стандартная точка входа: main() вызывается только при прямом запуске файла.
if __name__ == "__main__":
    sys.exit(main())
