"""Вкладка «Чемпионы»: топ по Уилсону, scatter убийства/смерти, аномалии меты."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, download_csv, champion_images, POSITIONS


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
            SELECT c.champion_name, c.primary_class, c.champion_id,
                   COUNT(DISTINCT f.match_id) AS games,
                   SUM(CASE WHEN f.win THEN 1 ELSE 0 END) AS wins,
                   AVG(f.kda) AS avg_kda
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' {pos_filter}
            GROUP BY c.champion_name, c.primary_class, c.champion_id
            HAVING COUNT(DISTINCT f.match_id) >= {min_games}
        ),
        ci AS (
            SELECT *, wins * 1.0 / games AS winrate,
                   wilson_low(wins * 1.0 / games, games) AS wilson_low,
                   wilson_high(wins * 1.0 / games, games) AS wilson_high
            FROM base
        )
        SELECT champion_name, primary_class, champion_id, games, winrate, wilson_low, wilson_high, avg_kda,
               RANK() OVER (ORDER BY {order_col} DESC) AS rank,
               (winrate - AVG(winrate) OVER (PARTITION BY primary_class)) * 100 AS vs_class,
               CASE WHEN wilson_low > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
        FROM ci ORDER BY {order_col} DESC
    """)

    metric_title = "Winrate (с поправкой на число игр)" if order_col == "wilson_low" else "Winrate"
    st.subheader(f"Топ чемпионов ({position})")
    st.caption(
        "Цвет столбца = значимость: золотой — значимо сильный (весь интервал уверенности выше 50%), "
        "красный — значимо слабый, серый — в норме (высокий % может быть просто шумом малой выборки)."
    )
    if champions.empty:
        st.info("Нет чемпионов с таким порогом игр. Снизьте минимум игр.")
        return

    imgs = champion_images()

    def hero(title, row, value, accent="#C8AA6E"):
        img = imgs.get(int(row["champion_id"]), "")
        pic = (f"<img src='{img}' style='width:56px;height:56px;border-radius:10px;"
               f"border:1px solid #2f3a4d;flex:none'>") if img else ""
        return (
            "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:14px;"
            "padding:13px 15px;display:flex;gap:12px;align-items:center'>"
            f"{pic}<div style='min-width:0'>"
            f"<div style='font-size:11px;color:#a49b86;text-transform:uppercase;letter-spacing:.05em'>{title}</div>"
            "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:19px;"
            f"font-weight:600;color:#e8ecec\">{row['champion_name']}</div>"
            f"<div style='font-size:13px;color:{accent}'>{value}</div>"
            "</div></div>"
        )

    most_played = champions.loc[champions["games"].idxmax()]
    best_kda = champions.loc[champions["avg_kda"].idxmax()]
    top_row = champions.iloc[0]
    h1, h2, h3 = st.columns(3)
    h1.markdown(hero("Сильнейший по рейтингу", top_row,
                     f"{top_row[order_col]:.1%} · {int(top_row['games'])} игр"),
                unsafe_allow_html=True)
    h2.markdown(hero("Самый играемый", most_played,
                     f"{int(most_played['games'])} игр · WR {most_played['winrate']:.0%}",
                     accent="#5aa0c9"), unsafe_allow_html=True)
    h3.markdown(hero("Лучший KDA", best_kda, f"KDA {best_kda['avg_kda']:.2f}",
                     accent="#cda24a"), unsafe_allow_html=True)
    st.write("")

    strong = champions[champions["verdict"].str.contains("значимо сильный")]
    if not strong.empty:
        st.caption(f"Статистически доказанных сильных (весь интервал выше 50%): {len(strong)}.")
    top20 = champions.head(20).copy()
    top20["image"] = top20["champion_id"].map(imgs)
    H = 560
    ysort = alt.EncodingSortField(field=order_col, op="max", order="descending")
    # Узкий столбец портретов слева (строки выровнены по той же сортировке).
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
            tooltip=[
                "champion_name", "primary_class", "games",
                alt.Tooltip("winrate:Q", format=".1%", title="winrate"),
                alt.Tooltip("wilson_low:Q", format=".1%", title="Уилсон ниж."),
                "verdict",
            ],
        )
        .properties(height=H)
    )
    # Значение winrate у конца бара — не нужно водить глазом к оси.
    vals = (
        alt.Chart(top20).mark_text(align="left", dx=6, fontSize=11, color="#cfd6d6")
        .encode(x=alt.X(f"{order_col}:Q"), y=y_named,
                text=alt.Text(f"{order_col}:Q", format=".1%"))
    )
    chart = alt.hconcat(portraits, (bars + vals), spacing=4).configure_view(strokeWidth=0)
    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### Рейтинг чемпионов")
    st.caption(
        "«Ранг» — место чемпиона в общем рейтинге. «vs класс» — на сколько процентных "
        "пунктов его winrate выше или ниже среднего по своему классу (танки сравниваются "
        "с танками, маги с магами)."
    )
    top = champions.head(25).copy()
    top.insert(0, "img", top["champion_id"].map(imgs))
    show = top[["rank", "img", "champion_name", "primary_class", "games",
                "winrate", "wilson_low", "vs_class", "avg_kda", "verdict"]]
    st.dataframe(
        show, hide_index=True, width="stretch",
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

    st.markdown("#### Убийства vs смерти по чемпионам")
    st.caption(
        "Каждая точка — чемпион: по горизонтали среднее число смертей за игру, по вертикали — "
        "убийств. Пунктирная диагональ — где убийств столько же, сколько смертей: выше линии = "
        "больше убийств. Цвет: зеленее — winrate выше 50%, краснее — ниже."
    )
    kd = run(f"""
        SELECT c.champion_name, c.primary_class, c.champion_id,
               COUNT(DISTINCT f.match_id) AS games,
               AVG(f.kills) AS avg_kills,
               AVG(f.deaths) AS avg_deaths,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        WHERE f.data_source = '{source}' {pos_filter}
        GROUP BY c.champion_name, c.primary_class, c.champion_id
        HAVING COUNT(DISTINCT f.match_id) >= {min_games}
    """)
    lim = float(max(kd["avg_deaths"].max(), kd["avg_kills"].max())) if not kd.empty else 10.0
    points = (
        alt.Chart(kd)
        .mark_circle(opacity=0.65, stroke="#141719", strokeWidth=0.4)
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
    # Диагональ убийства = смерти: точки выше линии — больше убийств, чем смертей.
    ref = (
        alt.Chart(pd.DataFrame({"v": [0, lim]}))
        .mark_line(strokeDash=[4, 4], color="#6b7580")
        .encode(x="v:Q", y="v:Q")
    )
    st.altair_chart((points + ref).properties(height=420).interactive(), width="stretch")

    anomalies = champions[champions["verdict"].str.contains("значимо")]
    with st.expander(f"Аномалии меты: {len(anomalies)} чемпионов со значимым отклонением от 50%"):
        _, dl_col = st.columns([4, 1])
        with dl_col:
            download_csv(champions, "champions.csv", key="dl_champions", use_container_width=True)
        verdict_colors = {"значимо сильный": "#C8AA6E", "значимо слабый": "#d9534f"}
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
