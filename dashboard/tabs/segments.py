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
        "**Каждого сравниваем со своей ролью, а не со всеми подряд.** Золото, фарм и обзор "
        "почти целиком задаются ролью: бот получает больше золота, чем саппорт, просто "
        "потому что он бот. Если сравнивать всех вместе, компьютер найдёт не манеру игры, "
        "а те же самые роли, и выдаст это за открытие. Поэтому показатель каждого игрока "
        "мы делим на средний по его роли. Единица означает «как обычный игрок моей роли», "
        "1.3 — «на 30% больше». Так группы говорят о том, чем человек отличается от "
        "коллег по роли.",
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
        f"Самая большая группа — «{top['archetype']}»: {int(top['players'])} игроков, "
        f"в среднем {top['winrate']:.0%} побед."
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
        st.markdown("#### Урон и обзор, оба в сравнении с нормой своей роли")
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
        "archetype": "Архетип", "players": "Игроков", "winrate": "Побед",
        "kda": "KDA к норме", "cs": "CS к норме", "dmg": "Урон к норме",
        "vision": "Обзор к норме", "gold": "Золото к норме",
    })
    table_with_download(
        profile, "Чем группы отличаются друг от друга", "player_segments.csv",
        key="dl_segments",
        caption="Все столбцы, кроме доли побед, показывают сравнение со своей ролью: "
                "1.00 значит «как обычный игрок этой роли», 1.30 — «на 30% больше». "
                "Доля побед — обычный процент выигранных матчей.")
    st.caption(
        "Не читайте разницу в победах как «этот стиль сильнее». Группы отличаются не только "
        "манерой игры, но и уровнем самих игроков, и разделить одно от другого здесь нечем. "
        "К тому же границы между группами размытые: у игроков на стыке двух групп показатели "
        "почти одинаковые, и деление во многом условное."
    )

    st.markdown("#### Портрет каждой группы")
    st.caption(
        "Каждая фигура — одна группа, каждый луч — один показатель. Чем дальше точка от "
        "центра, тем показатель выше; край луча — лучшее значение среди всех групп. "
        "Смотреть надо на форму: она сразу показывает, чем группа отличается от соседних."
    )
    radar_grid(counts.set_index("archetype"),
               [("winrate", "Побед"), ("kda", "KDA"), ("cs", "CS"),
                ("dmg", "Урон"), ("vision", "Обзор"), ("gold", "Золото")])
