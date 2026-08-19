"""Вкладка «Состав»: прогноз winrate командного состава.

Не ML: оценка — средневзвешенный winrate каждого героя в его роли, вес — по
надёжности (числу игр), а сам winrate берём осторожным (нижняя граница Уилсона).
Плюс заметка про баланс ролей (фронтлайн / урон / поддержка) по классам чемпионов.
"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.data import run, champion_images

ROLES = [("TOP", "Топ"), ("JUNGLE", "Лес"), ("MIDDLE", "Мид"),
         ("BOTTOM", "Бот"), ("UTILITY", "Саппорт")]

# Грубая группировка классов Data Dragon для заметки о балансе.
FRONTLINE = {"Tank", "Fighter"}
DAMAGE = {"Marksman", "Mage", "Assassin"}
SUPPORT_CLS = {"Support"}


def _card(rk_ru, row, imgs):
    img = imgs.get(int(row["champion_id"]), "")
    pic = (f"<img src='{img}' style='width:40px;height:40px;border-radius:8px;"
           f"border:1px solid #2f3a4d;flex:none'>") if img else ""
    wr = float(row["winrate"])
    color = "#C8AA6E" if wr >= 0.5 else "#d9534f"
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:10px;"
        "padding:9px 13px;display:flex;gap:11px;align-items:center;margin-bottom:7px'>"
        f"{pic}<div style='flex:1;min-width:0'>"
        f"<div style='font-weight:600;color:#F0E6D2'>{rk_ru} — {row['champion_name']}</div>"
        f"<div style='font-size:12px;color:#a49b86'>{int(row['games'])} игр · "
        f"надёжность оценки {min(100, int(row['games'] / 2)):d}%</div></div>"
        f"<div style='color:{color};font-weight:600'>{wr:.1%} побед</div></div>"
    )


def render(source: str) -> None:
    st.subheader("Соберите состав")
    st.caption(
        "Выберите по одному чемпиону на каждую роль. Про каждого известно, как часто "
        "он побеждает именно на этой роли — по истории матчей. Дашборд усредняет эти "
        "пять winrate и показывает, какого результата в среднем можно ждать от такого "
        "состава. Это прикидка по прошлым играм, а не предсказание конкретного матча и "
        "не нейросеть; у чемпионов с малым числом игр оценка берётся осторожнее, чтобы "
        "случайные всплески её не завышали."
    )

    df = run(f"""
        SELECT c.champion_name, c.champion_id, c.primary_class, f.role_key,
               COUNT(DISTINCT f.match_id) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               wilson_low(AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END),
                          COUNT(DISTINCT f.match_id)) AS wilson_low
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        WHERE f.data_source = '{source}'
          AND f.role_key IN ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY')
        GROUP BY c.champion_name, c.champion_id, c.primary_class, f.role_key
        HAVING COUNT(DISTINCT f.match_id) >= 20
    """)
    if df.empty:
        st.info("Мало данных по ролям у этого источника. Выберите riot_full слева.")
        return

    imgs = champion_images()
    st.caption(
        "В каждом списке — только чемпионы, которых реально играют на этой роли "
        "(в данных ≥20 игр). Поэтому набор ролей у одного героя может отличаться: "
        "саппорта вы не увидите в списке лесников, если на нём там почти не играют."
    )
    cols = st.columns(5)
    picks = {}
    for (rk, rk_ru), col in zip(ROLES, cols):
        opts = sorted(df[df["role_key"] == rk]["champion_name"].unique().tolist())
        picks[rk] = col.selectbox(rk_ru, opts, key=f"compo_{rk}") if opts else None

    chosen = []
    for rk, rk_ru in ROLES:
        name = picks.get(rk)
        if not name:
            continue
        sub = df[(df["role_key"] == rk) & (df["champion_name"] == name)]
        if not sub.empty:
            chosen.append((rk_ru, sub.iloc[0]))
    if not chosen:
        return

    # Прогноз: средневзвешенный по числу игр, оценка героя — нижняя граница Уилсона.
    weights = np.array([float(r["games"]) for _, r in chosen])
    vals = np.array([float(r["wilson_low"]) for _, r in chosen])
    pred = float(np.average(vals, weights=weights))

    classes = {c for _, r in chosen for c in str(r["primary_class"]).split(",")}
    has_front = bool(classes & FRONTLINE)
    has_dmg = bool(classes & DAMAGE)
    has_supp = bool(picks.get("UTILITY"))
    balance = (
        "Сбалансированный состав: есть фронтлайн, урон и поддержка."
        if has_front and has_dmg and has_supp else
        "Состав однобокий: " + ", ".join(
            x for x, ok in [("нет фронтлайна", not has_front),
                            ("мало урона", not has_dmg),
                            ("нет саппорта", not has_supp)] if ok
        ) + "."
    )

    left, right = st.columns([1, 1.6])
    with left:
        color = "#C8AA6E" if pred >= 0.5 else "#d9534f"
        st.markdown(
            "<div style='background:#10233a;border:1px solid #2f3a4d;border-left:3px solid "
            f"{color};border-radius:12px;padding:16px 18px'>"
            "<div style='font-size:11px;color:#a49b86;text-transform:uppercase;letter-spacing:.06em'>"
            "Прогноз победы состава</div>"
            f"<div style=\"font-family:'Palatino Linotype',serif;font-size:38px;font-weight:600;"
            f"color:#F0E6D2\">{pred:.0%}</div>"
            f"<div style='font-size:12.5px;color:#a49b86'>{balance}</div></div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Чем больше игр на чемпионе, тем сильнее он влияет на общую оценку: по "
            "редким пикам судить ненадёжно. Сам winrate берём осторожно, с поправкой на "
            "размер выборки. Отдельно проверяем, сбалансирован ли состав — есть ли танк "
            "или боец, урон и поддержка."
        )
    with right:
        st.markdown("#### Вклад каждой роли")
        html = "".join(_card(rk_ru, r, imgs) for rk_ru, r in chosen)
        st.markdown(html, unsafe_allow_html=True)

    st.divider()
    st.markdown("#### Профиль ролей")
    st.caption(
        "Профиль каждой роли по пяти метрикам (KDA, CS, урон, обзор, золото). Значения "
        "нормированы между ролями: чем дальше от центра по оси, тем выше показатель, "
        "край — максимум среди ролей. Форма фигуры показывает сильные стороны роли."
    )
    roles_df = run(f"""
        SELECT f.role_key,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               AVG(f.kda) AS kda, AVG(f.cs_per_min) AS cs,
               AVG(f.damage_per_min) AS dmg, AVG(f.gold_per_min) AS gold,
               AVG(f.vision_per_min) AS vision
        FROM fact_participant f
        WHERE f.data_source = '{source}'
          AND f.role_key IN ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY')
        GROUP BY f.role_key
    """)
    if roles_df.empty:
        return
    roles_df["role"] = roles_df["role_key"].map(dict(ROLES))
    # WR у ролей ~50% у всех (неинформативно). Берём метрики, которые реально
    # различают роли; нормируем value/max. Мини-радар на роль — накладывать 5 ролей-
    # «противоположностей» на один радар нечитаемо.
    metrics = [("kda", "KDA"), ("cs", "CS"), ("dmg", "Урон"),
               ("vision", "Обзор"), ("gold", "Золото")]
    rad = roles_df.set_index("role_key")
    for col, _ in metrics:
        hi = rad[col].max()
        rad[col + "_n"] = rad[col] / hi if hi > 0 else 0.0
    m = len(metrics)
    sc = alt.Scale(domain=[-1.62, 1.62])

    def _pentagon(values):
        pts = []
        for i, v in enumerate(values):
            ang = i * 2 * np.pi / m - np.pi / 2
            pts.append({"x": v * np.cos(ang), "y": v * np.sin(ang), "order": i})
        pts.append({**pts[0], "order": m})
        return pd.DataFrame(pts)

    ref_df = _pentagon([1.0] * m)
    axis_lbl = pd.DataFrame([
        {"x": 1.36 * np.cos(i * 2 * np.pi / m - np.pi / 2),
         "y": 1.36 * np.sin(i * 2 * np.pi / m - np.pi / 2), "t": lbl}
        for i, (_, lbl) in enumerate(metrics)
    ])
    labels = (alt.Chart(axis_lbl)
              .mark_text(fontSize=9, color="#a49b86")
              .encode(x=alt.X("x:Q", axis=None, scale=sc),
                      y=alt.Y("y:Q", axis=None, scale=sc), text="t:N"))
    cols = st.columns(m)
    for (rk, rk_ru), col in zip(ROLES, cols):
        if rk not in rad.index:
            continue
        pdf = _pentagon([float(rad.loc[rk, mc + "_n"]) for mc, _ in metrics])
        ref = (alt.Chart(ref_df)
               .mark_line(interpolate="linear-closed", strokeWidth=1, color="#2f3a4d")
               .encode(x=alt.X("x:Q", axis=None, scale=sc),
                       y=alt.Y("y:Q", axis=None, scale=sc), order="order:Q"))
        shape = (alt.Chart(pdf)
                 .mark_line(interpolate="linear-closed", strokeWidth=2,
                            color="#C8AA6E", fill="#C8AA6E", fillOpacity=0.30)
                 .encode(x=alt.X("x:Q", axis=None, scale=sc),
                         y=alt.Y("y:Q", axis=None, scale=sc), order="order:Q"))
        col.markdown(
            f"<div style='text-align:center;font-weight:600;color:#F0E6D2'>{rk_ru}</div>",
            unsafe_allow_html=True)
        col.altair_chart((ref + shape + labels).properties(height=170).configure_view(strokeWidth=0),
                         use_container_width=True)
