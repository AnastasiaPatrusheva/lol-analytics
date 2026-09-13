"""Вкладка «Состав»: прикидка доли побед командного состава и её проверка.

Не ML: оценка — среднее winrate пяти чемпионов на их ролях, все роли поровну.
Как выбирали формулу и с чем сравнивать прогноз, считает
scripts/build_composition_backtest.py (витрины composition_backtest и
composition_calibration).
"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.charts import radar_grid
from dashboard.data import run, champion_images, table_exists
from dashboard.tabs.strength import _plural

ROLES = [("TOP", "Топ"), ("JUNGLE", "Лес"), ("MIDDLE", "Мид"),
         ("BOTTOM", "Бот"), ("UTILITY", "Саппорт")]

# Стороны карты в Riot API: 100 — синие, 200 — красные.
SIDE_NOM = {100: "синие", 200: "красные"}

# Грубая группировка классов Data Dragon для заметки о балансе.
FRONTLINE = {"Tank", "Fighter"}
DAMAGE = {"Marksman", "Mage", "Assassin"}
SUPPORT_CLS = {"Support"}


def _card(rk_ru, row, imgs):
    img = imgs.get(int(row["champion_id"]), "")
    pic = (f"<img src='{img}' style='width:40px;height:40px;border-radius:8px;"
           f"border:1px solid #2f3a4d;flex:none'>") if img else ""
    wr = float(row["winrate"])
    games = int(row["games"])
    color = "#C8AA6E" if wr >= 0.5 else "#d9534f"
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:10px;"
        "padding:9px 13px;display:flex;gap:11px;align-items:center;margin-bottom:7px'>"
        f"{pic}<div style='flex:1;min-width:0'>"
        f"<div style='font-weight:600;color:#F0E6D2'>{rk_ru} — {row['champion_name']}</div>"
        f"<div style='font-size:12px;color:#a49b86'>{games} "
        f"{_plural(games, 'игра', 'игры', 'игр')} на этой роли</div></div>"
        f"<div style='color:{color};font-weight:600'>{wr:.1%} побед</div></div>"
    )


def _backtest(source: str) -> None:
    """Результат проверки прогноза на реальных командах (витрина composition_backtest)."""
    st.divider()
    st.markdown("#### Проверка прогноза: а он вообще работает?")
    if not table_exists("composition_backtest"):
        st.info("Проверка не построена: запустите `python main.py backtest`.")
        return
    bt = run(f"SELECT * FROM composition_backtest WHERE data_source = '{source}'")
    if bt.empty or "accuracy_sideonly" not in bt.columns:
        st.info(
            f"Для источника «{source}» проверку провести не на чем: нужен хотя бы один "
            "прошлый патч, чтобы посчитать оценки, и достаточно матчей в последнем, чтобы "
            "проверить. Выберите **riot_full** в панели «Фильтры» слева."
        )
        return

    r = bt.iloc[0]
    patch = r["test_patch"]
    n_matches = f"{int(r['test_matches']):,}".replace(",", " ")
    st.caption(
        f"Проверка простая. Матчи последнего патча, {patch} ({n_matches} "
        f"{_plural(int(r['test_matches']), 'матч', 'матча', 'матчей')}), в расчёт не брали. "
        "Оценки составов посчитали по более ранним патчам и посмотрели, угадывают ли они "
        f"победителей в {patch}. Взяли именно последний патч, потому что в жизни так же: "
        "считают по прошлому, а сбывается или нет, видно в будущих матчах. В каждом матче "
        "победителем называем команду с оценкой выше."
    )

    # Точка отсчёта — не 50%, а сторона карты. Стороны не равны, и правило «всегда
    # побеждает сторона, которая чаще выигрывала в прошлых патчах» угадывает больше
    # половины, ни разу не взглянув на чемпионов.
    weak = int(r["weak_side"])
    strong = 300 - weak
    weak_wr = float(r["weak_side_wr"])
    st.markdown("**С чем сравнивать**")
    st.markdown(
        "Кажется, что вслепую победителя можно угадать в половине матчей: команд две, "
        "выигрывает одна. Но стороны карты не равны. Команда, чья база в нижнем левом углу, "
        "называется синей, в верхнем правом — красной. "
        f"В матчах патча {patch} {SIDE_NOM[strong]} выиграли {1 - weak_wr:.1%}, "
        f"{SIDE_NOM[weak]} — {weak_wr:.1%}. Значит, правило «всегда побеждают "
        f"{SIDE_NOM[strong]}», в котором нет ни одного чемпиона, уже угадывает больше "
        "половины. Прогноз должен обыграть это правило, а не 50%."
    )
    if strong == 200 and 1 - weak_wr > 0.51:
        st.caption(
            "Обычно бывает наоборот: в рейтинговых играх чуть чаще, примерно в 51% матчей, "
            "выигрывают синие. Мы проверили, что стороны не перепутаны при обработке: в "
            "исходных файлах Riot перекос тот же. Установить причину по этим данным не "
            "удалось, подробнее на вкладке «Данные и качество»."
        )

    acc = float(r["accuracy_raw"])
    side_acc = float(r["accuracy_sideonly"])
    m1, m2, m3 = st.columns(3)
    m1.metric("Прогноз по чемпионам угадал", f"{acc:.1%}",
              # разница показанных округлённых чисел, иначе 52.5 и 54.1 дают «−1.7»
              delta=f"{round(acc * 100, 1) - round(side_acc * 100, 1):+.1f} пункта "
                    "к правилу стороны",
              help="В скольких матчах команда с более высокой оценкой действительно победила.")
    m2.metric(f"Правило «всегда {SIDE_NOM[strong]}» угадало", f"{side_acc:.1%}",
              help=f"Доля матчей патча {patch}, которые выиграли {SIDE_NOM[strong]}.")
    m3.metric("Завышает или занижает", f"{float(r['bias_raw']) * 100:+.1f} пункта",
              help="На сколько обещанный процент побед в среднем расходится с тем, "
                   "что случилось на самом деле. Ноль — обещание сбывается.")

    fav, unfav = float(r["weak_side_fav_wr"]), float(r["weak_side_unfav_wr"])
    weak_gen = {100: "синих", 200: "красных"}[weak]
    st.markdown("**Влияют ли чемпионы вообще**")
    st.markdown(
        f"Да, но слабо. Возьмём {weak_gen}, которые в этой выборке проигрывают чаще, "
        "и разделим их матчи по тому, у кого по нашей оценке чемпионы сильнее."
    )
    s1, s2, s3 = st.columns(3)
    s1.metric(f"{SIDE_NOM[weak].capitalize()} выигрывают в среднем", f"{weak_wr:.1%}")
    n_fav, n_unfav = int(r["weak_side_fav_matches"]), int(r["weak_side_unfav_matches"])
    s2.metric(f"…когда чемпионы сильнее у {weak_gen}", f"{fav:.1%}",
              help=f"{n_fav} {_plural(n_fav, 'матч', 'матча', 'матчей')}")
    s3.metric("…когда сильнее у соперника", f"{unfav:.1%}",
              help=f"{n_unfav} {_plural(n_unfav, 'матч', 'матча', 'матчей')}")
    tail = (f"Но даже с более сильными чемпионами {SIDE_NOM[weak]} выигрывают меньше "
            "половины матчей, поэтому фаворит почти всегда тот же, что и без чемпионов."
            if fav < 0.5 else
            f"И с более сильными чемпионами {SIDE_NOM[weak]} уже выигрывают больше половины.")
    st.caption(
        f"Разница между этими случаями — {round(fav * 100, 1) - round(unfav * 100, 1):.1f} "
        "пункта. На таком числе "
        f"матчей это не случайность. {tail}"
    )

    st.warning(
        "**Одних чемпионов мало, чтобы угадать победителя.** Выбор чемпионов сдвигает "
        "шансы на несколько пунктов, а сторона карты в этой выборке значит больше. Многое "
        "из того, что решает матч, в расчёт вообще не попадает: как играют люди и кого "
        "выбрал соперник. Ставить на конкретный матч по этой оценке нельзя.",
        icon="⚠️",
    )

    with st.expander("Почему число в карточке считаем именно так: сравнили три способа"):
        under = abs(float(r["bias_equal"])) * 100
        st.markdown(
            "Мы пробовали три способа посчитать число в карточке наверху (например, «51%») "
            f"и проверили каждый на матчах патча {patch}."
        )
        variants = pd.DataFrame([
            {"Как считаем оценку": "Простая доля побед, все роли поровну",
             "Угадано": r["accuracy_raw"], "Уверенность": r["auc_raw"],
             "Расхождение": r["bias_raw"]},
            {"Как считаем оценку": "Осторожная оценка, все роли поровну",
             "Угадано": r["accuracy_equal"], "Уверенность": r["auc_equal"],
             "Расхождение": r["bias_equal"]},
            {"Как считаем оценку": "Осторожная оценка, вес по числу игр",
             "Угадано": r["accuracy_weighted"], "Уверенность": r["auc_weighted"],
             "Расхождение": r["bias_weighted"]},
        ])
        st.dataframe(
            variants, hide_index=True, width="stretch",
            column_config={
                "Угадано": st.column_config.NumberColumn(
                    format="percent", help="Доля матчей, где победила команда с оценкой выше"),
                "Уверенность": st.column_config.NumberColumn(
                    format="%.3f", help="Насколько уверенно способ отличает будущих "
                                        "победителей от проигравших: 0.5 — не отличает, "
                                        "1.0 — не ошибается. Специалистам: ROC AUC"),
                "Расхождение": st.column_config.NumberColumn(
                    format="percent", help="Насколько обещанный процент разошёлся с фактом"),
            },
        )
        worst = min(("raw", "equal", "weighted"), key=lambda t: float(r[f"accuracy_{t}"]))
        weighted_note = (
            "- **Вес по числу игр** угадывает победителя реже остальных. Число игр говорит, "
            "насколько надёжно мы знаем чемпиона, а не насколько важна его роль в матче, "
            "и состав перекашивает в сторону популярных героев.\n"
            if worst == "weighted" else ""
        )
        st.markdown(
            "- **Простая доля побед:** если карточка говорит 51%, такие команды на деле и "
            "выигрывают примерно 51 матч из 100.\n"
            f"- **Осторожная оценка:** в среднем показывает примерно на {under:.0f} "
            f"{_plural(round(under), 'пункт', 'пункта', 'пунктов')} меньше, чем выходит на "
            f"деле. Написано {51 - round(under)}%, а команды выигрывают 51%.\n"
            + weighted_note +
            "\nПосетитель смотрит на число в карточке, поэтому выбрали способ, у которого "
            "это число правдивое."
        )

    calib = run(f"""
        SELECT * FROM composition_calibration
        WHERE data_source = '{source}' AND variant = 'Точечный winrate'
        ORDER BY bin_low
    """)
    if calib.empty:
        return
    n_bins = len(calib)
    st.markdown("**Сбывается ли обещанный процент**")
    st.caption(
        f"Все команды разложены на {n_bins} {_plural(n_bins, 'группу', 'группы', 'групп')}: "
        "от тех, кому прогноз обещал меньше всего побед, до тех, кому больше всего. "
        "По горизонтали — что было обещано, по вертикали — что вышло на самом деле. Если "
        "точка лежит на пунктирной линии, обещание сбылось в точности. Выше линии — "
        "команды выиграли чаще обещанного, ниже — реже."
    )
    lo = float(min(calib["predicted"].min(), calib["actual"].min())) - 0.01
    hi = float(max(calib["predicted"].max(), calib["actual"].max())) + 0.01
    scale = alt.Scale(domain=[lo, hi])
    pct_axis = alt.Axis(format=".0%", tickMinStep=0.01)   # одинаково по обеим осям
    diag = (alt.Chart(pd.DataFrame({"v": [lo, hi]}))
            .mark_line(strokeDash=[4, 4], color="#6b7580")
            .encode(x=alt.X("v:Q", scale=scale), y=alt.Y("v:Q", scale=scale)))
    dots = (
        alt.Chart(calib)
        .mark_circle(size=140, color="#C8AA6E", stroke="#141719", strokeWidth=0.5)
        .encode(
            x=alt.X("predicted:Q", title="Обещано побед", axis=pct_axis, scale=scale),
            y=alt.Y("actual:Q", title="Получилось на деле", axis=pct_axis, scale=scale),
            tooltip=[alt.Tooltip("predicted:Q", format=".1%", title="обещано"),
                     alt.Tooltip("actual:Q", format=".1%", title="на деле"),
                     alt.Tooltip("teams:Q", title="команд")],
        )
    )
    st.altair_chart((diag + dots).properties(height=340), width="stretch")


def render(source: str) -> None:
    st.subheader("Соберите состав")
    st.caption(
        "Выберите пять чемпионов, по одному на каждую роль. Для каждого мы знаем, какую "
        "долю матчей он выигрывал на этой роли, и показываем среднее по пятерым. Это "
        "прикидка по прошлым играм: исход конкретного матча она не предскажет. Насколько "
        "ей можно верить, проверено ниже."
    )

    df = run(f"""
        SELECT c.champion_name, c.champion_id, c.primary_class, f.role_key,
               COUNT(DISTINCT f.match_id) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
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
        "Один и тот же чемпион может быть в одних списках и отсутствовать в других: на роли "
        "мы показываем его, только если нашли там хотя бы 20 его матчей."
    )
    cols = st.columns(5)
    picks = {}
    taken = set()
    for (rk, rk_ru), col in zip(ROLES, cols):
        role_df = df[df["role_key"] == rk]
        opts = sorted(role_df["champion_name"].unique().tolist())
        if not opts:
            picks[rk] = None
            continue
        # По умолчанию — самый популярный на роли из ещё не взятых. Раньше стоял первый
        # по алфавиту, и Aatrox оказывался сразу на топе и в лесу.
        popular = [n for n in role_df.sort_values("games", ascending=False)["champion_name"]
                   if n not in taken]
        default = popular[0] if popular else opts[0]
        taken.add(default)
        picks[rk] = col.selectbox(rk_ru, opts, index=opts.index(default), key=f"compo_{rk}")

    names = [n for n in picks.values() if n]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        st.warning(
            f"{', '.join(dupes)} выбран(ы) сразу на нескольких ролях. В настоящем матче так "
            "нельзя: одного чемпиона в команде может взять только один игрок.",
            icon="⚠️",
        )

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

    # Прогноз: среднее winrate пяти пиков, все роли с равным весом. Почему не вес по
    # числу игр и не нижняя граница Уилсона — показывает проверка ниже (раскрывашка
    # «сравнили три способа»): первый хуже угадывает, вторая занижает итог.
    pred = float(np.mean([float(r["winrate"]) for _, r in chosen]))

    classes = {c for _, r in chosen for c in str(r["primary_class"]).split(",")}
    has_front = bool(classes & FRONTLINE)
    has_dmg = bool(classes & DAMAGE)
    # Раньше «поддержкой» считался любой выбор в списке «Саппорт», а там всегда кто-то
    # выбран, и предупреждение не появлялось никогда. Смотрим на класс чемпиона.
    has_supp = bool(classes & SUPPORT_CLS)
    balance = (
        "Сбалансированный состав: есть фронтлайн, урон и поддержка."
        if has_front and has_dmg and has_supp else
        "Состав однобокий: " + ", ".join(
            x for x, ok in [("нет фронтлайна", not has_front),
                            ("нет урона", not has_dmg),
                            ("нет поддержки", not has_supp)] if ok
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
            "Средняя доля побед пяти выбранных чемпионов на их ролях, все роли считаются "
            "поровну. Отдельно смотрим, сбалансирован ли состав: есть ли кому держать удар "
            "(фронтлайн), кому наносить урон и кому поддерживать."
        )
    with right:
        st.markdown("#### Ваша пятёрка")
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
               -- KDA суммарно за все матчи, как в словаре: среднее KDA отдельных игр
               -- раздувают матчи без смертей
               (SUM(f.kills) + SUM(f.assists)) * 1.0 / GREATEST(SUM(f.deaths), 1) AS kda,
               AVG(f.cs_per_min) AS cs,
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
