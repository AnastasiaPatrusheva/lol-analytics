"""Вкладка «Чемпионы»: топ по Уилсону, scatter убийства/смерти, аномалии меты."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, download_csv, POSITIONS


def render(source: str) -> None:
    col_a, col_b, col_c = st.columns([1, 1.4, 1.4])
    position = col_a.selectbox("Позиция", POSITIONS)
    rank_by = col_b.radio(
        "Ранжировать по", ["С поправкой на число игр", "Сырой winrate"], horizontal=True,
        help="Метод Уилсона строит доверительный интервал winrate с учётом числа игр: "
             "чем меньше выборка, тем осторожнее оценка. Ранжируем по нижней границе интервала — "
             "чтобы 70% на 5 играх не оказались выше 53% на 500.",
    )
    min_games = col_c.slider("Минимум игр", 5, 100, 30, step=5)

    pos_filter = "" if position == "Все" else f"AND f.role_key = '{position}'"
    order_col = "wilson_low" if rank_by.startswith("С поправкой") else "winrate"

    champions = run(f"""
        WITH base AS (
            SELECT c.champion_name, c.primary_class,
                   COUNT(DISTINCT f.match_id) AS games,
                   SUM(CASE WHEN f.win THEN 1 ELSE 0 END) AS wins,
                   AVG(f.kda) AS avg_kda
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' {pos_filter}
            GROUP BY c.champion_name, c.primary_class
            HAVING COUNT(DISTINCT f.match_id) >= {min_games}
        ),
        ci AS (
            SELECT *, wins * 1.0 / games AS winrate,
                   wilson_low(wins * 1.0 / games, games) AS wilson_low,
                   wilson_high(wins * 1.0 / games, games) AS wilson_high
            FROM base
        )
        SELECT champion_name, primary_class, games, winrate, wilson_low, wilson_high, avg_kda,
               CASE WHEN wilson_low > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
        FROM ci ORDER BY {order_col} DESC
    """)

    metric_title = "Winrate (с поправкой на число игр)" if order_col == "wilson_low" else "Winrate"
    st.subheader(f"Топ чемпионов ({position})")
    st.caption(
        "Цвет столбца = значимость: зелёный — значимо сильный (весь интервал уверенности выше 50%), "
        "красный — значимо слабый, серый — в норме (высокий % может быть просто шумом малой выборки)."
    )
    if champions.empty:
        st.info("Нет чемпионов с таким порогом игр. Снизьте минимум игр.")
        return

    strong = champions[champions["verdict"].str.contains("значимо сильный")]
    if not strong.empty:
        t = strong.iloc[0]
        st.success(
            f"🏆 Сильнейший (значимо): **{t['champion_name']}** — winrate "
            f"{t['wilson_low']:.0%} с поправкой на число игр ({int(t['games'])} игр). "
            f"Статистически доказанных сильных всего {len(strong)}."
        )
    chart = (
        alt.Chart(champions.head(20))
        .mark_bar()
        .encode(
            x=alt.X(f"{order_col}:Q", title=metric_title, axis=alt.Axis(format="%")),
            y=alt.Y("champion_name:N", sort="-x", title=None),
            color=alt.Color(
                "verdict:N", title="Вердикт",
                scale=alt.Scale(
                    domain=["значимо сильный", "в норме", "значимо слабый"],
                    range=["#3fa45b", "#9aa0a6", "#d9534f"],
                ),
            ),
            tooltip=[
                "champion_name", "primary_class", "games",
                alt.Tooltip("winrate:Q", format=".1%", title="winrate"),
                alt.Tooltip("wilson_low:Q", format=".1%", title="Уилсон ниж."),
                "verdict",
            ],
        )
        .properties(height=480)
    )
    st.altair_chart(chart, width="stretch")
    download_csv(champions, "champions.csv", key="dl_champions")

    st.markdown("#### Убийства vs смерти по чемпионам")
    st.caption(
        "Каждая точка — чемпион: по горизонтали среднее число смертей за игру, по вертикали — "
        "убийств. Пунктирная диагональ — где убийств столько же, сколько смертей: выше линии = "
        "больше убийств. Цвет: зеленее — winrate выше 50%, краснее — ниже."
    )
    kd = run(f"""
        SELECT c.champion_name, c.primary_class,
               COUNT(DISTINCT f.match_id) AS games,
               AVG(f.kills) AS avg_kills,
               AVG(f.deaths) AS avg_deaths,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        WHERE f.data_source = '{source}' {pos_filter}
        GROUP BY c.champion_name, c.primary_class
        HAVING COUNT(DISTINCT f.match_id) >= {min_games}
    """)
    lim = float(max(kd["avg_deaths"].max(), kd["avg_kills"].max())) if not kd.empty else 10.0
    points = (
        alt.Chart(kd)
        .mark_circle(opacity=0.6)
        .encode(
            x=alt.X("avg_deaths:Q", title="Смертей за игру (в среднем)"),
            y=alt.Y("avg_kills:Q", title="Убийств за игру (в среднем)"),
            size=alt.Size("games:Q", title="Игр"),
            color=alt.Color("winrate:Q", title="Winrate",
                            scale=alt.Scale(scheme="redyellowgreen", domain=[0.4, 0.6])),
            tooltip=["champion_name", "primary_class", "games",
                     alt.Tooltip("avg_kills:Q", format=".1f", title="убийств"),
                     alt.Tooltip("avg_deaths:Q", format=".1f", title="смертей"),
                     alt.Tooltip("winrate:Q", format=".0%")],
        )
    )
    # Диагональ убийства = смерти: точки выше линии — больше убийств, чем смертей.
    ref = (
        alt.Chart(pd.DataFrame({"v": [0, lim]}))
        .mark_line(strokeDash=[4, 4], color="#888")
        .encode(x="v:Q", y="v:Q")
    )
    st.altair_chart((points + ref).properties(height=380).interactive(), width="stretch")

    anomalies = champions[champions["verdict"].str.contains("значимо")]
    with st.expander(f"🔎 Аномалии меты: {len(anomalies)} чемпионов со значимым отклонением от 50%"):
        verdict_colors = {"значимо сильный": "#3fa45b", "значимо слабый": "#d9534f"}
        disp = anomalies.rename(columns={
            "champion_name": "Чемпион", "primary_class": "Класс", "games": "Игр",
            "winrate": "Winrate", "wilson_low": "Ниж. оценка", "wilson_high": "Верх. оценка",
            "avg_kda": "KDA", "verdict": "Вердикт",
        })
        styled = (
            disp.style
            .format({"Winrate": "{:.1%}", "Ниж. оценка": "{:.1%}",
                     "Верх. оценка": "{:.1%}", "KDA": "{:.2f}"})
            .apply(
                lambda col: [f"color: {verdict_colors.get(v, '#9aa0a6')}; font-weight: 600"
                             for v in col],
                subset=["Вердикт"],
            )
        )
        st.dataframe(styled, width="stretch", hide_index=True)
