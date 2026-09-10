"""Вкладка «Архетипы»: сегментация игроков (KMeans)."""
import altair as alt
import pandas as pd
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
        "потому что он бот. Если сравнивать всех вместе, группы разложатся ровно по ролям, "
        "и никакой манеры игры мы не увидим. Поэтому показатель каждого игрока мы делим "
        "на средний по его роли. Единица означает «как обычный игрок моей роли», "
        "1.3 — «на 30% больше». Так группы показывают, насколько человек отличается "
        "от среднего по своей роли.",
        icon="🧭",
    )
    st.markdown(
        "**Что значат названия:**\n"
        "- **Агрессивный** — урон выше нормы своей роли\n"
        "- **Фармящий** — больше миньонов (CS), чем типично для роли\n"
        "- **Играет на обзор** — чаще ставит на карту наблюдателей, которые показывают, "
        "что происходит в этом месте; так команда видит противника заранее\n"
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

    # Оба графика одной высоты и с короткими заголовками в одну строку: разная
    # высота и перенос заголовка справа делали пару визуально несимметричной.
    H = 340
    c_left, c_right = st.columns([1, 1.4])
    with c_left:
        st.markdown("#### Игроков в каждой группе")
        ybar = alt.Y("archetype:N", sort="-x", title=None,
                     axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
        # Запас справа, иначе число у самой длинной полосы уходит за край
        # графика и обрезается («1505» превращалось в «150»).
        x_max = float(counts["players"].max()) * 1.18
        bar = (
            alt.Chart(counts)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("players:Q", title="Игроков",
                        scale=alt.Scale(domain=[0, x_max]),
                        axis=alt.Axis(grid=True, domain=False)),
                y=ybar,
                color=alt.Color("archetype:N", legend=None),
                tooltip=["archetype", "players", alt.Tooltip("winrate:Q", format=".1%")],
            )
            .properties(height=H)
        )
        labels = (
            alt.Chart(counts)
            .mark_text(align="left", dx=5, fontSize=12, color="#cfd6d6")
            .encode(x=alt.X("players:Q"), y=ybar, text=alt.Text("players:Q"))
        )
        st.altair_chart((bar + labels).configure_view(strokeWidth=0), width="stretch")
    with c_right:
        st.markdown("#### Урон и обзор")
        scatter = (
            alt.Chart(seg)
            .mark_circle(size=60, opacity=0.5)
            .encode(
                x=alt.X("damage_per_min:Q", title="Урон к норме своей роли"),
                y=alt.Y("vision_per_min:Q", title="Обзор к норме своей роли"),
                color=alt.Color("archetype:N", title="Группа"),
                tooltip=["name", "archetype", "games",
                         alt.Tooltip("winrate:Q", format=".1%"),
                         alt.Tooltip("kda:Q", format=".2f")],
            )
        )
        # Линии нормы: единица по обеим осям — «как обычный игрок своей роли».
        # Сразу видно, кто выше нормы по урону, кто по обзору, а кто ниже по обоим.
        norm_x = alt.Chart(pd.DataFrame({"v": [1.0]})).mark_rule(
            color="#a49b86", strokeDash=[4, 4]).encode(x="v:Q")
        norm_y = alt.Chart(pd.DataFrame({"v": [1.0]})).mark_rule(
            color="#a49b86", strokeDash=[4, 4]).encode(y="v:Q")
        # Без .interactive(): зум колесом перехватывает прокрутку страницы.
        st.altair_chart((scatter + norm_x + norm_y).properties(height=H), width="stretch")
        st.caption("Пунктир — норма роли. Правее вертикальной линии урона больше обычного, "
                   "выше горизонтальной — больше обзора.")

    profile = counts.rename(columns={
        "archetype": "Архетип", "players": "Игроков", "winrate": "Побед",
        "kda": "KDA к норме", "cs": "CS к норме", "dmg": "Урон к норме",
        "vision": "Обзор к норме", "gold": "Золото к норме",
    })
    # Что значат 1.00 и 1.30, уже сказано в синей плашке выше, не повторяем.
    table_with_download(
        profile, "Чем группы отличаются друг от друга", "player_segments.csv",
        key="dl_segments",
        caption="«Побед» — обычный процент выигранных матчей, остальные столбцы — "
                "в сравнении со своей ролью.")
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
