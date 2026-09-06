"""Вкладка «Архетипы»: сегментация игроков (KMeans)."""
import altair as alt
import streamlit as st

from dashboard.charts import radar_grid
from dashboard.data import run, table_exists, table_with_download


def render(source: str) -> None:
    st.subheader("Архетипы игроков")
    st.caption(
        "Игроки разбиты на группы по манере игры. Названия описательные, это не официальные "
        "категории Riot."
    )
    st.info(
        "**Метрики сравниваются внутри роли.** Золото, фарм и обзор в минуту почти полностью "
        "определяются ролью: бот по определению получает больше золота, чем саппорт. Если "
        "кластеризовать по сырым значениям, найдутся просто роли. Поэтому каждая метрика "
        "игрока делится на среднюю по его основной роли: 1.0 значит «как типичный игрок моей "
        "роли», 1.3 значит «на 30% выше». Архетип показывает, чем игрок выделяется среди "
        "своих, а не кем он играет.",
        icon="🧭",
    )
    st.markdown(
        "**Что значат названия:**\n"
        "- **Агрессивный** — урон выше нормы своей роли\n"
        "- **Фармящий** — больше миньонов (CS), чем типично для роли\n"
        "- **Играет на обзор** — больше вардинга и контроля карты\n"
        "- **Сильная экономика** — больше золота в минуту\n"
        "- **Осторожный** — высокий KDA, то есть реже умирает"
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
        f"Самый массовый архетип: **{top['archetype']}** — "
        f"{int(top['players'])} игроков, ср. winrate {top['winrate']:.0%}."
    )

    c_left, c_right = st.columns([1, 1.4])
    with c_left:
        st.markdown("#### Игроков в каждом архетипе")
        ybar = alt.Y("archetype:N", sort="-x", title=None,
                     axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
        bar = (
            alt.Chart(counts)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("players:Q", title="Игроков", axis=alt.Axis(grid=True, domain=False)),
                y=ybar,
                color=alt.Color("archetype:N", legend=None),
                tooltip=["archetype", "players", alt.Tooltip("winrate:Q", format=".0%")],
            )
            .properties(height=320)
        )
        labels = (
            alt.Chart(counts)
            .mark_text(align="left", dx=5, fontSize=12, color="#cfd6d6")
            .encode(x=alt.X("players:Q"), y=ybar, text=alt.Text("players:Q"))
        )
        st.altair_chart((bar + labels).configure_view(strokeWidth=0), width="stretch")
    with c_right:
        st.markdown("#### Урон vs обзор, обе метрики в долях от нормы роли")
        scatter = (
            alt.Chart(seg)
            .mark_circle(size=60, opacity=0.5)
            .encode(
                x=alt.X("damage_per_min:Q", title="Урон к норме своей роли"),
                y=alt.Y("vision_per_min:Q", title="Обзор к норме своей роли"),
                color=alt.Color("archetype:N", title="Архетип"),
                tooltip=["name", "archetype", "games",
                         alt.Tooltip("winrate:Q", format=".0%"),
                         alt.Tooltip("kda:Q", format=".2f")],
            )
            # Без .interactive(): зум колесом перехватывает прокрутку страницы.
            .properties(height=300)
        )
        st.altair_chart(scatter, width="stretch")

    profile = counts.rename(columns={
        "archetype": "Архетип", "players": "Игроков", "winrate": "Winrate",
        "kda": "KDA к норме", "cs": "CS к норме", "dmg": "Урон к норме",
        "vision": "Обзор к норме", "gold": "Золото к норме",
    })
    table_with_download(
        profile, "Профиль архетипов (в долях от нормы роли)", "player_segments.csv",
        key="dl_segments",
        caption="Все метрики, кроме winrate, показаны относительно средней по основной роли "
                "игрока: 1.00 значит «как типичный игрок этой роли», 1.30 значит «на 30% выше». "
                "Winrate — обычная доля побед.")
    st.caption(
        "Разница в winrate между архетипами не означает, что один стиль сильнее. "
        "Группы отличаются ещё и уровнем игроков, а сегментация разведочная: "
        "силуэт около 0.22 говорит, что границы между группами размыты."
    )

    st.markdown("#### Профиль архетипов — радар")
    st.caption(
        "Профиль каждого архетипа по шести метрикам. Значения нормированы между "
        "архетипами: чем дальше от центра по оси, тем выше показатель, край — максимум "
        "среди архетипов. Форма фигуры показывает, чем архетип выделяется."
    )
    radar_grid(counts.set_index("archetype"),
               [("winrate", "WR"), ("kda", "KDA"), ("cs", "CS"),
                ("dmg", "Урон"), ("vision", "Обзор"), ("gold", "Золото")])
