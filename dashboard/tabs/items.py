"""Вкладка «Предметы»: как часто предмет оказывается в финальной сборке × winrate.

Данные Riot дают инвентарь НА КОНЕЦ матча, а не покупки по ходу игры, поэтому
вкладка описательная: она не отвечает на вопрос «что покупать, чтобы выиграть».
"""
import altair as alt
import streamlit as st

from dashboard.data import run, download_csv, item_images
from dashboard.theme import hero_card


def _item_card(title, row, value, icons, accent="#C8AA6E"):
    return hero_card(title, row["item_name"], value, icons.get(int(row["item_id"]), ""), accent)


def render(source: str) -> None:
    min_gold = st.slider(
        "Минимальная цена предмета (золото)", 0, 4000, 2000, step=250, key="f_min_gold",
        help="Отсекает дешёвые предметы и тринкеты-варды, чтобы видеть «билдовые» предметы",
    )
    items = run(f"""
        SELECT item_name, item_id, appearances, winrate, wilson_low, gold_total
        FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= {min_gold}
        ORDER BY appearances DESC
    """)

    st.subheader("Что чаще всего стоит в финальной сборке")
    st.caption(
        "Сборка — это набор предметов, с которым игрок закончил матч. Точка на графике — "
        "предмет: правее — встречается в сборках чаще, выше — чаще оказывается в сборке "
        "того, кто выиграл."
    )
    st.warning(
        "**Это не совет, что покупать.** Riot сохраняет, что лежало в сумке в конце матча, "
        "а не что и когда игрок покупал. А дорогую вещь успевает достроить тот, кто дольше "
        "живёт, то есть чаще всего тот, кто и так выигрывает. Получается наоборот: не "
        "предмет привёл к победе, а победа дала время его собрать. Такую ловушку называют "
        "обратной причинностью. Читайте таблицу как «с чем игрок дошёл до победы», "
        "а не как «что купить, чтобы выиграть».",
        icon="⚠️",
    )
    if items.empty:
        st.info("Нет предметов с таким порогом цены.")
        return

    icons = item_images()
    best_wr = items.sort_values("wilson_low", ascending=False).iloc[0]
    most_common = items.iloc[0]  # запрос уже отсортирован по appearances DESC
    c1, c2 = st.columns(2)
    c1.markdown(_item_card("Чаще всего у победителей", best_wr,
                           f"{best_wr['winrate']:.0%} · {int(best_wr['appearances'])} сборок", icons),
                unsafe_allow_html=True)
    c2.markdown(_item_card("Встречается чаще всего", most_common,
                           f"{int(most_common['appearances'])} сборок · "
                           f"побед {most_common['winrate']:.0%}",
                           icons, accent="#5aa0c9"), unsafe_allow_html=True)
    st.write("")

    scatter = (
        alt.Chart(items)
        .mark_circle(size=80, opacity=0.7, color="#C8AA6E", stroke="#141719", strokeWidth=0.4)
        .encode(
            x=alt.X("appearances:Q", title="Сборок с этим предметом"),
            y=alt.Y("winrate:Q", title="Доля побед", axis=alt.Axis(format="%"),
                    scale=alt.Scale(zero=False)),
            tooltip=[
                "item_name", alt.Tooltip("appearances:Q", title="Сборок"),
                alt.Tooltip("winrate:Q", format=".1%", title="Доля побед"),
                alt.Tooltip("gold_total:Q", title="Цена"),
            ],
        )
        # Без .interactive(): зум колесом перехватывает прокрутку страницы.
        .properties(height=420)
    )
    st.altair_chart(scatter, width="stretch")

    left, right = st.columns([4, 1])
    left.markdown("#### Все предметы по доле побед")
    with right:
        download_csv(items, "items.csv", key="dl_items", use_container_width=True)
    st.caption(
        "Полоски нарисованы в коридоре от 40% до 65%, а не от нуля: иначе все предметы "
        "выглядели бы одинаково. Разница между ними на глаз кажется больше, чем есть."
    )
    table = items.sort_values("winrate", ascending=False).copy()
    table.insert(0, "icon", table["item_id"].map(icons))
    st.dataframe(
        table[["icon", "item_name", "appearances", "winrate", "wilson_low", "gold_total"]],
        hide_index=True, width="stretch",
        column_config={
            "icon": st.column_config.ImageColumn(" ", width="small"),
            "item_name": "Предмет",
            "appearances": st.column_config.NumberColumn("Сборок"),
            "winrate": st.column_config.ProgressColumn(
                "Побед", format="percent", min_value=0.40, max_value=0.65),
            "wilson_low": st.column_config.NumberColumn(
                "Осторожно", format="percent",
                help="Доля побед, заниженная с учётом того, в скольких сборках встретился предмет"),
            "gold_total": st.column_config.NumberColumn("Цена", format="%d"),
        },
    )
