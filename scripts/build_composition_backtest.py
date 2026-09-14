"""
Проверка модели «Состав» на реальных командах — build-шаг, не рантайм дашборда.

Вкладка «Состав» оценивает пятёрку так: у каждого чемпиона берётся его точечный
winrate на своей роли, пять значений усредняются с равными весами ролей. Формула
выбрана по итогам этой проверки: сначала вкладка брала нижнюю границу Уилсона с
весами по числу игр, и на реальных пятёрках с известным исходом это угадывало хуже.

Как устроена проверка:

1. Разделение по времени, а не случайное. Модель учится на всех патчах, кроме
   последнего, и проверяется на последнем. Так же она работала бы в жизни:
   оцениваем состав по прошлым играм, а исход ещё не наступил. Случайное
   разделение было бы мягче, потому что подмешивало бы будущее в обучение.
2. Оцениваются обе команды каждого матча, и побеждает та, чья оценка выше.
   Это честнее, чем спрашивать «выиграет ли команда»: в матче ровно один
   победитель. Но точка отсчёта — не 50%: стороны карты не равны, и правило
   «всегда побеждает сторона, что чаще выигрывала в прошлых патчах» (sideonly)
   угадывает больше половины без единого чемпиона. Прогноз сравнивается с ним.
3. Считаются несколько версий оценки: точечный winrate с равными весами ролей
   (raw, так считает вкладка), нижняя граница Уилсона с равными весами (equal) и
   с весами по числу игр (weighted, прежняя формула вкладки), только сторона
   (sideonly) и точечный winrate плюс сторона (side). Веса по числу игр отражают
   надёжность оценки, а не важность роли, поэтому сравнение показывает, не мешают ли они.

Метрики: доля верно угаданных матчей, ROC AUC на уровне команд и калибровка
(сбывается ли предсказанный процент). Результат — витрины composition_backtest
и composition_calibration.

Запуск:  python scripts/build_composition_backtest.py   (или через main.py backtest)
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from lol_utils import config as cfg, save_parquet_if_available  # noqa: E402
from lol_utils.sql import install_macros  # noqa: E402

MIN_TRAIN_GAMES = 20      # чемпион×роль реже — оценка слишком шумная, берём 0.5
MIN_TEST_MATCHES = 300    # меньше — проверка ничего не покажет
MIN_COVERAGE = 0.75       # доля пиков с оценкой из обучения; ниже — проверяем не модель, а заглушку
N_BINS = 8                # столько корзин в калибровке

PATCH = ("split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2)")
ROLES = ", ".join(f"'{r}'" for r in cfg.STANDARD_POSITIONS)


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    install_macros(con)
    for table in ("fact_participant", "dim_match", "dim_champion"):
        path = (cfg.STAR_DIR / f"{table}.parquet").as_posix()
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return con


def _test_patch(con: duckdb.DuckDBPyConnection, source: str) -> str | None:
    """Самый поздний патч источника, если на нём хватает матчей для проверки."""
    df = con.execute(f"""
        SELECT {PATCH} AS patch, COUNT(*) AS matches
        FROM dim_match
        WHERE data_source = '{source}' AND game_version IS NOT NULL
        GROUP BY 1
    """).df()
    df = df[df["patch"].str.match(r"^\d+\.\d+$", na=False)]
    if df.empty:
        return None
    df["key"] = df["patch"].map(lambda p: [int(n) for n in p.split(".")])
    latest = df.sort_values("key").iloc[-1]
    return str(latest["patch"]) if latest["matches"] >= MIN_TEST_MATCHES else None


def _team_scores(con: duckdb.DuckDBPyConnection, source: str, patch: str) -> pd.DataFrame:
    """Оценка каждой команды тестового патча по модели, обученной на прошлых патчах."""
    return con.execute(f"""
        WITH f AS (
            SELECT p.match_id, p.team_id, p.champion_id, p.role_key, p.win,
                   {PATCH} AS patch
            FROM fact_participant p
            JOIN dim_match m ON p.data_source = m.data_source AND p.match_id = m.match_id
            WHERE p.data_source = '{source}' AND p.role_key IN ({ROLES})
        ),
        train AS (
            SELECT champion_id, role_key,
                   COUNT(*) AS games,
                   AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS winrate,
                   wilson_low(AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END), COUNT(*)) AS score
            FROM f WHERE patch <> '{patch}'
            GROUP BY 1, 2 HAVING COUNT(*) >= {MIN_TRAIN_GAMES}
        ),
        -- Поправка за сторону карты (100 — синие, 200 — красные): насколько чаще
        -- половины сторона выигрывала в прошлых патчах. Тестовый патч не трогаем.
        side AS (
            SELECT team_id, AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) - 0.5 AS shift
            FROM f WHERE patch <> '{patch}'
            GROUP BY 1
        )
        SELECT t.match_id, t.team_id,
               ANY_VALUE(s.shift) AS side_shift,
               ANY_VALUE(t.win) AS win,
               COUNT(tr.score) AS covered,
               -- равные веса: каждая роль вносит 1/5
               AVG(COALESCE(tr.score, 0.5)) AS score_equal,
               -- веса по числу игр чемпиона (прежняя формула вкладки)
               SUM(COALESCE(tr.score, 0.5) * COALESCE(tr.games, 1))
                   / SUM(COALESCE(tr.games, 1)) AS score_weighted,
               -- точечный winrate с равными весами: так считает вкладка
               AVG(COALESCE(tr.winrate, 0.5)) AS score_raw
        FROM f t
        LEFT JOIN train tr ON t.champion_id = tr.champion_id AND t.role_key = tr.role_key
        LEFT JOIN side s ON t.team_id = s.team_id
        WHERE t.patch = '{patch}'
        GROUP BY 1, 2
        HAVING COUNT(*) = 5
    """).df()


def _auc(scores: pd.Series, wins: pd.Series) -> float:
    """ROC AUC через ранги (статистика Манна-Уитни).

    0.5 — модель не отличает победителей от проигравших, 1.0 — идеально.
    Совпадающие оценки получают средний ранг, иначе AUC систематически смещается.
    """
    ranks = scores.rank(method="average")
    n_pos = int(wins.sum())
    n_neg = int(len(wins) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[wins].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _head_to_head(teams: pd.DataFrame, col: str) -> tuple[int, int]:
    """Сколько матчей угадано, если побеждает команда с более высокой оценкой."""
    piv = teams.pivot(index="match_id", columns="team_id", values=[col, "win"])
    sides = list(piv[col].columns)
    if len(sides) != 2:
        return 0, 0
    a, b = sides
    diff = piv[(col, a)] - piv[(col, b)]
    a_won = piv[("win", a)].astype(bool)
    decided = diff != 0                      # ничьи по оценке не засчитываем
    correct = ((diff > 0) == a_won) & decided
    return int(correct.sum()), int(decided.sum())


def _calibration(teams: pd.DataFrame, col: str) -> pd.DataFrame:
    """Сбывается ли предсказанный процент: предсказано против фактического по корзинам."""
    bins = pd.qcut(teams[col], N_BINS, duplicates="drop")
    grp = teams.groupby(bins, observed=True)
    out = pd.DataFrame({
        "teams": grp.size(),
        "predicted": grp[col].mean(),
        "actual": grp["win"].mean(),
    }).reset_index(drop=True)
    edges = [iv for iv in grp.groups.keys()]
    out["bin_low"] = [float(iv.left) for iv in edges]
    out["bin_high"] = [float(iv.right) for iv in edges]
    return out


def backtest_source(con: duckdb.DuckDBPyConnection, source: str) -> tuple[dict, pd.DataFrame]:
    patch = _test_patch(con, source)
    if patch is None:
        print(f"{source}: пропускаю — нет патча с {MIN_TEST_MATCHES}+ матчами")
        return {}, pd.DataFrame()

    teams = _team_scores(con, source, patch)
    if len(teams) < 2 * MIN_TEST_MATCHES:
        print(f"{source}: пропускаю — только {len(teams)} полных команд в патче {patch}")
        return {}, pd.DataFrame()

    teams["win"] = teams["win"].astype(bool)
    # Доля пиков, у которых нашлась оценка в обучающей выборке. Остальные получают
    # заглушку 0.5, и при низком покрытии проверялась бы именно заглушка, а не модель.
    coverage = float(teams["covered"].sum() / (5 * len(teams)))
    if coverage < MIN_COVERAGE:
        print(f"{source}: пропускаю — покрытие {coverage:.1%}, у большинства пиков нет "
              f"оценки в патчах до {patch}")
        return {}, pd.DataFrame()

    row = {"data_source": source, "test_patch": patch,
           "test_teams": len(teams), "test_matches": teams["match_id"].nunique(),
           "coverage": coverage}

    teams["side_shift"] = teams["side_shift"].fillna(0.0)
    # Только сторона: «всегда побеждает та сторона, что чаще выигрывала раньше».
    # Это настоящая точка отсчёта вместо монетки, если стороны не равны.
    teams["score_sideonly"] = 0.5 + teams["side_shift"]
    # Чемпионы плюс сторона: доля побед пятёрки, сдвинутая на преимущество стороны.
    teams["score_side"] = teams["score_raw"] + teams["side_shift"]

    # Дают ли чемпионы что-то сверх стороны: берём матчи, где по чемпионам сильнее
    # та сторона, что обычно проигрывает, и смотрим, как часто она побеждает там.
    row.update(_against_side(teams))

    for col, tag in (("score_equal", "equal"), ("score_weighted", "weighted"),
                     ("score_raw", "raw"), ("score_sideonly", "sideonly"),
                     ("score_side", "side")):
        hit, total = _head_to_head(teams, col)
        row[f"accuracy_{tag}"] = hit / total if total else float("nan")
        row[f"decided_{tag}"] = total
        row[f"auc_{tag}"] = _auc(teams[col], teams["win"])
        # Смещение: насколько предсказанный процент в среднем отличается от факта.
        row[f"bias_{tag}"] = float(teams[col].mean() - teams["win"].mean())

    # Калибруем оба варианта усреднения: осторожный (нижняя граница) и точечный.
    calib = pd.concat([
        _calibration(teams, "score_equal").assign(variant="Нижняя граница Уилсона"),
        _calibration(teams, "score_raw").assign(variant="Точечный winrate"),
        _calibration(teams, "score_side").assign(variant="Точечный winrate + сторона"),
    ], ignore_index=True)
    calib.insert(0, "data_source", source)
    print(f"{source}: патч {patch}, {row['test_matches']} матчей, покрытие {row['coverage']:.1%}")
    for tag, label in (("equal", "Уилсон, равные веса"),
                       ("weighted", "Уилсон, веса по играм"),
                       ("raw", "точечный winrate, равные веса (как в дашборде)"),
                       ("sideonly", "только сторона"),
                       ("side", "точечный winrate + сторона")):
        print(f"    {label:42s} точность {row[f'accuracy_{tag}']:.1%}  "
              f"AUC {row[f'auc_{tag}']:.3f}  смещение {row[f'bias_{tag}']:+.1%}")
    print(f"    слабая сторона: обычно {row['weak_side_wr']:.1%} побед, "
          f"с чемпионами сильнее — {row['weak_side_fav_wr']:.1%} "
          f"({row['weak_side_fav_matches']} матчей), слабее — {row['weak_side_unfav_wr']:.1%}")
    return row, calib


def _against_side(teams: pd.DataFrame) -> dict:
    """Как часто побеждает слабая сторона, когда по чемпионам сильнее она и когда соперник.

    Если чемпионы ничего не добавляют к стороне, обе доли совпадут с её обычной.
    """
    piv = teams.pivot(index="match_id", columns="team_id",
                      values=["score_raw", "side_shift", "win"])
    weak = min(piv["side_shift"].columns, key=lambda s: piv[("side_shift", s)].mean())
    strong = next(s for s in piv["side_shift"].columns if s != weak)
    diff = piv[("score_raw", weak)] - piv[("score_raw", strong)]
    won = piv[("win", weak)].astype(bool)
    fav, unfav = diff > 0, diff < 0
    return {
        "weak_side": int(weak),
        "weak_side_wr": float(won.mean()),
        "weak_side_fav_matches": int(fav.sum()),
        "weak_side_fav_wr": float(won[fav].mean()),
        "weak_side_unfav_matches": int(unfav.sum()),
        "weak_side_unfav_wr": float(won[unfav].mean()),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not (cfg.STAR_DIR / "fact_participant.parquet").exists():
        print("Нет звёздной схемы. Сначала: python main.py star")
        return 1

    con = _connect()
    sources = [r[0] for r in con.execute(
        "SELECT DISTINCT data_source FROM fact_participant ORDER BY 1").fetchall()]

    rows, calibs = [], []
    for source in sources:
        row, calib = backtest_source(con, source)
        if row:
            rows.append(row)
            calibs.append(calib)

    if not rows:
        print("Ни на одном источнике не хватает данных для проверки.")
        return 1

    cfg.STAR_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in (("composition_backtest", pd.DataFrame(rows)),
                     ("composition_calibration", pd.concat(calibs, ignore_index=True))):
        out = cfg.STAR_DIR / name
        df.to_csv(out.with_suffix(".csv"), index=False, encoding="utf-8")
        save_parquet_if_available(df, out.with_suffix(".parquet"))
        print(f"  {name}: {len(df)} строк")
    return 0


if __name__ == "__main__":
    sys.exit(main())
