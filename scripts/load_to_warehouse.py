"""
Слой базы данных: заливаем звёздную схему в реляционную БД.

Зачем это нужно (наставник называл это «следующим уровнем»):
DuckDB/Parquet — это файловый слой. Чтобы дашборд в DataLens (или PowerBI/Streamlit)
подключался к данным «вживую», их удобно положить в обычную БД и подключить BI к ней.

Один и тот же скрипт работает в двух режимах — выбор по переменной окружения DATABASE_URL:

1) Без DATABASE_URL  -> пишет в локальный SQLite (outputs/warehouse/lol.db).
   Работает сразу, без облака и регистрации — для демонстрации навыка работы с БД.

2) С DATABASE_URL от Supabase -> те же таблицы заливаются в облачный PostgreSQL,
   и DataLens подключается к нему по обычному коннекшену.

Пример (Supabase):
    setx DATABASE_URL "postgresql+psycopg2://postgres:ПАРОЛЬ@ХОСТ:5432/postgres"
    pip install psycopg2-binary
    python scripts/load_to_warehouse.py

Источник данных — готовые CSV звёздной схемы из outputs/sql/star/
(их собирает ноутбук LOL_sql_layer.ipynb).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg  # noqa: E402

STAR_DIR = cfg.STAR_DIR
LOCAL_DB_PATH = cfg.WAREHOUSE_DIR / "lol.db"
STAR_TABLES = cfg.STAR_TABLES

# match_id читаем строкой, чтобы длинные id не округлились (актуально для CSV).
STRING_COLUMNS = {"match_id": "string"}


def read_star_table(table: str) -> pd.DataFrame:
    # Parquet — основной формат хранения; CSV оставлен как запасной / для BI-выгрузки.
    parquet = STAR_DIR / f"{table}.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    return pd.read_csv(STAR_DIR / f"{table}.csv", dtype=STRING_COLUMNS, low_memory=False)


def resolve_database_url() -> tuple[str, str]:
    """Возвращает (url, человекочитаемое_описание_цели). Пароль в описании не светим."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Прячем пароль: postgresql+psycopg2://user:***@host:port/db
        safe = url
        if "@" in url and "//" in url:
            scheme, rest = url.split("//", 1)
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            safe = f"{scheme}//{user}:***@{host}"
        return url, f"внешняя БД ({safe})"

    LOCAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{LOCAL_DB_PATH.as_posix()}", f"локальный SQLite ({LOCAL_DB_PATH})"


def load() -> int:
    # SKIP_TABLES (через запятую) — не грузить тяжёлые таблицы в облако.
    # Пример: мост fact_participant_item (~1.8M строк) не нужен в Supabase —
    # для дашборда используется готовая витрина item_stats.
    skip = {t.strip() for t in os.environ.get("SKIP_TABLES", "").split(",") if t.strip()}
    tables = [t for t in STAR_TABLES if t not in skip]
    if skip:
        print(f"Пропускаем (не грузим): {sorted(skip)}")

    missing = [
        t for t in tables
        if not (STAR_DIR / f"{t}.parquet").exists() and not (STAR_DIR / f"{t}.csv").exists()
    ]
    if missing:
        print(f"Нет CSV звёздной схемы: {missing}")
        print("Сначала прогони ноутбук LOL_sql_layer.ipynb (секция 'Звёздная схема').")
        return 1

    url, target = resolve_database_url()
    print(f"Цель загрузки: {target}\n")

    engine = create_engine(url)
    loaded: dict[str, int] = {}

    with engine.begin() as conn:
        for table in tables:
            df = read_star_table(table)
            # if_exists='replace' делает загрузку идемпотентной:
            # повторный запуск перезаписывает таблицу, а не плодит дубли.
            # method='multi' + chunksize упаковывает много строк в один INSERT —
            # критично для скорости при заливке по сети в облачный Postgres.
            df.to_sql(
                table, conn, if_exists="replace", index=False,
                method="multi", chunksize=1000,
            )
            loaded[table] = len(df)
            print(f"  загружено {table}: {len(df)} строк")

    # Проверка: читаем обратно из БД, что факт реально записался.
    with engine.connect() as conn:
        fact_in_db = conn.execute(text("SELECT COUNT(*) FROM fact_participant")).scalar_one()

    print()
    if fact_in_db == loaded["fact_participant"]:
        print(f"OK: в БД {fact_in_db} строк fact_participant — совпадает с источником.")
    else:
        print(f"ВНИМАНИЕ: в БД {fact_in_db}, а грузили {loaded['fact_participant']} — расхождение.")
        return 1

    print("\nГотово. Таблицы в БД: " + ", ".join(tables))
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    return load()


if __name__ == "__main__":
    sys.exit(main())
