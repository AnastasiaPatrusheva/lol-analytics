"""Вкладка «Предметы»: покупки × winrate, с иконками Data Dragon."""
import altair as alt
import streamlit as st

from dashboard.data import run, download_csv, item_images


def _item_card(title, row, value, icons, accent="#C8AA6E"):
    ic = icons.get(int(row["item_id"]), "")
    pic = (f"<img src='{ic}' style='width:52px;height:52px;border-radius:9px;"
           f"border:1px solid #2f3a4d;flex:none'>") if ic else ""
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:14px;"
        "padding:13px 15px;display:flex;gap:12px;align-items:center'>"
        f"{pic}<div style='min-width:0'>"
        f"<div style='font-size:11px;color:#a49b86;text-transform:uppercase;letter-spacing:.05em'>{title}</div>"
        "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:18px;"
        f"font-weight:600;color:#e8ecec\">{row['item_name']}</div>"
        f"<div style='font-size:13px;color:{accent}'>{value}</div>"
        "</div></div>"
    )


def render(source: str) -> None:
    min_gold = st.slider(
        "Минимальная цена предмета (золото)", 0, 4000, 2000, step=250,
        help="Отсекает дешёвые предметы и триннкеты-варды, чтобы видеть «билдовые» предметы",
    )
    items = run(f"""
        SELECT item_name, item_id, purchases, winrate, wilson_low, gold_total
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

    icons = item_images()
    best_wr = items.sort_values("wilson_low", ascending=False).iloc[0]
    most_bought = items.iloc[0]  # запрос уже отсортирован по purchases DESC
    c1, c2 = st.columns(2)
    c1.markdown(_item_card("Лучший по winrate", best_wr,
                           f"{best_wr['winrate']:.0%} · {int(best_wr['purchases'])} покупок", icons),
                unsafe_allow_html=True)
    c2.markdown(_item_card("Самый покупаемый", most_bought,
                           f"{int(most_bought['purchases'])} покупок · WR {most_bought['winrate']:.0%}",
                           icons, accent="#5aa0c9"), unsafe_allow_html=True)
    st.write("")

    scatter = (
        alt.Chart(items)
        .mark_circle(size=80, opacity=0.7, color="#C8AA6E", stroke="#141719", strokeWidth=0.4)
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

    left, right = st.columns([4, 1])
    left.markdown("#### Все предметы (по winrate)")
    with right:
        download_csv(items, "items.csv", key="dl_items", use_container_width=True)
    table = items.sort_values("winrate", ascending=False).copy()
    table.insert(0, "icon", table["item_id"].map(icons))
    st.dataframe(
        table[["icon", "item_name", "purchases", "winrate", "wilson_low", "gold_total"]],
        hide_index=True, width="stretch",
        column_config={
            "icon": st.column_config.ImageColumn(" ", width="small"),
            "item_name": "Предмет",
            "purchases": st.column_config.NumberColumn("Покупок"),
            "winrate": st.column_config.ProgressColumn(
                "Winrate", format="percent", min_value=0.40, max_value=0.65),
            "wilson_low": st.column_config.NumberColumn("Ниж. оценка", format="percent"),
            "gold_total": st.column_config.NumberColumn("Цена", format="%d"),
        },
    )
