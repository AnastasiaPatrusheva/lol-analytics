"""Вкладка «Длительность»: размах длительности матчей и «скейл» чемпионов."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, table_with_download


def render(source: str) -> None:
    st.subheader("Длительность матчей")
    dur = run(f"""
        SELECT game_duration_min FROM dim_match
        WHERE data_source = '{source}' AND game_duration_min IS NOT NULL
    """)
    if not dur.empty:
        box = (
            alt.Chart(dur)
            .mark_boxplot(extent="min-max", size=40, color="#3fa45b")
            .encode(x=alt.X("game_duration_min:Q", title="Длительность матча, мин"))
            .properties(height=140)
        )
        st.altair_chart(box, width="stretch")
        q1 = dur["game_duration_min"].quantile(0.25)
        q3 = dur["game_duration_min"].quantile(0.75)
        med = dur["game_duration_min"].median()
        st.caption(
            f"Половина матчей длится примерно {q1:.0f}–{q3:.0f} мин (медиана {med:.0f}). "
            "«Коробка» — где лежит середина матчей, «усы» — общий разброс."
        )
    st.divider()

    min_b = st.slider("Минимум игр в каждой длине (короткие и длинные)", 5, 50, 15, step=5)
    st.subheader("Кто сильнее в долгих играх, а кто в коротких")
    st.caption(
        "Разница winrate между долгими (>32 мин) и короткими (<25 мин) матчами. "
        "Зелёный (плюс) — чемпион сильнее в долгой игре, красный (минус) — в короткой."
    )

    scaling = run(f"""
        WITH b AS (
            SELECT c.champion_name,
                   CASE WHEN m.game_duration_min < 25 THEN 'short'
                        WHEN m.game_duration_min < 32 THEN 'mid'
                        ELSE 'long' END AS bucket,
                   COUNT(*) AS games,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS wr
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}'
            GROUP BY c.champion_name, bucket
        ),
        piv AS (
            SELECT champion_name,
                   MAX(CASE WHEN bucket = 'short' THEN wr END) AS wr_short,
                   MAX(CASE WHEN bucket = 'long' THEN wr END) AS wr_long,
                   MAX(CASE WHEN bucket = 'short' THEN games END) AS g_short,
                   MAX(CASE WHEN bucket = 'long' THEN games END) AS g_long
            FROM b GROUP BY champion_name
        )
        SELECT champion_name, wr_short, wr_long,
               (wr_long - wr_short) AS delta, g_short, g_long
        FROM piv
        WHERE g_short >= {min_b} AND g_long >= {min_b}
        ORDER BY delta DESC
    """)

    if scaling.empty:
        st.info("Мало данных при таком пороге. Снизьте минимум игр.")
        return

    top_s = scaling.iloc[0]
    bot_s = scaling.iloc[-1]
    st.success(
        f"📈 Больше всех выигрывает от долгой игры — **{top_s['champion_name']}** "
        f"(+{top_s['delta']:.0%} winrate); а **{bot_s['champion_name']}** наоборот сильнее "
        f"в короткой ({bot_s['delta']:+.0%} в долгой)."
    )
    diverging = pd.concat([scaling.head(12), scaling.tail(12)])
    chart = (
        alt.Chart(diverging)
        .mark_bar()
        .encode(
            x=alt.X("delta:Q", title="Δ winrate (длинные − короткие)",
                    axis=alt.Axis(format="+%")),
            y=alt.Y("champion_name:N", sort="-x", title=None),
            color=alt.condition("datum.delta > 0", alt.value("#3fa45b"), alt.value("#d9534f")),
            tooltip=[
                "champion_name",
                alt.Tooltip("wr_short:Q", format=".1%", title="короткие"),
                alt.Tooltip("wr_long:Q", format=".1%", title="длинные"),
                alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
            ],
        )
        .properties(height=520)
    )
    st.altair_chart(chart, width="stretch")
    table_with_download(scaling, "Чемпионы по длине матча", "champion_by_duration.csv",
                        key="dl_duration",
                        caption="Сверху — сильнее в долгой игре, снизу — сильнее в короткой.")
