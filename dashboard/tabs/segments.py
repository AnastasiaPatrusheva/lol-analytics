"""Вкладка «Архетипы»: сегментация игроков (KMeans)."""
import altair as alt
import streamlit as st

from dashboard.data import run, table_exists, download_csv


def render(source: str) -> None:
    st.subheader("Архетипы игроков")
    st.caption(
        "Игроки разбиты на группы по стилю игры. Названия описательные — это не официальные "
        "категории Riot."
    )
    st.markdown(
        "**Что значат названия архетипов:**\n"
        "- **фарм** — много миньонов (CS)\n"
        "- **урон** — высокий урон по чемпионам\n"
        "- **обзор** — контроль карты (вардинг)\n"
        "- **экономика** — много золота\n"
        "- **командный** — высокий KDA при низком фарме (участие в командных боях)"
    )
    if not table_exists("player_segments"):
        st.info("Данные по архетипам пока недоступны.")
        return

    seg = run(f"SELECT * FROM player_segments WHERE data_source = '{source}'")
    if seg.empty:
        st.info(
            f"Для источника «{source}» мало игроков с ≥20 играми для группировки. "
            "Выберите источник riot_full в панели «Фильтры» слева."
        )
        return

    counts = (
        seg.groupby("archetype")
        .agg(players=("puuid", "count"), winrate=("winrate", "mean"),
             kda=("kda", "mean"), cs=("cs_per_min", "mean"),
             dmg=("damage_per_min", "mean"), vision=("vision_per_min", "mean"),
             gold=("gold_per_min", "mean"))
        .reset_index()
        .sort_values("players", ascending=False)
    )
    top = counts.iloc[0]
    st.success(
        f"🧩 Самый массовый архетип: **{top['archetype']}** — "
        f"{int(top['players'])} игроков, ср. winrate {top['winrate']:.0%}."
    )

    c_left, c_right = st.columns([1, 1.4])
    with c_left:
        st.markdown("#### Игроков в каждом архетипе")
        bar = (
            alt.Chart(counts)
            .mark_bar()
            .encode(
                x=alt.X("players:Q", title="Игроков"),
                y=alt.Y("archetype:N", sort="-x", title=None),
                color=alt.Color("archetype:N", legend=None),
                tooltip=["archetype", "players", alt.Tooltip("winrate:Q", format=".0%")],
            )
            .properties(height=300)
        )
        st.altair_chart(bar, width="stretch")
    with c_right:
        st.markdown("#### Урон в минуту vs контроль карты (вардинг)")
        scatter = (
            alt.Chart(seg)
            .mark_circle(size=60, opacity=0.5)
            .encode(
                x=alt.X("damage_per_min:Q", title="Урон/мин"),
                y=alt.Y("vision_per_min:Q", title="Контроль карты (обзор), в минуту"),
                color=alt.Color("archetype:N", title="Архетип"),
                tooltip=["name", "archetype", "games",
                         alt.Tooltip("winrate:Q", format=".0%"),
                         alt.Tooltip("kda:Q", format=".2f")],
            )
            .interactive()
            .properties(height=300)
        )
        st.altair_chart(scatter, width="stretch")

    st.markdown("#### Профиль архетипов (средние метрики)")
    st.caption("Средние показатели каждой группы — видно, чем они реально отличаются.")
    profile = counts.rename(columns={
        "archetype": "Архетип", "players": "Игроков", "winrate": "Winrate",
        "kda": "KDA", "cs": "CS/мин", "dmg": "Урон/мин",
        "vision": "Обзор/мин", "gold": "Золото/мин",
    })
    st.dataframe(profile, width="stretch", hide_index=True)
    download_csv(profile, "player_segments.csv", key="dl_segments")
