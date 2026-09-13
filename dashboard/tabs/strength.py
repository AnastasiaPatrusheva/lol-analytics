"""Вкладка «Сила чемпиона»: один вопрос, одна статистика, разные условия.

Раньше это были три вкладки. «Чемпионы» считали winrate при условии роли и
проверяли значимость интервалом Уилсона с поправкой Бонферрони. «Мета» считала то
же самое при условии патча, но z-тестом и без поправки. «Длительность» — при
условии длины матча и вообще без проверки. Три ответа на один вопрос тремя
методами защитить невозможно, поэтому здесь один метод на все срезы.

Побочный эффект слияния — главная находка проекта становится видимой: сила
чемпиона проступает только внутри роли и патча, а в общей таблице усредняется в ноль.
"""
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, download_csv, champion_images, POSITIONS
from dashboard.stats import two_proportion_pvalue

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from lol_utils.sql import z_for_multiple_tests  # noqa: E402

ROLES = POSITIONS[1:]                 # POSITIONS[0] — «Все»
ALL_SLICE = "Все роли вместе"
# Ключи ролей приходят из данных латиницей; в интерфейсе показываем по-русски.
ROLE_RU = {"Все": "Все роли", "TOP": "Топ", "JUNGLE": "Лес", "MIDDLE": "Мид",
           "BOTTOM": "Бот / керри", "UTILITY": "Саппорт"}
ALPHA = 0.05
# Патч из game_version: «16.11.673.4372» -> «16.11».
PATCH_EXPR = "split_part(m.game_version, '.', 1) || '.' || split_part(m.game_version, '.', 2)"
# Границы групп по длине матча, те же, что в витрине champion_by_duration.
SHORT_MAX, LONG_MIN = 25, 32


def _patches(source: str) -> list[str]:
    """Патчи источника, отсортированные по номеру (16.9 < 16.10, а не как строки)."""
    df = run(f"""
        SELECT {PATCH_EXPR} AS patch, COUNT(*) AS matches
        FROM dim_match m
        WHERE m.data_source = '{source}' AND m.game_version IS NOT NULL
        GROUP BY 1 HAVING COUNT(*) >= 30 ORDER BY 1
    """)
    vals = [p for p in df["patch"].tolist() if p and p != "."]
    return sorted(vals, key=lambda x: [int(n) for n in x.split(".")])


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение при числе: 1 чемпион, 2 чемпиона, 5 чемпионов."""
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _hero(title, name, value, img, accent="#C8AA6E") -> str:
    pic = (f"<img src='{img}' style='width:56px;height:56px;border-radius:10px;"
           f"border:1px solid #2f3a4d;flex:none'>") if img else ""
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:14px;"
        "padding:13px 15px;display:flex;gap:12px;align-items:center'>"
        f"{pic}<div style='min-width:0'>"
        f"<div style='font-size:11px;color:#a49b86;text-transform:uppercase;"
        f"letter-spacing:.05em'>{title}</div>"
        "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:19px;"
        f"font-weight:600;color:#e8ecec\">{name}</div>"
        f"<div style='font-size:13px;color:{accent}'>{value}</div>"
        "</div></div>"
    )


# Роли в предложном падеже: у каждой свой предлог, одним шаблоном не обойтись.
ROLE_IN = {"TOP": "на топе", "JUNGLE": "в лесу", "MIDDLE": "на миде",
           "BOTTOM": "на боте", "UTILITY": "на саппорте"}
# Пример должен стоять на заметной выборке: на полусотне матчей доля побед
# скачет сама по себе, и пример будет объяснять шум, а не устройство подсчёта.
EXAMPLE_MIN_GAMES = 120


def role_gap_example(source: str, patch_filter: str, min_games: int) -> dict | None:
    """Живой чемпион, у которого доли побед по ролям сильно расходятся,
    а общая при этом близка к половине.

    Нужен вместо выдуманного примера. Выдуманные числа тут особенно опасны:
    общая доля побед — не среднее двух долей, а взвешенное по числу игр,
    и на глаз такой пример не сойдётся.
    """
    roles = ", ".join(f"'{r}'" for r in ROLES)
    min_games = max(min_games, EXAMPLE_MIN_GAMES)
    df = run(f"""
        WITH per_role AS (
            SELECT ch.champion_name, f.role_key,
                   COUNT(*) AS games,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS wr
            FROM fact_participant f
            JOIN dim_champion ch ON f.champion_id = ch.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}' AND f.role_key IN ({roles}) {patch_filter}
            GROUP BY 1, 2 HAVING COUNT(*) >= {min_games}
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY champion_name ORDER BY wr)      AS lo,
                   ROW_NUMBER() OVER (PARTITION BY champion_name ORDER BY wr DESC) AS hi,
                   COUNT(*)   OVER (PARTITION BY champion_name)                    AS n_roles,
                   SUM(games) OVER (PARTITION BY champion_name)                    AS total,
                   SUM(games * wr) OVER (PARTITION BY champion_name)
                       / SUM(games) OVER (PARTITION BY champion_name)              AS overall
            FROM per_role
        )
        SELECT champion_name, total, overall,
               MAX(CASE WHEN lo = 1 THEN role_key END) AS worst_role,
               MAX(CASE WHEN lo = 1 THEN wr END)       AS worst_wr,
               MAX(CASE WHEN lo = 1 THEN games END)    AS worst_games,
               MAX(CASE WHEN hi = 1 THEN role_key END) AS best_role,
               MAX(CASE WHEN hi = 1 THEN wr END)       AS best_wr,
               MAX(CASE WHEN hi = 1 THEN games END)    AS best_games
        FROM ranked WHERE n_roles >= 2
        GROUP BY 1, 2, 3
        HAVING MAX(CASE WHEN hi = 1 THEN wr END) - MAX(CASE WHEN lo = 1 THEN wr END) >= 0.05
           AND abs(overall - 0.5) <= 0.03
        ORDER BY MAX(CASE WHEN hi = 1 THEN wr END) - MAX(CASE WHEN lo = 1 THEN wr END) DESC
        LIMIT 1
    """)
    return None if df.empty else df.iloc[0].to_dict()


def aggregation_effect(source: str, patch_filter: str, min_games: int) -> pd.DataFrame:
    """Сколько чемпионов значимо отличаются от 50% в разных разрезах.

    Ради этой таблицы вкладки и сливались: в общей строке значимых обычно ноль,
    а внутри роли они появляются. Ноль в общем срезе — следствие усреднения по
    ролям, а не свойство игры.
    """
    slices = f"""
        WITH j AS (
            SELECT f.role_key, f.champion_id, f.match_id, f.win
            FROM fact_participant f
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}'
              AND f.role_key IN ({", ".join(f"'{r}'" for r in ROLES)})
              {patch_filter}
        ),
        by_role AS (
            SELECT role_key AS slice, champion_id,
                   COUNT(DISTINCT match_id) AS games,
                   SUM(CASE WHEN win THEN 1 ELSE 0 END) * 1.0
                       / COUNT(DISTINCT match_id) AS wr
            FROM j GROUP BY 1, 2 HAVING COUNT(DISTINCT match_id) >= {min_games}
        ),
        pooled AS (
            SELECT '{ALL_SLICE}' AS slice, champion_id,
                   COUNT(DISTINCT match_id) AS games,
                   SUM(CASE WHEN win THEN 1 ELSE 0 END) * 1.0
                       / COUNT(DISTINCT match_id) AS wr
            FROM j GROUP BY 1, 2 HAVING COUNT(DISTINCT match_id) >= {min_games}
        )
        SELECT * FROM pooled UNION ALL SELECT * FROM by_role
    """
    raw = run(slices)
    if raw.empty:
        return raw

    # Поправка Бонферрони считается отдельно в каждом срезе: чем меньше чемпионов
    # проходит порог, тем меньше одновременных проверок и тем мягче порог.
    sizes = raw.groupby("slice").size()
    z_values = ", ".join(f"('{s}', {z_for_multiple_tests(int(n))})" for s, n in sizes.items())

    return run(f"""
        WITH z(slice, z) AS (VALUES {z_values}),
        base AS ({slices})
        SELECT b.slice,
               COUNT(*) AS champions,
               SUM(CASE WHEN wilson_low_z(b.wr, b.games, z.z) > 0.5 THEN 1 ELSE 0 END) AS strong,
               SUM(CASE WHEN wilson_high_z(b.wr, b.games, z.z) < 0.5 THEN 1 ELSE 0 END) AS weak,
               MIN(b.wr) AS wr_min, MAX(b.wr) AS wr_max,
               ANY_VALUE(z.z) AS z
        FROM base b JOIN z ON b.slice = z.slice
        GROUP BY 1
    """)


def render(source: str) -> None:
    st.subheader("Сила чемпиона")
    st.caption(
        "Чемпион — это игровой персонаж, за которого играют. Всего их в игре больше "
        "полутора сотен. Есть ли среди них те, кто выигрывает чаще остальных? В хорошо "
        "настроенной игре каждый побеждает примерно в половине матчей, и вопрос в том, "
        "кто действительно выбивается из этой половины, а кому просто повезло. Условия "
        "сравнения можно менять: роль, патч, длина матча."
    )

    patches = _patches(source)
    c1, c2, c3, c4 = st.columns([1, 1, 1.5, 1.3])
    position = c1.selectbox("Позиция", POSITIONS,
                            format_func=lambda p: ROLE_RU.get(p, p))
    patch = c2.selectbox("Патч", ["Все патчи"] + patches) if patches else "Все патчи"
    min_games = c3.slider("Минимум игр", 5, 100, 30, step=5)
    rank_by = c4.radio(
        "Как сортировать", ["С поправкой на число игр", "Просто по доле побед"],
        help="Пять побед из пяти — это 100% побед, но верить такому нельзя. Поправка "
             "занижает оценку, чтобы отсеять случайных победителей: чем меньше игр "
             "сыграно, тем сильнее занижение. Например, 70% побед на 5 матчах после "
             "неё окажутся ниже, чем 53% побед на 500 матчах. "
             "Метод называется интервалом Уилсона.",
    )

    pos_filter = "" if position == "Все" else f"AND f.role_key = '{position}'"
    patch_filter = "" if patch == "Все патчи" else f"AND {PATCH_EXPR} = '{patch}'"
    order_col = "wilson_low" if rank_by.startswith("С поправкой") else "winrate"

    # Число одновременных проверок = число чемпионов, прошедших порог в этом срезе.
    n_tests = int(run(f"""
        SELECT COUNT(*) AS n FROM (
            SELECT f.champion_id
            FROM fact_participant f
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}' {pos_filter} {patch_filter}
            GROUP BY f.champion_id
            HAVING COUNT(DISTINCT f.match_id) >= {min_games})
    """).iloc[0]["n"])
    if n_tests == 0:
        st.info("Нет чемпионов с таким порогом игр в этом срезе. Снизьте минимум игр.")
        return
    z_adj = z_for_multiple_tests(n_tests)

    champions = run(f"""
        WITH base AS (
            SELECT c.champion_name, c.primary_class, c.champion_id,
                   COUNT(DISTINCT f.match_id) AS games,
                   SUM(CASE WHEN f.win THEN 1 ELSE 0 END) AS wins,
                   (SUM(f.kills) + SUM(f.assists)) * 1.0
                       / GREATEST(SUM(f.deaths), 1) AS avg_kda
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}' {pos_filter} {patch_filter}
            GROUP BY c.champion_name, c.primary_class, c.champion_id
            HAVING COUNT(DISTINCT f.match_id) >= {min_games}
        ),
        ci AS (
            SELECT *, wins * 1.0 / games AS winrate,
                   wilson_low(wins * 1.0 / games, games) AS wilson_low,
                   wilson_high(wins * 1.0 / games, games) AS wilson_high,
                   wilson_low_z(wins * 1.0 / games, games, {z_adj}) AS wilson_low_adj,
                   wilson_high_z(wins * 1.0 / games, games, {z_adj}) AS wilson_high_adj
            FROM base
        )
        SELECT champion_name, primary_class, champion_id, games, winrate,
               wilson_low, wilson_high, avg_kda,
               RANK() OVER (ORDER BY {order_col} DESC) AS rank,
               (winrate - AVG(winrate) OVER (PARTITION BY primary_class)) * 100 AS vs_class,
               CASE WHEN wilson_low_adj > 0.5 THEN 'выигрывает чаще'
                    WHEN wilson_high_adj < 0.5 THEN 'выигрывает реже'
                    ELSE 'как все' END AS verdict
        FROM ci ORDER BY {order_col} DESC
    """)

    imgs = champion_images()
    top_row = champions.iloc[0]
    most_played = champions.loc[champions["games"].idxmax()]
    best_kda = champions.loc[champions["avg_kda"].idxmax()]
    h1, h2, h3 = st.columns(3)
    h1.markdown(_hero("Сильнейший по рейтингу", top_row["champion_name"],
                      f"{top_row[order_col]:.1%} · {int(top_row['games'])} игр",
                      imgs.get(int(top_row["champion_id"]), "")), unsafe_allow_html=True)
    h2.markdown(_hero("Фаворит игроков", most_played["champion_name"],
                      f"{int(most_played['games'])} игр · побед {most_played['winrate']:.0%}",
                      imgs.get(int(most_played["champion_id"]), ""), accent="#5aa0c9"),
                unsafe_allow_html=True)
    h3.markdown(_hero("Лучший KDA", best_kda["champion_name"],
                      f"KDA {best_kda['avg_kda']:.2f}",
                      imgs.get(int(best_kda["champion_id"]), ""), accent="#cda24a"),
                unsafe_allow_html=True)
    st.caption(
        "KDA — убийства и помощи, делённые на смерти. Мы складываем их за все матчи "
        "чемпиона и делим одну сумму на другую. Считать KDA в каждом матче отдельно "
        "и потом усреднять нельзя: матч без единой смерти даёт огромное число, "
        "и в лидеры выходит тот, кому повезло в паре игр."
    )
    st.write("")

    n_strong = int((champions["verdict"] == "выигрывает чаще").sum())
    n_weak = int((champions["verdict"] == "выигрывает реже").sum())
    n_marked = n_strong + n_weak
    # Сколько чемпионов выделилось бы, если проверять каждого поодиночке.
    # Считаем по обычному интервалу, без поправки на число сравнений.
    n_naive = int(((champions["wilson_low"] > 0.5)
                   | (champions["wilson_high"] < 0.5)).sum())
    # Падежи разные: «все 172 чемпиона», но «из 172 чемпионов». Одной формой не обойтись.
    nom = _plural(n_tests, "чемпион", "чемпиона", "чемпионов")
    gen = _plural(n_tests, "чемпиона", "чемпионов", "чемпионов")

    if n_marked:
        st.caption(
            f"Заметно чаще половины побеждают — {n_strong}, заметно реже — {n_weak}. "
            f"Остальные из {n_tests} {gen} от половины неотличимы."
        )
    else:
        st.caption(
            f"В этой выборке {n_tests} {nom} выигрывают примерно одинаково. Разницу "
            "между ними можно объяснить обычным везением."
        )

    # Сколько ложных срабатываний ждём при обычном пороге: alpha × число проверок.
    expected_false = round(ALPHA * n_tests)
    tail = ("но мы не засчитали ни одного" if n_marked == 0
            else f"но засчитали только {n_marked}")
    with st.expander(
            f"Из {n_tests} чемпионов {n_naive} выглядят сильнее остальных, {tail}"):
        st.markdown(
            "Любая проверка по выборке иногда ошибается: мы видим часть матчей "
            "чемпиона, а не все, какие он вообще сыграл. Насколько часто ошибаться — "
            "выбираем мы сами, и обычный выбор такой: примерно 5 промахов "
            "на 100 проверок.\n\n"
            f"Пока чемпион один, риск невелик. Но чемпионов {n_tests}, и при таком "
            f"пороге примерно {expected_false} из них назовутся сильными по ошибке. "
            f"Мы насчитали {n_naive} — и не можем сказать, сколько из них настоящие.\n\n"
            f"Поэтому поднимаем требования: ярлык получает только тот, чей перевес "
            f"не объяснить даже с учётом {n_tests} попыток. Таких оказалось "
            f"**{n_marked}**. Приём называется поправкой Бонферрони."
        )

    st.caption(
        "Середина графика — половина побед: столько выигрывает чемпион, который "
        "не сильнее и не слабее прочих. Столбец вправо означает, что чемпион побеждает "
        "чаще половины, влево — реже. Число у столбца — его доля побед целиком."
    )

    top20 = champions.head(20).copy()
    top20["image"] = top20["champion_id"].map(imgs)
    # Считаем от половины, а не от нуля. Все значения лежат между 48% и 52%, и столбцы
    # от нуля выглядят одинаковыми: разницу в один пункт глазом не поймать.
    top20["dev"] = top20[order_col] - 0.5
    H = 560
    ysort = alt.EncodingSortField(field=order_col, op="max", order="descending")
    portraits = (
        alt.Chart(top20).mark_image(width=26, height=26)
        .encode(y=alt.Y("champion_name:N", sort=ysort, axis=None), url="image:N")
        .properties(width=30, height=H)
    )
    y_named = alt.Y("champion_name:N", sort=ysort, title=None,
                    axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
    bars = (
        alt.Chart(top20).mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("dev:Q", title="Выше или ниже половины побед",
                    axis=alt.Axis(format="+%", grid=True, domain=False, tickCount=7)),
            y=y_named,
            color=alt.Color(
                "verdict:N", title="Итог",
                scale=alt.Scale(
                    domain=["выигрывает чаще", "как все", "выигрывает реже"],
                    range=["#C8AA6E", "#6b7580", "#d9534f"],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=["champion_name", "primary_class", "games",
                     alt.Tooltip("winrate:Q", format=".1%", title="доля побед"),
                     alt.Tooltip("wilson_low:Q", format=".1%", title="осторожная оценка"),
                     alt.Tooltip("dev:Q", format="+.1%", title="от половины"),
                     "verdict"],
        )
        .properties(height=H)
    )
    half = (
        alt.Chart(pd.DataFrame({"z": [0]}))
        .mark_rule(color="#a49b86", strokeWidth=1)
        .encode(x=alt.X("z:Q"))
    )
    # Подпись ставим по ту сторону столбца, куда он растёт, иначе она ложится на бар.
    # Двумя слоями, а не условием: align в encode() эта версия Altair не принимает.
    def _labels(part: pd.DataFrame, align: str, dx: int) -> alt.Chart:
        return (
            alt.Chart(part).mark_text(align=align, dx=dx, fontSize=11, color="#cfd6d6")
            .encode(x=alt.X("dev:Q"), y=y_named,
                    text=alt.Text(f"{order_col}:Q", format=".1%"))
        )

    layers = [bars, half]
    above = top20[top20["dev"] >= 0]
    below = top20[top20["dev"] < 0]
    if not above.empty:
        layers.append(_labels(above, "left", 6))
    if not below.empty:
        layers.append(_labels(below, "right", -6))
    st.altair_chart(
        alt.hconcat(portraits, alt.layer(*layers), spacing=4).configure_view(strokeWidth=0),
        width="stretch")

    # ---------- эффект усреднения: ради этого три вкладки и слиты в одну ----------
    st.divider()
    st.markdown("#### Ответ зависит от того, как считать")
    st.caption(
        "В первой строке роли смешаны, в остальных разделены. Сравните два столбца: "
        "сколько чемпионов выделяется и какой между ними разброс."
    )
    example = role_gap_example(source, patch_filter, min_games)
    if example:
        big, small = int(example["best_games"]), int(example["worst_games"])
        st.caption(
            "Смешивать роли нельзя потому, что на разных позициях у одного и того же "
            "чемпиона разная работа: где-то он добывает золото и наносит урон, где-то "
            "прикрывает команду. Это фактически две разные игры, и сила в них тоже разная. "
            f"{example['champion_name']} "
            f"{ROLE_IN.get(example['best_role'], example['best_role'])} выигрывает "
            f"{example['best_wr']:.0%} матчей, а "
            f"{ROLE_IN.get(example['worst_role'], example['worst_role'])} всего "
            f"{example['worst_wr']:.0%}. Но на первой позиции сыграно "
            f"{big} {_plural(big, 'матч', 'матча', 'матчей')}, а на второй только "
            f"{small}. Общая доля побед считается по всем матчам сразу, поэтому она "
            f"тянется к большей группе и выходит {example['overall']:.0%} — "
            "и чемпион попадает в «как все». Так пропадают и сильные, и слабые."
        )
    else:
        st.caption(
            "Смешивать роли нельзя вот почему. Одного и того же чемпиона играют на разных "
            "позициях, и на одной он может выигрывать заметно чаще, чем на другой. Вместе "
            "эти доли сливаются в одну, близкую к половине, и чемпион попадает в «как все». "
            "Так пропадают и сильные, и слабые."
        )
    eff = aggregation_effect(source, patch_filter, min_games)
    if not eff.empty:
        order = [ALL_SLICE] + ROLES
        eff["_o"] = eff["slice"].apply(lambda s: order.index(s) if s in order else 99)
        eff = eff.sort_values("_o")
        eff["spread"] = eff["wr_max"] - eff["wr_min"]
        eff["significant"] = eff["strong"] + eff["weak"]
        eff["slice"] = eff["slice"].map(lambda s: ROLE_RU.get(s, s))
        # Столбец «Строгость планки» (z) убран: голое число вида 3.62 не читается
        # никем, включая автора. Механизм объяснён в свёрнутом блоке выше.
        # «Выделяются» тоже убран: он был просто суммой двух соседних столбцов,
        # а сами они схлопнуты в один — «чаще / реже».
        eff["pair"] = (eff["strong"].astype(int).astype(str) + " / "
                       + eff["weak"].astype(int).astype(str))
        show = eff.rename(columns={
            "slice": "Как считаем", "champions": "Чемпионов",
            "pair": "Чаще / реже", "spread": "Разброс побед",
        })[["Как считаем", "Чемпионов", "Чаще / реже", "Разброс побед"]]
        st.dataframe(
            show, hide_index=True, width="stretch",
            column_config={
                "Чемпионов": st.column_config.NumberColumn(
                    format="%d", help="Сколько чемпионов набрали нужный минимум игр"),
                "Чаще / реже": st.column_config.TextColumn(
                    help="Первое число — сколько чемпионов выигрывают заметно чаще "
                         "половины матчей, второе — сколько заметно реже"),
                "Разброс побед": st.column_config.NumberColumn(
                    format="percent",
                    help="На сколько процентных пунктов лучший чемпион опережает худшего "
                         "по доле побед"),
            },
        )

    # ---------- рейтинг таблицей ----------
    st.divider()
    st.markdown("#### Рейтинг чемпионов")
    st.caption(
        "«Побед» — сколько матчей чемпион выиграл на самом деле. «Осторожно» — та же доля, "
        "но заниженная с учётом числа игр: по ней и строится рейтинг, чтобы наверх "
        "не попадали чемпионы с парой удачных матчей. «Лучше в классе» показывает, насколько "
        "чемпион выигрывает чаще среднего по своему классу: танки сравниваются с танками, "
        "маги с магами."
    )
    top = champions.head(25).copy()
    top.insert(0, "img", top["champion_id"].map(imgs))
    st.dataframe(
        top[["rank", "img", "champion_name", "primary_class", "games",
             "winrate", "wilson_low", "vs_class", "avg_kda", "verdict"]],
        hide_index=True, width="stretch",
        column_config={
            "rank": st.column_config.NumberColumn("Ранг", format="%d"),
            "img": st.column_config.ImageColumn(" ", width="small"),
            "champion_name": "Чемпион",
            "primary_class": "Класс",
            "games": st.column_config.NumberColumn("Игр"),
            "winrate": st.column_config.ProgressColumn(
                "Побед", format="percent", min_value=0.40, max_value=0.60),
            "wilson_low": st.column_config.ProgressColumn(
                "Осторожно", format="percent", min_value=0.40, max_value=0.60,
                help="Доля побед, заниженная с учётом того, сколько игр сыграно"),
            "vs_class": st.column_config.NumberColumn(
                "Лучше в классе", format="%+.1f%%",
                help="Насколько чемпион выигрывает чаще среднего по своему классу"),
            "avg_kda": st.column_config.NumberColumn("KDA", format="%.2f"),
            "verdict": "Итог",
        },
    )
    _, dl = st.columns([4, 1])
    with dl:
        download_csv(champions, "champion_strength.csv", key="dl_strength",
                     use_container_width=True)

    _kills_deaths(source, pos_filter, patch_filter, min_games)
    _patch_shift(source, patches, pos_filter, min_games)
    _by_duration(source, pos_filter, patch_filter)


def _kills_deaths(source: str, pos_filter: str, patch_filter: str, min_games: int) -> None:
    st.divider()
    st.markdown("#### Убийства и смерти по чемпионам")
    st.caption(
        "Каждая точка — чемпион. Вправо растёт среднее число смертей за игру, вверх — "
        "убийств. Пунктирная линия — там, где убийств столько же, сколько смертей: "
        "чемпионы выше неё убивают чаще, чем гибнут. Зелёный цвет означает больше "
        "половины побед, красный — меньше. Размер точки — сколько матчей сыграно."
    )
    kd = run(f"""
        SELECT c.champion_name, c.primary_class, c.champion_id,
               COUNT(DISTINCT f.match_id) AS games,
               AVG(f.kills) AS avg_kills, AVG(f.deaths) AS avg_deaths,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
        WHERE f.data_source = '{source}' {pos_filter} {patch_filter}
        GROUP BY c.champion_name, c.primary_class, c.champion_id
        HAVING COUNT(DISTINCT f.match_id) >= {min_games}
    """)
    if kd.empty:
        return
    lim = float(max(kd["avg_deaths"].max(), kd["avg_kills"].max()))
    points = (
        alt.Chart(kd).mark_circle(opacity=0.65, stroke="#141719", strokeWidth=0.4)
        .encode(
            x=alt.X("avg_deaths:Q", title="Смертей за игру (в среднем)"),
            y=alt.Y("avg_kills:Q", title="Убийств за игру (в среднем)"),
            size=alt.Size("games:Q", title="Игр", scale=alt.Scale(range=[60, 900])),
            color=alt.Color("winrate:Q", title="Побед",
                            scale=alt.Scale(scheme="redyellowgreen", domain=[0.4, 0.6])),
            tooltip=["champion_name", "primary_class", "games",
                     alt.Tooltip("avg_kills:Q", format=".1f", title="убийств"),
                     alt.Tooltip("avg_deaths:Q", format=".1f", title="смертей"),
                     alt.Tooltip("winrate:Q", format=".0%")],
        )
    )
    ref = (alt.Chart(pd.DataFrame({"v": [0, lim]}))
           .mark_line(strokeDash=[4, 4], color="#6b7580")
           .encode(x="v:Q", y="v:Q"))
    # Без .interactive(): Altair вешает на колесо мыши зум, и широкий график
    # перехватывает прокрутку страницы — курсор над ним, и страница не листается
    # дальше. Подписи при наведении работают и без этого.
    st.altair_chart((points + ref).properties(height=420), width="stretch")


def _diverging_bars(df: pd.DataFrame, x_title: str, tooltips: list) -> alt.Chart:
    """Столбики отклонений: золотой вверх, красный вниз.

    Прозрачность различает три состояния, а не два. Средний уровень — те, что
    прошли бы обычную проверку, но не строгую: без него в тексте оставалось число,
    на которое нельзя показать пальцем.
    """
    part = pd.concat([df.head(12), df.tail(12)]).drop_duplicates(subset=["champion_name"])
    part = part.assign(op=part.apply(
        lambda r: 0.95 if r["is_sig"] else (0.55 if r["is_sig_naive"] else 0.20), axis=1))
    return (
        alt.Chart(part).mark_bar(cornerRadiusEnd=2)
        .encode(
            x=alt.X("delta:Q", title=x_title, axis=alt.Axis(format="+%")),
            y=alt.Y("champion_name:N", sort="-x", title=None),
            color=alt.condition("datum.delta > 0", alt.value("#C8AA6E"), alt.value("#d9534f")),
            opacity=alt.Opacity("op:Q", scale=None, legend=None),
            tooltip=tooltips,
        )
        .properties(height=520)
    )


def _patch_shift(source: str, patches: list[str], pos_filter: str, min_games: int) -> None:
    """Условие «патч А против патча Б» — бывшая вкладка «Мета»."""
    st.divider()
    st.markdown("#### Что изменилось между патчами")
    if len(patches) < 2:
        st.info(
            f"У источника «{source}» меньше двух патчей с данными. Переключите источник "
            "на **riot_full** — там 6 патчей (16.7–16.12)."
        )
        return

    c1, c2 = st.columns(2)
    a = c1.selectbox("Патч A", patches, index=len(patches) - 2, key="patch_a")
    b = c2.selectbox("Патч B", patches, index=len(patches) - 1, key="patch_b")
    a, b = sorted([a, b], key=lambda x: [int(n) for n in x.split(".")])
    if a == b:
        st.info("Выберите два разных патча.")
        return

    cmp = run(f"""
        WITH j AS (
            SELECT c.champion_name, c.primary_class, f.win, {PATCH_EXPR} AS patch
            FROM fact_participant f
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' {pos_filter}
              AND {PATCH_EXPR} IN ('{a}', '{b}')
        ),
        agg AS (
            SELECT champion_name, primary_class, patch, COUNT(*) AS games,
                   SUM(CASE WHEN win THEN 1 ELSE 0 END) AS wins,
                   AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
            FROM j GROUP BY 1, 2, 3
        )
        SELECT champion_name, primary_class,
               MAX(CASE WHEN patch = '{a}' THEN wr END) AS wr_a,
               MAX(CASE WHEN patch = '{b}' THEN wr END) AS wr_b,
               MAX(CASE WHEN patch = '{a}' THEN games END) AS g_a,
               MAX(CASE WHEN patch = '{b}' THEN games END) AS g_b,
               MAX(CASE WHEN patch = '{a}' THEN wins END) AS w_a,
               MAX(CASE WHEN patch = '{b}' THEN wins END) AS w_b
        FROM agg GROUP BY 1, 2
        HAVING MAX(CASE WHEN patch = '{a}' THEN games END) >= {min_games}
           AND MAX(CASE WHEN patch = '{b}' THEN games END) >= {min_games}
    """)
    if cmp.empty:
        st.info("Нет чемпионов с достаточной выборкой в обоих патчах. Снизьте минимум игр.")
        return

    cmp["delta"] = cmp["wr_b"] - cmp["wr_a"]
    cmp["p_value"] = cmp.apply(
        lambda r: two_proportion_pvalue(r["w_a"], r["g_a"], r["w_b"], r["g_b"]), axis=1)
    # Та же логика, что и в рейтинге выше: проверок столько, сколько чемпионов,
    # поэтому порог значимости делится на их число.
    alpha_adj = ALPHA / len(cmp)
    cmp["is_sig"] = cmp["p_value"] < alpha_adj
    cmp["is_sig_naive"] = cmp["p_value"] < ALPHA
    cmp = cmp.sort_values("delta", ascending=False)
    naive = int(cmp["is_sig_naive"].sum())
    sig = cmp[cmp["is_sig"]]

    st.caption(
        f"Riot регулярно правит чемпионов. Здесь видно, у кого доля побед между патчами "
        f"{a} и {b} изменилась по-настоящему, а у кого сдвинулась в пределах обычного "
        f"разброса. Золотой столбец — стал выигрывать чаще, красный — реже.\n\n"
        f"Насыщенные столбцы прошли строгую проверку, их {len(sig)}. Столбцы средней "
        f"яркости — те {naive}, что прошли бы обычную проверку по одному чемпиону, "
        f"но не выдержали строгую: чемпионов здесь {len(cmp)}, и планка поднята именно "
        f"из-за их количества. Самые бледные — обычный разброс."
    )
    # Один и тот же чемпион не может одновременно усилиться и ослабнуть: берём
    # лидеров отдельно среди выросших и среди упавших. Раньше при единственном
    # значимом чемпионе он попадал в обе половины фразы.
    ups = sig[sig["delta"] > 0]
    downs = sig[sig["delta"] < 0]
    parts = []
    if not ups.empty:
        r = ups.iloc[0]
        parts.append(f"**{r['champion_name']}** стал выигрывать на "
                     f"{r['delta']:.0%} чаще")
    if not downs.empty:
        r = downs.iloc[-1]
        parts.append(f"**{r['champion_name']}** — на {abs(r['delta']):.0%} реже")
    if parts:
        st.success(f"Между патчами {a} и {b} по-настоящему изменились: "
                   + ", ".join(parts) + ".")
    else:
        st.info(
            f"Между патчами {a} и {b} ни у кого нет изменений, которые нельзя объяснить "
            "случайностью. Цифры у чемпионов поменялись, но в пределах обычного разброса."
        )
    st.altair_chart(
        _diverging_bars(cmp, f"Δ winrate ({b} − {a})",
                        ["champion_name", "primary_class",
                         alt.Tooltip("wr_a:Q", format=".1%", title=a),
                         alt.Tooltip("wr_b:Q", format=".1%", title=b),
                         alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
                         alt.Tooltip("p_value:Q", format=".4f", title="p-значение")]),
        width="stretch")
    _, dl = st.columns([4, 1])
    with dl:
        download_csv(cmp, "patch_comparison.csv", key="dl_patch", use_container_width=True)


def _duration_groups(source: str, patch_filter: str) -> None:
    """Сколько матчей в каждой группе по длине: где границы «коротких» и «длинных»."""
    dur = run(f"""
        SELECT FLOOR(m.game_duration_min) AS minute, COUNT(*) AS matches,
               CASE WHEN m.game_duration_min < {SHORT_MAX} THEN 'Короткие'
                    WHEN m.game_duration_min < {LONG_MIN} THEN 'Средние'
                    ELSE 'Длинные' END AS grp
        FROM dim_match m
        WHERE m.data_source = '{source}' AND m.game_duration_min IS NOT NULL {patch_filter}
        GROUP BY 1, 3
    """)
    if dur.empty:
        return
    share = dur.groupby("grp")["matches"].sum() / dur["matches"].sum()
    order = ["Короткие", "Средние", "Длинные"]
    labels = {"Короткие": f"Короткие, до {SHORT_MAX} мин",
              "Средние": f"Средние, {SHORT_MAX}–{LONG_MIN} мин",
              "Длинные": f"Длинные, от {LONG_MIN} мин"}
    dur["grp_label"] = dur["grp"].map(labels)
    top = int(dur["minute"].max() // 5 + 1) * 5
    domain = [labels[g] for g in order]
    hist = (
        alt.Chart(dur)
        .mark_bar(width={"band": 0.9})
        .encode(
            x=alt.X("minute:Q", title="Длительность матча, мин",
                    scale=alt.Scale(domain=[0, top]),
                    axis=alt.Axis(values=list(range(0, top + 1, 5)))),
            y=alt.Y("matches:Q", title="Матчей", axis=alt.Axis(format="d")),
            color=alt.Color("grp_label:N", title=None, sort=domain,
                            scale=alt.Scale(domain=domain,
                                            range=["#5aa0c9", "#C8AA6E", "#b5654a"]),
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("minute:Q", title="минута"),
                     alt.Tooltip("matches:Q", title="матчей")],
        )
        .properties(height=200)
    )
    st.altair_chart(hist, width="stretch")
    st.caption(
        f"Сравниваем короткие и длинные матчи, средние в сравнение не входят. Коротких "
        f"{share.get('Короткие', 0):.0%}, средних {share.get('Средние', 0):.0%}, длинных "
        f"{share.get('Длинные', 0):.0%}. Всплеск на 15-й минуте — сдачи: раньше сдаться "
        "в игре нельзя, и проигрывающая команда часто сдаётся, как только это становится "
        "возможным."
    )


def _by_duration(source: str, pos_filter: str, patch_filter: str) -> None:
    """Условие «длина матча» — бывшая вкладка «Длительность»."""
    st.divider()
    st.markdown("#### Кто сильнее в долгих играх, а кто в коротких")
    st.warning(
        "**Этот разрез описывает, но не объясняет.** Часть чемпионов набирает силу "
        "к концу матча: в начале они слабые, зато под конец становятся опаснее всех. "
        "Проблема в том, что матч заканчивается быстро, когда одна команда разносит "
        "другую. Значит короткие матчи — это в основном разгромы, и все проигрыши таких "
        "чемпионов попадают в них сами собой, ещё до того, как те успели усилиться. "
        "Поэтому из графика видно, кому долгая игра на руку, но не видно, что здесь "
        "причина, а что следствие: возможно, игра затянулась именно потому, что такой "
        "чемпион не дал её закончить.",
        icon="⚠️",
    )
    _duration_groups(source, patch_filter)
    min_b = st.slider("Минимум игр в каждой длине", 5, 100, 30, step=5, key="dur_min")

    dur = run(f"""
        WITH j AS (
            SELECT c.champion_name, f.win,
                   CASE WHEN m.game_duration_min < {SHORT_MAX} THEN 'short'
                        WHEN m.game_duration_min < {LONG_MIN} THEN 'mid'
                        ELSE 'long' END AS bucket
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}' {pos_filter} {patch_filter}
        ),
        agg AS (
            SELECT champion_name, bucket, COUNT(*) AS games,
                   SUM(CASE WHEN win THEN 1 ELSE 0 END) AS wins,
                   AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
            FROM j GROUP BY 1, 2
        )
        SELECT champion_name,
               MAX(CASE WHEN bucket = 'short' THEN wr END) AS wr_short,
               MAX(CASE WHEN bucket = 'long'  THEN wr END) AS wr_long,
               MAX(CASE WHEN bucket = 'short' THEN games END) AS g_short,
               MAX(CASE WHEN bucket = 'long'  THEN games END) AS g_long,
               MAX(CASE WHEN bucket = 'short' THEN wins END) AS w_short,
               MAX(CASE WHEN bucket = 'long'  THEN wins END) AS w_long
        FROM agg GROUP BY 1
        HAVING MAX(CASE WHEN bucket = 'short' THEN games END) >= {min_b}
           AND MAX(CASE WHEN bucket = 'long'  THEN games END) >= {min_b}
    """)
    if dur.empty:
        st.info("Мало данных при таком пороге. Снизьте минимум игр.")
        return

    dur["delta"] = dur["wr_long"] - dur["wr_short"]
    dur["p_value"] = dur.apply(
        lambda r: two_proportion_pvalue(r["w_short"], r["g_short"], r["w_long"], r["g_long"]),
        axis=1)
    alpha_adj = ALPHA / len(dur)
    dur["is_sig"] = dur["p_value"] < alpha_adj
    dur["is_sig_naive"] = dur["p_value"] < ALPHA
    dur = dur.sort_values("delta", ascending=False)
    sig = dur[dur["is_sig"]]
    naive = int(dur["is_sig_naive"].sum())

    st.caption(
        f"Насколько чаще чемпион побеждает в долгих матчах (от {LONG_MIN} минут) по "
        f"сравнению с короткими (до {SHORT_MAX} минут).\n\n"
        f"Насыщенные столбцы прошли строгую проверку, их {len(sig)}. Столбцы средней "
        f"яркости — те {naive}, что прошли бы обычную проверку по одному чемпиону, "
        f"но не выдержали строгую: чемпионов здесь {len(dur)}, и планка поднята именно "
        f"из-за их количества. Самые бледные — обычный разброс."
    )
    if not sig.empty:
        top = sig.iloc[0]
        st.success(
            f"Больше всех выигрывает от долгой игры **{top['champion_name']}**: "
            f"{top['wr_short']:.0%} побед в коротких матчах против {top['wr_long']:.0%} "
            f"в долгих."
        )
    st.altair_chart(
        _diverging_bars(dur, "Δ winrate (длинные − короткие)",
                        ["champion_name",
                         alt.Tooltip("wr_short:Q", format=".1%", title="короткие"),
                         alt.Tooltip("wr_long:Q", format=".1%", title="длинные"),
                         alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
                         alt.Tooltip("p_value:Q", format=".4f", title="p-значение")]),
        width="stretch")
    _, dl = st.columns([4, 1])
    with dl:
        download_csv(dur, "champion_by_duration.csv", key="dl_dur", use_container_width=True)
