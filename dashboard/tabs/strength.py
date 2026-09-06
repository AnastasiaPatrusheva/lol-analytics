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


def _aggregation_effect(source: str, patch_filter: str, min_games: int) -> pd.DataFrame:
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
        "Один вопрос: отличается ли winrate чемпиона от 50%. Условия можно менять "
        "(роль, патч, длина матча), но проверка везде одна и та же."
    )

    patches = _patches(source)
    c1, c2, c3, c4 = st.columns([1, 1, 1.5, 1.3])
    position = c1.selectbox("Позиция", POSITIONS,
                            format_func=lambda p: ROLE_RU.get(p, p))
    patch = c2.selectbox("Патч", ["Все патчи"] + patches) if patches else "Все патчи"
    min_games = c3.slider("Минимум игр", 5, 100, 30, step=5)
    rank_by = c4.radio(
        "Ранжировать по", ["С поправкой на число игр", "Сырой winrate"],
        help="Метод Уилсона строит доверительный интервал winrate с учётом числа игр: "
             "чем меньше выборка, тем осторожнее оценка. Ранжируем по нижней границе, "
             "чтобы 70% на 5 играх не оказались выше 53% на 500.",
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
               CASE WHEN wilson_low_adj > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high_adj < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
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
    h2.markdown(_hero("Самый играемый", most_played["champion_name"],
                      f"{int(most_played['games'])} игр · WR {most_played['winrate']:.0%}",
                      imgs.get(int(most_played["champion_id"]), ""), accent="#5aa0c9"),
                unsafe_allow_html=True)
    h3.markdown(_hero("Лучший KDA", best_kda["champion_name"],
                      f"KDA {best_kda['avg_kda']:.2f}",
                      imgs.get(int(best_kda["champion_id"]), ""), accent="#cda24a"),
                unsafe_allow_html=True)
    st.caption(
        "KDA считается как сумма убийств и помощей, делённая на сумму смертей по всем "
        "матчам чемпиона. Если усреднять KDA отдельных матчей, редкие игры без смертей "
        "дают огромные значения и наверх выходят чемпионы с везучей серией."
    )
    st.write("")

    n_strong = int((champions["verdict"] == "значимо сильный").sum())
    n_weak = int((champions["verdict"] == "значимо слабый").sum())
    st.caption(
        f"Значимо отличаются от 50%: {n_strong + n_weak} из {n_tests} "
        f"({n_strong} сильных, {n_weak} слабых). Проверка идёт по всем чемпионам среза "
        f"сразу, поэтому порог поднят поправкой Бонферрони: z={z_adj:.2f} вместо 1.96. "
        "Без неё примерно каждый двадцатый получил бы ярлык случайно."
    )

    top20 = champions.head(20).copy()
    top20["image"] = top20["champion_id"].map(imgs)
    H = 560
    ysort = alt.EncodingSortField(field=order_col, op="max", order="descending")
    portraits = (
        alt.Chart(top20).mark_image(width=26, height=26)
        .encode(y=alt.Y("champion_name:N", sort=ysort, axis=None), url="image:N")
        .properties(width=30, height=H)
    )
    y_named = alt.Y("champion_name:N", sort=ysort, title=None,
                    axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
    metric_title = ("Winrate (с поправкой на число игр)" if order_col == "wilson_low"
                    else "Winrate")
    bars = (
        alt.Chart(top20).mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X(f"{order_col}:Q", title=metric_title,
                    axis=alt.Axis(format="%", grid=True, domain=False, tickCount=6)),
            y=y_named,
            color=alt.Color(
                "verdict:N", title="Вердикт",
                scale=alt.Scale(
                    domain=["значимо сильный", "в норме", "значимо слабый"],
                    range=["#C8AA6E", "#6b7580", "#d9534f"],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=["champion_name", "primary_class", "games",
                     alt.Tooltip("winrate:Q", format=".1%", title="winrate"),
                     alt.Tooltip("wilson_low:Q", format=".1%", title="Уилсон ниж."),
                     "verdict"],
        )
        .properties(height=H)
    )
    vals = (
        alt.Chart(top20).mark_text(align="left", dx=6, fontSize=11, color="#cfd6d6")
        .encode(x=alt.X(f"{order_col}:Q"), y=y_named,
                text=alt.Text(f"{order_col}:Q", format=".1%"))
    )
    st.altair_chart(
        alt.hconcat(portraits, (bars + vals), spacing=4).configure_view(strokeWidth=0),
        width="stretch")

    # ---------- эффект усреднения: ради этого три вкладки и слиты в одну ----------
    st.divider()
    st.markdown("#### Что делает с ответом сам разрез")
    st.caption(
        "Одна и та же проверка в разных разрезах. Обратите внимание на первую строку "
        "и на остальные: чемпион, которого играют на двух ролях с 38% и 52%, в сумме даёт "
        "ровно 50% и выглядит сбалансированным. Поэтому в общем срезе значимых обычно нет, "
        "а внутри роли они появляются. Ноль сверху — следствие усреднения, а не свойство игры."
    )
    eff = _aggregation_effect(source, patch_filter, min_games)
    if not eff.empty:
        order = [ALL_SLICE] + ROLES
        eff["_o"] = eff["slice"].apply(lambda s: order.index(s) if s in order else 99)
        eff = eff.sort_values("_o")
        eff["spread"] = eff["wr_max"] - eff["wr_min"]
        eff["significant"] = eff["strong"] + eff["weak"]
        eff["slice"] = eff["slice"].map(lambda s: ROLE_RU.get(s, s))
        show = eff.rename(columns={
            "slice": "Разрез", "champions": "Чемпионов", "significant": "Значимых",
            "strong": "Сильных", "weak": "Слабых", "spread": "Размах winrate", "z": "Порог z",
        })[["Разрез", "Чемпионов", "Значимых", "Сильных", "Слабых", "Размах winrate", "Порог z"]]
        st.dataframe(
            show, hide_index=True, width="stretch",
            column_config={
                "Чемпионов": st.column_config.NumberColumn(format="%d"),
                "Значимых": st.column_config.NumberColumn(format="%d"),
                "Сильных": st.column_config.NumberColumn(format="%d"),
                "Слабых": st.column_config.NumberColumn(format="%d"),
                "Размах winrate": st.column_config.NumberColumn(format="percent"),
                "Порог z": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    # ---------- рейтинг таблицей ----------
    st.divider()
    st.markdown("#### Рейтинг чемпионов")
    st.caption(
        "«Ранг» — место чемпиона в рейтинге этого среза. «vs класс» — на сколько процентных "
        "пунктов его winrate выше или ниже среднего по своему классу: танки сравниваются "
        "с танками, маги с магами."
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
                "Winrate", format="percent", min_value=0.40, max_value=0.60),
            "wilson_low": st.column_config.ProgressColumn(
                "Ниж. оценка", format="percent", min_value=0.40, max_value=0.60),
            "vs_class": st.column_config.NumberColumn("vs класс", format="%+.1f%%"),
            "avg_kda": st.column_config.NumberColumn("KDA", format="%.2f"),
            "verdict": "Вердикт",
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
    st.markdown("#### Убийства vs смерти по чемпионам")
    st.caption(
        "Каждая точка — чемпион: по горизонтали среднее число смертей за игру, по вертикали — "
        "убийств. Пунктирная диагональ — где убийств столько же, сколько смертей: выше линии = "
        "больше убийств. Цвет: зеленее — winrate выше 50%, краснее — ниже."
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
            color=alt.Color("winrate:Q", title="Winrate",
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
    """Столбики отклонений: золотой вверх, красный вниз, незначимые блёклые."""
    part = pd.concat([df.head(12), df.tail(12)]).drop_duplicates(subset=["champion_name"])
    return (
        alt.Chart(part).mark_bar(cornerRadiusEnd=2)
        .encode(
            x=alt.X("delta:Q", title=x_title, axis=alt.Axis(format="+%")),
            y=alt.Y("champion_name:N", sort="-x", title=None),
            color=alt.condition("datum.delta > 0", alt.value("#C8AA6E"), alt.value("#d9534f")),
            opacity=alt.condition("datum.is_sig", alt.value(0.95), alt.value(0.28)),
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
            "на **riot_full** — там 7 патчей (16.7–16.12)."
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
    cmp = cmp.sort_values("delta", ascending=False)
    naive = int((cmp["p_value"] < ALPHA).sum())
    sig = cmp[cmp["is_sig"]]

    st.caption(
        f"Сравниваем winrate от раннего патча ({a}) к позднему ({b}); порядок выбора не важен. "
        f"Проверяется {len(cmp)} чемпионов сразу, поэтому порог значимости не 0.05, "
        f"а {alpha_adj:.5f}. При обычном пороге «значимыми» выглядели бы {naive}, "
        f"с поправкой их {len(sig)}. Золотой — усилился, красный — ослаб, блёклый — шум."
    )
    if not sig.empty:
        up, down = sig.iloc[0], sig.iloc[-1]
        st.success(
            f"Значимые сдвиги {a} → {b}: усилился **{up['champion_name']}** "
            f"({up['delta']:+.0%}, p={up['p_value']:.4f}); ослаб "
            f"**{down['champion_name']}** ({down['delta']:+.0%}, p={down['p_value']:.4f})."
        )
    else:
        st.info(
            f"Между {a} и {b} нет сдвигов, переживающих поправку на множественные "
            "сравнения. Изменения в пределах шума выборки."
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


def _by_duration(source: str, pos_filter: str, patch_filter: str) -> None:
    """Условие «длина матча» — бывшая вкладка «Длительность»."""
    st.divider()
    st.markdown("#### Кто сильнее в долгих играх, а кто в коротких")
    st.warning(
        "**Длина матча — следствие исхода, а не фактор.** Разгромные матчи заканчиваются "
        "быстро, поэтому поражения «скейлеров» механически попадают в короткий бакет. "
        "Разрез полезен как описание, но причину «чемпион силён потому, что игра долгая» "
        "из него вывести нельзя: возможно, игра долгая потому, что чемпион не дал её закончить.",
        icon="⚠️",
    )
    min_b = st.slider("Минимум игр в каждой длине", 5, 100, 30, step=5, key="dur_min")

    dur = run(f"""
        WITH j AS (
            SELECT c.champion_name, f.win,
                   CASE WHEN m.game_duration_min < 25 THEN 'short'
                        WHEN m.game_duration_min < 32 THEN 'mid'
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
    dur = dur.sort_values("delta", ascending=False)
    sig = dur[dur["is_sig"]]

    st.caption(
        f"Разница winrate между долгими (>32 мин) и короткими (<25 мин) матчами. "
        f"Проверка та же, что и в разрезах выше: {len(dur)} чемпионов сразу, порог "
        f"{alpha_adj:.5f}. Значимых различий: {len(sig)}. Насыщенные столбцы — значимые, "
        "блёклые — в пределах шума."
    )
    if not sig.empty:
        top = sig.iloc[0]
        st.success(
            f"Сильнее всех выигрывает от долгой игры **{top['champion_name']}**: "
            f"{top['wr_short']:.0%} в коротких против {top['wr_long']:.0%} в долгих "
            f"({top['delta']:+.0%}, p={top['p_value']:.4f})."
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
