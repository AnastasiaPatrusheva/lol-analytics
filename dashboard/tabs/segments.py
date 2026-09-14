"""Вкладка «Архетипы»: сегментация игроков (KMeans)."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard.charts import radar_grid
from dashboard.data import run, table_exists, table_with_download

# Что значит каждый ярлык. Ярлыки ставит scripts/build_player_segments.py
# (ARCHETYPE_BY_FEATURE), и набор групп меняется от пересборки к пересборке, поэтому
# легенда показывает только те, что есть в данных. Раньше список был вписан руками:
# описывал «Агрессивный» и «Сильная экономика», которых в riot_full нет, а самая
# большая группа, «Часто умирает», оставалась без объяснения.
# Полноту словаря проверяет tests/test_segments.py.
ARCHETYPE_DESC = {
    "Агрессивный": "урона по чемпионам соперника больше, чем обычно на его роли",
    "Мало урона": "урона по чемпионам соперника меньше, чем обычно на его роли",
    "Фармящий": "больше миньонов (CS), чем типично для роли",
    "Мало фарма": "меньше миньонов (CS), чем типично для роли",
    "Играет на обзор": "чаще ставит на карту наблюдателей, которые показывают, что "
                       "происходит в этом месте; так команда видит противника заранее",
    "Не ставит варды": "реже обычного для роли ставит наблюдателей, поэтому команда "
                       "видит меньше карты",
    "Сильная экономика": "больше золота в минуту, чем обычно на роли",
    "Слабая экономика": "меньше золота в минуту, чем обычно на роли",
    "Осторожный": "высокий KDA, то есть реже умирает",
    "Часто умирает": "низкий KDA, то есть гибнет чаще, чем обычно на его роли",
    "Не классифицирован": "не хватило показателей, чтобы отнести игрока к группе",
    "Мало данных": "в источнике слишком мало игроков, чтобы разбить их на группы",
}


def _legend(archetypes: list[str]) -> str:
    rows = []
    for a in archetypes:
        # «Осторожный + урон» и «Осторожный #2» — уточнённые ярлыки при совпадении
        # главной метрики у двух групп; смысл у них тот же, что у базового.
        desc = ARCHETYPE_DESC.get(a.split(" + ")[0].split(" #")[0])
        rows.append(f"- **{a}** — {desc}" if desc else f"- **{a}**")
    return "**Что значат названия:**\n" + "\n".join(rows)


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
    st.markdown(_legend(counts["archetype"].tolist()))
    top = counts.iloc[0]
    st.success(
        f"Самая большая группа — «{top['archetype']}»: {int(top['players'])} игроков, "
        f"в среднем {top['winrate']:.0%} побед."
    )

    # Заголовки — отдельной строкой колонок, а графики — следующей. Streamlit
    # складывает каждую колонку независимо, и когда при открытом фильтре слева
    # колонка сужалась, длинный заголовок переносился на две строки и сдвигал
    # свой график вниз относительно соседнего. Строка заголовков берёт высоту
    # самого высокого из них, поэтому графики теперь начинаются вровень при любой ширине.
    H = 340
    t_left, t_right = st.columns([1, 1.4])
    t_left.markdown("#### Игроков в каждой группе")
    t_right.markdown("#### Урон и обзор")
    c_left, c_right = st.columns([1, 1.4])
    with c_left:
        ybar = alt.Y("archetype:N", sort="-x", title=None,
                     axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
        # Запас справа, иначе число у самой длинной полосы уходит за край
        # графика и обрезается («1505» превращалось в «150»). Запас задан в долях
        # оси, а подписи нужно место в пикселях: при открытом фильтре график узкий,
        # и 18% не хватало. 35% держит подпись и на узкой колонке.
        x_max = float(counts["players"].max()) * 1.35
        bar = (
            alt.Chart(counts)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                # labelFlush прижимает крайние подписи оси внутрь графика: иначе
                # последняя метка на узкой колонке тоже вылезала за край.
                x=alt.X("players:Q", title="Игроков",
                        scale=alt.Scale(domain=[0, x_max]),
                        axis=alt.Axis(grid=True, domain=False, labelFlush=True)),
                y=ybar,
                color=alt.Color("archetype:N", legend=None),
                tooltip=["archetype", "players", alt.Tooltip("winrate:Q", format=".1%", title="доля побед")],
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
        scatter = (
            alt.Chart(seg)
            .mark_circle(size=60, opacity=0.5)
            .encode(
                x=alt.X("damage_per_min:Q", title="Урон к норме своей роли"),
                y=alt.Y("vision_per_min:Q", title="Обзор к норме своей роли"),
                color=alt.Color("archetype:N", title="Группа"),
                tooltip=["name", "archetype", "games",
                         alt.Tooltip("winrate:Q", format=".1%", title="доля побед"),
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

    # Доля побед в процентах, а не долей (было 0.4714 вместо 47.1%); отношения к
    # норме — с двумя знаками, четыре знака после запятой только мешали читать.
    profile = counts.assign(
        winrate=(counts["winrate"] * 100).round(1),
        **{c: counts[c].round(2) for c in ("kda", "cs", "dmg", "vision", "gold")},
    ).rename(columns={
        "archetype": "Группа", "players": "Игроков", "winrate": "Побед, %",
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
