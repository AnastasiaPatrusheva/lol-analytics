"""Вкладка «Состав»: прогноз winrate командного состава.

Не ML: оценка — средневзвешенный winrate каждого героя в его роли, вес — по
надёжности (числу игр), а сам winrate берём осторожным (нижняя граница Уилсона).
Плюс заметка про баланс ролей (фронтлайн / урон / поддержка) по классам чемпионов.
"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.charts import radar_grid
from dashboard.data import run, champion_images, table_exists

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


def _backtest(source: str) -> None:
    """Результат проверки модели на реальных командах (витрина composition_backtest)."""
    st.divider()
    st.markdown("#### Проверка модели")
    if not table_exists("composition_backtest"):
        st.info("Проверка не построена: запустите `python main.py backtest`.")
        return
    bt = run(f"SELECT * FROM composition_backtest WHERE data_source = '{source}'")
    if bt.empty:
        st.info(
            f"Для источника «{source}» проверку провести не на чем: нужен хотя бы один "
            "прошлый патч, чтобы обучиться, и достаточно матчей в последнем, чтобы "
            "проверить. Выберите **riot_full** в панели «Фильтры» слева."
        )
        return

    r = bt.iloc[0]
    # Разделитель тысяч — только в самом числе: раньше replace стоял на всей строке
    # и вычищал запятые из текста.
    n_matches = f"{int(r['test_matches']):,}".replace(",", " ")
    st.caption(
        f"Модель обучена на всех патчах до {r['test_patch']} и проверена на "
        f"{n_matches} матчах патча {r['test_patch']}, которых она не видела. "
        "Разделение по времени, а не случайное: так же она работала бы в жизни, когда исход "
        "ещё не наступил. Оцениваются обе команды матча, побеждает та, чья оценка выше, "
        "поэтому базовый уровень строго 50% и его нельзя обыграть угадыванием."
    )

    m1, m2, m3 = st.columns(3)
    acc = float(r["accuracy_raw"])
    m1.metric("Угадано матчей", f"{acc:.1%}", delta=f"{acc - 0.5:+.1%} к случайному",
              help="Доля матчей, где команда с более высокой оценкой действительно победила.")
    m2.metric("ROC AUC", f"{float(r['auc_raw']):.3f}",
              help="0.5 — модель не отличает победителей от проигравших, 1.0 — идеально.")
    m3.metric("Смещение", f"{float(r['bias_raw']):+.1%}",
              help="Насколько предсказанный процент в среднем расходится с фактическим.")

    st.warning(
        f"**Модель работает, но слабо.** Она угадывает победителя в {acc:.1%} матчей против "
        "50% у монетки. Это настоящий, но небольшой сигнал: состав действительно влияет на "
        "исход, однако куда меньше, чем мастерство игроков, ход самой игры и вражеская "
        "пятёрка, которую модель вообще не видит. Пользоваться этим прогнозом как "
        "предсказанием конкретного матча нельзя.",
        icon="⚠️",
    )

    with st.expander("Как выбирали способ считать оценку и почему"):
        st.markdown(
            "Проверены три варианта на одних и тех же матчах. Ни один не выигрывает "
            "по обеим метрикам сразу — это обычный компромисс между **ранжированием** "
            "(правильно ли модель расставляет составы по силе) и **калибровкой** "
            "(означает ли показанный процент то, что написано)."
        )
        variants = pd.DataFrame([
            {"Способ оценки": "Точечный winrate, равные веса",
             "Точность": r["accuracy_raw"], "AUC": r["auc_raw"], "Смещение": r["bias_raw"]},
            {"Способ оценки": "Нижняя граница Уилсона, равные веса",
             "Точность": r["accuracy_equal"], "AUC": r["auc_equal"], "Смещение": r["bias_equal"]},
            {"Способ оценки": "Нижняя граница Уилсона, веса по числу игр",
             "Точность": r["accuracy_weighted"], "AUC": r["auc_weighted"],
             "Смещение": r["bias_weighted"]},
        ])
        st.dataframe(
            variants, hide_index=True, width="stretch",
            column_config={
                "Точность": st.column_config.NumberColumn(format="percent"),
                "AUC": st.column_config.NumberColumn(format="%.3f"),
                "Смещение": st.column_config.NumberColumn(format="percent"),
            },
        )
        st.markdown(
            "- **Веса по числу игр** (так было раньше) оказались худшими по обеим метрикам. "
            "Число игр — это надёжность оценки чемпиона, а не важность роли в матче.\n"
            "- **Нижняя граница Уилсона** чуть лучше ранжирует, но занижает результат почти "
            "на 4 пункта: она намеренно осторожна, и среднее пяти заниженных оценок тоже "
            "занижено.\n"
            "- **Точечный winrate** почти не уступает в ранжировании и при этом честен по "
            "величине. Раз вкладка показывает число, а не только сортирует составы, выбран он."
        )

    calib = run(f"""
        SELECT * FROM composition_calibration
        WHERE data_source = '{source}' AND variant = 'Точечный winrate'
        ORDER BY bin_low
    """)
    if calib.empty:
        return
    st.markdown("**Калибровка: сбывается ли предсказанный процент**")
    st.caption(
        "Команды разбиты на восемь групп по величине прогноза. По горизонтали — что модель "
        "предсказала, по вертикали — как получилось. Точки на пунктирной диагонали означают, "
        "что прогноз сбывается; выше диагонали — модель недооценила, ниже — переоценила."
    )
    lo = float(min(calib["predicted"].min(), calib["actual"].min())) - 0.01
    hi = float(max(calib["predicted"].max(), calib["actual"].max())) + 0.01
    scale = alt.Scale(domain=[lo, hi])
    diag = (alt.Chart(pd.DataFrame({"v": [lo, hi]}))
            .mark_line(strokeDash=[4, 4], color="#6b7580")
            .encode(x=alt.X("v:Q", scale=scale), y=alt.Y("v:Q", scale=scale)))
    dots = (
        alt.Chart(calib)
        .mark_circle(size=140, color="#C8AA6E", stroke="#141719", strokeWidth=0.5)
        .encode(
            x=alt.X("predicted:Q", title="Предсказанный winrate",
                    axis=alt.Axis(format="%"), scale=scale),
            y=alt.Y("actual:Q", title="Фактический winrate",
                    axis=alt.Axis(format="%"), scale=scale),
            tooltip=[alt.Tooltip("predicted:Q", format=".1%", title="предсказано"),
                     alt.Tooltip("actual:Q", format=".1%", title="фактически"),
                     alt.Tooltip("teams:Q", title="команд")],
        )
    )
    st.altair_chart((diag + dots).properties(height=340), width="stretch")


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

    # Прогноз: среднее winrate пяти пиков, все роли с равным весом.
    #
    # Раньше здесь было средневзвешенное по числу игр от нижних границ Уилсона.
    # Бэктест на патче 16.12 (см. раздел «Проверка модели» ниже) показал, что этот
    # вариант худший по обеим метрикам: точность 51.9% против 53.1% у равных весов.
    # Число игр — это надёжность оценки чемпиона, а не важность роли в матче, и
    # взвешивание по нему просто перекашивает состав в сторону популярных пиков.
    #
    # Осторожную нижнюю границу Уилсона тоже не берём: она намеренно занижена, и
    # среднее пяти заниженных оценок занижено на 3.8 пункта. Точечный winrate
    # почти не уступает в ранжировании (AUC 0.524 против 0.529), зато показанный
    # процент означает ровно то, что написано: смещение +0.1 пункта.
    pred = float(np.mean([float(r["winrate"]) for _, r in chosen]))
    pred_low = float(np.mean([float(r["wilson_low"]) for _, r in chosen]))

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
            f"Среднее winrate пяти пиков на их ролях, все роли с равным весом. "
            f"Осторожная оценка с поправкой на размер выборки: {pred_low:.0%}. "
            "Отдельно проверяем, сбалансирован ли состав — есть ли танк или боец, "
            "урон и поддержка."
        )
    with right:
        st.markdown("#### Вклад каждой роли")
        html = "".join(_card(rk_ru, r, imgs) for rk_ru, r in chosen)
        st.markdown(html, unsafe_allow_html=True)

    _backtest(source)

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
    rad = roles_df.set_index("role_key")
    rad = rad.reindex([rk for rk, _ in ROLES if rk in rad.index])   # порядок как в ROLES
    radar_grid(rad, [("kda", "KDA"), ("cs", "CS"), ("dmg", "Урон"),
                     ("vision", "Обзор"), ("gold", "Золото")], titles=dict(ROLES))
