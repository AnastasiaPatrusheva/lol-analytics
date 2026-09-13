"""
Data Quality слой проекта LOL.

Запускает набор проверок поверх нормализованной таблицы
``data/normalized/all_matches_common.csv`` и печатает понятный отчёт.

Назначение — контроль качества данных на выходе пайплайна. При обнаружении
проблем (нехватка участников в матче, посторонний режим игры, неверные типы)
скрипт завершается с ненулевым кодом возврата и указывает, какая именно
проверка не пройдена.

Уровни:
- ERROR — данные нельзя использовать, скрипт завершится с кодом 1;
- WARN  — подозрительно, но не критично, скрипт не падает.

Пример запуска:
    python scripts/run_data_quality.py
    python scripts/run_data_quality.py --strict   # WARN тоже считать ошибкой
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg  # noqa: E402

# Проверяем ровно тот артефакт, из которого потом собирается звезда:
# build_star_schema берёт Parquet, если он есть, и только иначе CSV. Раньше здесь
# был прошит CSV, и валидировался не тот файл, который шёл в витрины.
DATA_PARQUET = cfg.COMMON_TABLE.with_suffix(".parquet")
DATA_CSV = cfg.COMMON_TABLE.with_suffix(".csv")
DATA_PATH = DATA_PARQUET if DATA_PARQUET.exists() else DATA_CSV
REPORT_DIR = cfg.DQ_DIR

# Пороги ранкед-соло и допустимые роли — из центрального конфига (config.py).
RANKED_SOLO_QUEUE_ID = cfg.RANKED_SOLO_QUEUE_ID
STANDARD_POSITIONS = set(cfg.STANDARD_POSITIONS)  # в конфиге список; здесь нужен set для операций над множествами
UNDEFINED_SHARE_WARN = cfg.UNDEFINED_SHARE_WARN
# Пороги предупреждений: старше — данные пора обновить; ремейков больше — вопрос к сбору.
FRESHNESS_WARN_DAYS = 120
REMAKE_SHARE_WARN = 0.05

# Метрики, которые по смыслу не могут быть отрицательными.
NON_NEGATIVE_COLUMNS = [
    "kills", "deaths", "assists",
    "gold_earned", "gold_spent",
    "total_damage_dealt_to_champions", "total_damage_taken",
    "vision_score", "wards_placed", "wards_killed",
    "dragon_kills", "baron_kills",
    "game_duration_sec", "game_duration_min",
]

CRITICAL_COLUMNS = [
    "data_source", "match_id", "participant_id", "puuid",
    "champion_id", "champion_name", "team_id", "win",
    "team_position", "queue_id", "kills", "deaths", "assists",
    "kda", "gold_per_min", "damage_per_min",
]


class Report:
    """Накапливает результаты проверок и определяет, пройден ли прогон."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, name: str, passed: bool, severity: str, detail: str) -> None:
        self.rows.append(
            {"check": name, "passed": passed, "severity": severity, "detail": detail}
        )
        status = "PASS" if passed else severity
        print(f"  [{status:5}] {name} - {detail}")

    def has_errors(self, strict: bool) -> bool:
        for row in self.rows:
            if row["passed"]:
                continue
            if row["severity"] == "ERROR" or (strict and row["severity"] == "WARN"):
                return True
        return False

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def load_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Нет файла {DATA_PATH}. Сначала выполните scripts/build_common_analytics_layer.py"
        )
    if DATA_PATH.suffix == ".parquet":
        df = pd.read_parquet(DATA_PATH)
        return df.astype({"match_id": "string"}) if "match_id" in df.columns else df
    # match_id читаем строкой, чтобы длинные id не превратились в float и не потеряли точность.
    return pd.read_csv(DATA_PATH, dtype={"match_id": "string"}, low_memory=False)


def check_schema(df: pd.DataFrame, report: Report) -> None:
    missing = [c for c in CRITICAL_COLUMNS if c not in df.columns]
    report.add(
        "schema_columns",
        passed=not missing,
        severity="ERROR",
        detail="все нужные поля на месте" if not missing else f"не хватает полей: {missing}",
    )


def check_not_empty(df: pd.DataFrame, report: Report) -> None:
    report.add(
        "not_empty",
        passed=len(df) > 0,
        severity="ERROR",
        detail=f"{len(df):,} записей игроков".replace(",", " "),
    )


def check_unique_key(df: pd.DataFrame, report: Report) -> None:
    key = ["data_source", "match_id", "participant_id"]
    dups = int(df.duplicated(subset=key).sum())
    report.add(
        "unique_participant_key",
        passed=dups == 0,
        severity="ERROR",
        detail="повторов нет" if dups == 0 else f"{dups} повторных записей",
    )


def check_ten_participants(df: pd.DataFrame, report: Report) -> None:
    # Главная структурная проверка: в каждом матче ровно 10 участников.
    sizes = df.groupby(["data_source", "match_id"]).size()
    bad = int((sizes != 10).sum())
    report.add(
        "ten_participants_per_match",
        passed=bad == 0,
        severity="ERROR",
        detail="в каждом матче 10 игроков" if bad == 0 else f"{bad} матчей, где игроков не 10",
    )


def check_team_id(df: pd.DataFrame, report: Report) -> None:
    bad = int((~df["team_id"].isin([100, 200])).sum())
    report.add(
        "team_id_values",
        passed=bad == 0,
        severity="ERROR",
        detail="у всех записей сторона синие или красные" if bad == 0 else f"{bad} записей с неизвестной стороной",
    )


def check_queue(df: pd.DataFrame, report: Report) -> None:
    bad = int((df["queue_id"] != RANKED_SOLO_QUEUE_ID).sum())
    report.add(
        "queue_is_ranked_solo",
        passed=bad == 0,
        severity="ERROR",
        detail="только рейтинговые одиночные матчи" if bad == 0 else f"{bad} записей из других режимов",
    )


def check_win_balance(df: pd.DataFrame, report: Report) -> None:
    # В каждом матче 5 победителей и 5 проигравших, поэтому winrate по источнику ≈ 0.5.
    # Существенное отклонение указывает на несбалансированные данные или потерю части строк.
    for source, group in df.groupby("data_source"):
        wr = float(group["win"].mean())
        ok = abs(wr - 0.5) <= 0.01
        report.add(
            f"win_balance[{source}]",
            passed=ok,
            severity="ERROR",
            detail=f"побед {wr:.1%}, должно быть 50%",
        )


def check_non_negative(df: pd.DataFrame, report: Report) -> None:
    offenders = []
    for col in NON_NEGATIVE_COLUMNS:
        if col in df.columns and (df[col].dropna() < 0).any():
            offenders.append(col)
    report.add(
        "non_negative_metrics",
        passed=not offenders,
        severity="ERROR",
        detail="отрицательных чисел нет" if not offenders else f"отрицательные числа в: {offenders}",
    )


def check_kda_finite(df: pd.DataFrame, report: Report) -> None:
    # kda считается через deaths.clip(lower=1), поэтому бесконечностей быть не должно.
    bad = int(df["kda"].isna().sum() + np.isinf(df["kda"]).sum())
    report.add(
        "kda_finite",
        passed=bad == 0,
        severity="ERROR",
        detail="KDA посчитан у всех записей" if bad == 0 else f"{bad} записей без KDA",
    )


def check_undefined_roles(df: pd.DataFrame, report: Report) -> None:
    # Роль может быть не определена (ливеры, edge-cases). Это не ошибка,
    # но большая доля таких строк указывает на присутствие постороннего режима игры.
    valid_or_undef = STANDARD_POSITIONS | {"UNDEFINED"}
    unexpected = sorted(set(df["team_position"].dropna().unique()) - valid_or_undef)
    share = float((df["team_position"] == "UNDEFINED").mean())
    passed = not unexpected and share <= UNDEFINED_SHARE_WARN
    if unexpected:
        detail = f"неожиданные роли: {unexpected}"
    else:
        detail = f"без роли {share:.1%} записей, допустимо {UNDEFINED_SHARE_WARN:.0%}"
    report.add("team_position_values", passed=passed, severity="WARN", detail=detail)


def check_no_null_keys(df: pd.DataFrame, report: Report) -> None:
    null_keys = {
        c: int(df[c].isna().sum())
        for c in ["match_id", "puuid", "champion_id"]
        if c in df.columns and df[c].isna().any()
    }
    report.add(
        "keys_not_null",
        passed=not null_keys,
        severity="ERROR",
        detail="у всех записей есть матч, игрок и чемпион" if not null_keys else f"пропуски: {null_keys}",
    )


def check_freshness(df: pd.DataFrame, report: Report) -> None:
    """Свежесть данных: самый поздний матч в выборке.

    Молчаливое устаревание — самый частый способ показывать неверные цифры:
    пайплайн зелёный, витрины собираются, а данные полугодовой давности.
    """
    if "game_start_utc" not in df.columns:
        report.add("freshness", passed=True, severity="WARN", detail="нет колонки game_start_utc")
        return
    latest = pd.to_datetime(df["game_start_utc"], errors="coerce", utc=True).max()
    if pd.isna(latest):
        report.add("freshness", passed=False, severity="WARN",
                   detail="не удалось разобрать ни одной даты матча")
        return
    age_days = (pd.Timestamp.now(tz="UTC") - latest).days
    report.add(
        "freshness", passed=age_days <= FRESHNESS_WARN_DAYS, severity="WARN",
        detail=f"последний матч {latest:%d.%m.%Y}, при сборке прошло {age_days} дн.",
    )


def check_remake_share(df: pd.DataFrame, report: Report) -> None:
    """Доля ремейков: матчи короче MIN_MATCH_MINUTES отменены на 3-й минуте.

    Звезда их отфильтровывает, но знать их долю нужно: резкий рост означает
    проблему со сбором, а не с игроками.
    """
    if "game_duration_min" not in df.columns:
        return
    dur = pd.to_numeric(df["game_duration_min"], errors="coerce")
    share = float((dur < cfg.MIN_MATCH_MINUTES).mean())
    report.add(
        "remake_share", passed=share <= REMAKE_SHARE_WARN, severity="WARN",
        detail=f"ремейков {share:.1%}, допустимо {REMAKE_SHARE_WARN:.0%}",
    )


def check_reference_integrity(df: pd.DataFrame, report: Report) -> None:
    """Ссылочная целостность со справочником чемпионов Data Dragon.

    Незнакомый champion_id иначе молча получает primary_class = 'Unknown'
    и тихо портит разрезы по классам.
    """
    if not cfg.CHAMPIONS_REF.exists() or "champion_id" not in df.columns:
        return
    known = set(pd.read_csv(cfg.CHAMPIONS_REF, usecols=["champion_id"])["champion_id"])
    ids = pd.to_numeric(df["champion_id"], errors="coerce").dropna().astype(int)
    missing = sorted(set(ids) - known)
    report.add(
        "champion_id_in_reference", passed=not missing, severity="ERROR",
        detail="все чемпионы есть в справочнике Riot" if not missing
               else f"{len(missing)} чемпионов нет в справочнике: {missing[:10]}",
    )


def run_checks(df: pd.DataFrame) -> Report:
    report = Report()
    check_not_empty(df, report)
    check_schema(df, report)
    check_unique_key(df, report)
    check_no_null_keys(df, report)
    check_ten_participants(df, report)
    check_team_id(df, report)
    check_queue(df, report)
    check_win_balance(df, report)
    check_non_negative(df, report)
    check_kda_finite(df, report)
    check_undefined_roles(df, report)
    check_reference_integrity(df, report)
    check_remake_share(df, report)
    check_freshness(df, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Data Quality проверки для общей таблицы LOL.")
    parser.add_argument("--strict", action="store_true", help="считать WARN ошибкой")
    args = parser.parse_args()

    # Консоль Windows по умолчанию cp1251 — переключаем вывод на UTF-8,
    # чтобы кириллица в отчёте не падала с UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"Проверяю: {DATA_PATH}")
    df = load_data()
    print(f"Загружено строк: {len(df)}\n")

    report = run_checks(df)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "data_quality_report.csv"
    report.to_frame().to_csv(report_path, index=False, encoding="utf-8")

    failed = report.has_errors(strict=args.strict)
    print()
    if failed:
        print(f"РЕЗУЛЬТАТ: проверки не пройдены. Отчёт: {report_path}")
        return 1
    print(f"РЕЗУЛЬТАТ: все критичные проверки пройдены. Отчёт: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
