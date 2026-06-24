"""
Единая настройка логирования пайплайна.

Пишем одновременно в консоль и в файл `etl.log` с таймстампами — так в логе
остаётся полная история прогона ETL (какая стадия, когда, сколько шла, успех/ошибка).
Это то «логирование», которое наставник показывал как признак прод-проекта.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(logfile: Path, name: str = "etl") -> logging.Logger:
    logfile.parent.mkdir(parents=True, exist_ok=True)

    # Консоль Windows бывает cp1251 — переводим вывод в UTF-8, иначе кириллица в логе падает.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(logfile, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger
