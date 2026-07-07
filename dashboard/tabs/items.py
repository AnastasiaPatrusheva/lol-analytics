"""Вкладка «Предметы»: покупки × winrate."""
import altair as alt
import streamlit as st

from dashboard.data import run, download_csv


def render(source: str) -> None:
    min_gold = st.slider(
        "Минимальная цена предмета (золото)", 0, 4000, 2000, step=250,
        help="Отсекает дешёвые предметы и триннкеты-варды, чтобы видеть «билдовые» предметы",
    )
    items = run(f"""
        SELECT item_name, purchases, winrate, wilson_low, gold_total
        FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= {min_gold}
        ORDER BY purchases DESC
    """)

    st.subheader("Какие предметы стоит собирать")
    st.caption(
        "Точка на графике — предмет: правее — покупают чаще, выше — чаще с ним побеждают. "
        "Верх-право = и популярны, и приносят победы."
    )
    if items.empty:
        st.info("Нет предметов с таким порогом цены.")
        return

    best = items.sort_values("wilson_low", ascending=False).iloc[0]
    st.success(
        f"🛡️ Лучший по winrate: **{best['item_name']}** — "
        f"{best['winrate']:.0%} при {int(best['purchases'])} покупках."
    )
    scatter = (
        alt.Chart(items)
        .mark_circle(size=70, opacity=0.7, color="#3fa45b")
        .encode(
            x=alt.X("purchases:Q", title="Покупок"),
            y=alt.Y("winrate:Q", title="Winrate", axis=alt.Axis(format="%"),
                    scale=alt.Scale(zero=False)),
            tooltip=[
                "item_name", "purchases",
                alt.Tooltip("winrate:Q", format=".1%"),
                alt.Tooltip("gold_total:Q", title="Цена"),
            ],
        )
        .interactive()
        .properties(height=420)
    )
    st.altair_chart(scatter, width="stretch")
    st.markdown("#### Все предметы (сортировка по winrate)")
    table = items.sort_values("winrate", ascending=False)
    st.dataframe(table, width="stretch", hide_index=True)
    download_csv(table, "items.csv", key="dl_items")
