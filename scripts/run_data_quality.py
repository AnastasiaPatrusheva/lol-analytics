"""
Data Quality слой проекта LOL.

Запускает набор проверок поверх нормализованной таблицы
``data/normalized/all_matches_common.csv`` и печатает понятный отчёт.

Идея: это «контроль на выходе конвейера». Если данные собрались неправильно
(потерялись участники, затесался чужой режим игры, поехали типы) — скрипт
падает с ненулевым кодом возврата и говорит, ЧТО именно сломалось. Так ошибку
видно сразу, а не на дашборде через неделю.

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

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "normalized" / "all_matches_common.csv"
REPORT_DIR = PROJECT_ROOT / "outputs" / "data_quality"

# Порог ранкед-соло очереди и допустимые роли.
RANKED_SOLO_QUEUE_ID = 420
STANDARD_POSITIONS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
UNDEFINED_SHARE_WARN = 0.05  # доля ролей UNDEFINED выше 5% -> предупреждение

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
    """Копит результаты проверок и решает, упал ли прогон."""

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
            f"Нет файла {DATA_PATH}. Сначала запусти scripts/build_common_analytics_layer.py"
        )
    # match_id читаем строкой, чтобы длинные id не превратились в float и не потеряли точность.
    return pd.read_csv(DATA_PATH, dtype={"match_id": "string"}, low_memory=False)


def check_schema(df: pd.DataFrame, report: Report) -> None:
    missing = [c for c in CRITICAL_COLUMNS if c not in df.columns]
    report.add(
        "schema_columns",
        passed=not missing,
        severity="ERROR",
        detail="все ключевые колонки на месте" if not missing else f"нет колонок: {missing}",
    )


def check_not_empty(df: pd.DataFrame, report: Report) -> None:
    report.add(
        "not_empty",
        passed=len(df) > 0,
        severity="ERROR",
        detail=f"{len(df)} строк",
    )


def check_unique_key(df: pd.DataFrame, report: Report) -> None:
    key = ["data_source", "match_id", "participant_id"]
    dups = int(df.duplicated(subset=key).sum())
    report.add(
        "unique_participant_key",
        passed=dups == 0,
        severity="ERROR",
        detail="дублей нет" if dups == 0 else f"{dups} дублей по {key}",
    )


def check_ten_participants(df: pd.DataFrame, report: Report) -> None:
    # Главная структурная проверка: в каждом матче ровно 10 участников.
    sizes = df.groupby(["data_source", "match_id"]).size()
    bad = int((sizes != 10).sum())
    report.add(
        "ten_participants_per_match",
        passed=bad == 0,
        severity="ERROR",
        detail="во всех матчах по 10 игроков" if bad == 0 else f"{bad} матчей не по 10 участников",
    )


def check_team_id(df: pd.DataFrame, report: Report) -> None:
    bad = int((~df["team_id"].isin([100, 200])).sum())
    report.add(
        "team_id_values",
        passed=bad == 0,
        severity="ERROR",
        detail="team_id только 100/200" if bad == 0 else f"{bad} строк с чужим team_id",
    )


def check_queue(df: pd.DataFrame, report: Report) -> None:
    bad = int((df["queue_id"] != RANKED_SOLO_QUEUE_ID).sum())
    report.add(
        "queue_is_ranked_solo",
        passed=bad == 0,
        severity="ERROR",
        detail="только queue 420" if bad == 0 else f"{bad} строк из других режимов",
    )


def check_win_balance(df: pd.DataFrame, report: Report) -> None:
    # В каждом матче 5 победителей и 5 проигравших, поэтому winrate по источнику ≈ 0.5.
    # Сильное отклонение значит, что данные перекошены или потеряна часть строк.
    for source, group in df.groupby("data_source"):
        wr = float(group["win"].mean())
        ok = abs(wr - 0.5) <= 0.01
        report.add(
            f"win_balance[{source}]",
            passed=ok,
            severity="ERROR",
            detail=f"winrate={wr:.3f} (ожидаем ~0.5)",
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
        detail="отрицательных значений нет" if not offenders else f"отрицательные значения в: {offenders}",
    )


def check_kda_finite(df: pd.DataFrame, report: Report) -> None:
    # kda считается через deaths.clip(lower=1), поэтому бесконечностей быть не должно.
    import numpy as np

    bad = int(df["kda"].isna().sum() + np.isinf(df["kda"]).sum())
    report.add(
        "kda_finite",
        passed=bad == 0,
        severity="ERROR",
        detail="kda везде конечна" if bad == 0 else f"{bad} строк с NaN/inf в kda",
    )


def check_undefined_roles(df: pd.DataFrame, report: Report) -> None:
    # Роль может быть не определена (ливеры, edge-cases). Это не ошибка,
    # но если таких строк много — значит затесался не тот режим игры.
    valid_or_undef = STANDARD_POSITIONS | {"UNDEFINED"}
    unexpected = sorted(set(df["team_position"].dropna().unique()) - valid_or_undef)
    share = float((df["team_position"] == "UNDEFINED").mean())
    passed = not unexpected and share <= UNDEFINED_SHARE_WARN
    if unexpected:
        detail = f"неожиданные роли: {unexpected}"
    else:
        detail = f"доля UNDEFINED = {share:.1%} (порог {UNDEFINED_SHARE_WARN:.0%})"
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
        detail="ключи без пропусков" if not null_keys else f"пропуски в ключах: {null_keys}",
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
