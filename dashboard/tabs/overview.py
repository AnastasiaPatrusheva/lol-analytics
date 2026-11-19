"""Вкладка «Главное»: что выяснили, а не какие тут есть графики.

Раньше первый экран показывал лидеров по метрикам. Лидер — это максимум выборки,
он систематически завышен (у кого-то из многих обязательно окажется удачная серия),
и выводом быть не может.

ВАЖНО про числа. Все цифры в выводах считаются здесь же из витрин, а не вписаны
в текст. Прежняя версия держала семнадцать чисел прямо в строках, и одно из них
(«14 чемпионов выглядят сильными») уже разошлось с тем, что показывала вкладка
«Сила чемпиона» — там выходило 28. Текст над живыми данными обязан считать себя сам,
иначе он врёт после первой же пересборки. Там, где вывод может перевернуться
(значимые чемпионы появятся или исчезнут), формулировка тоже ветвится.
"""
import streamlit as st

from dashboard.data import fmt_int, load_backtest, plural, run, table_exists
from dashboard.tabs.composition import SIDE_GEN, SIDE_NOM
from dashboard.tabs.quality import sample_facts
from dashboard.tabs.segments import outcome_note
from dashboard.tabs.strength import (
    ALL_SLICE, ROLE_RU, aggregation_effect, duration_shift, role_gap_example, role_gap_text,
)

MIN_GAMES = 30          # тот же порог, что стоит по умолчанию на вкладке «Сила чемпиона»


def _card(topic: str, title: str, body: str) -> None:
    """Один вывод: где смотреть, сам вывод, доказательство."""
    st.markdown(
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-left:3px solid #C8AA6E;"
        "border-radius:10px;padding:14px 18px;margin-bottom:12px'>"
        "<div style='font-size:11px;color:#a49b86;text-transform:uppercase;"
        f"letter-spacing:.07em'>{topic}</div>"
        "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:18px;"
        f"font-weight:600;color:#F0E6D2;margin:3px 0 7px\">{title}</div>"
        f"<div style='font-size:14px;color:#cfd6d6;line-height:1.55'>{body}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _strength_findings(source: str) -> None:
    """Выводы 1 и 2: сила чемпиона и то, как её прячет усреднение."""
    eff = aggregation_effect(source, "", MIN_GAMES)
    if eff.empty:
        return
    eff = eff.assign(marked=eff["strong"] + eff["weak"],
                     spread=eff["wr_max"] - eff["wr_min"])
    pooled = eff[eff["slice"] == ALL_SLICE]
    by_role = eff[eff["slice"] != ALL_SLICE]
    if pooled.empty or by_role.empty:
        return
    pooled = pooled.iloc[0]
    # Роль, где разброс между чемпионами шире всего: на ней эффект виден лучше.
    widest = by_role.loc[by_role["spread"].idxmax()]
    role_ru = ROLE_RU.get(widest["slice"], widest["slice"])
    marked_in_roles = int(by_role["marked"].sum())

    if int(pooled["marked"]) == 0:
        _card(
            "Сила чемпиона",
            "В общем срезе отличий от 50% побед не обнаружено",
            f"Проверили {int(pooled['champions'])} чемпионов с поправкой на число проверок. "
            "Ни у одного отличие от половины побед не прошло этот порог. "
            "Равенство чемпионов из этого не следует.",
        )
    else:
        _card(
            "Сила чемпиона",
            f"Заметно выделяются {int(pooled['marked'])} из {int(pooled['champions'])} чемпионов",
            f"Чаще половины побеждают {int(pooled['strong'])}, реже — {int(pooled['weak'])}. "
            "У остальных отличие от половины побед не обнаружено.",
        )

    if marked_in_roles > int(pooled["marked"]):
        # Пример берём из данных: доли по ролям складываются не поровну, а с весом
        # по числу игр, и выдуманные числа в таком примере почти наверняка не сойдутся.
        ex = role_gap_example(source, "", MIN_GAMES)
        if ex:
            why = f"Вот как это выглядит: {role_gap_text(ex)}."
        else:
            why = ("Одна из возможных причин: одного чемпиона играют на разных позициях, "
                   "и разные доли побед сливаются в одну, близкую к половине.")
        _card(
            "Сила чемпиона",
            "Разрез по ролям показывает различия, скрытые в общем срезе",
            f"Стоит перестать смешивать роли, и выделяющихся становится {marked_in_roles} "
            f"вместо {int(pooled['marked'])}. {why} Видно и по разбросу: среди всех ролей "
            f"вместе от худшего чемпиона к лучшему {pooled['spread']:.0%}, а внутри роли "
            f"«{role_ru}» — {widest['spread']:.0%}.",
        )


def _duration_finding(source: str) -> None:
    """Вывод 3: для скольких чемпионов длина матча действительно меняет долю побед.

    Прежняя версия выносила в заголовок «длина решает больше, чем выбор чемпиона»
    по одному чемпиону с самым большим разрывом — это максимум выборки. У типичного
    чемпиона разрыв в разы меньше, поэтому вывод строится на счёте прошедших
    строгую проверку, а крайний чемпион остаётся примером.
    """
    dur = duration_shift(source, "", "", MIN_GAMES)
    if dur.empty:
        return
    n = len(dur)
    gen = plural(n, "чемпиона", "чемпионов", "чемпионов")
    typical = round(float(dur["delta"].abs().median()) * 100)
    typical_text = (f"У обычного чемпиона разница около {typical} "
                    f"{plural(typical, 'пункта', 'пунктов', 'пунктов')}.")
    why = ("Длительность зависит от хода матча и действий обеих команд. "
           "Причинный эффект длительности здесь не установлен.")
    sig = dur[dur["is_sig"]]
    if sig.empty:
        _card(
            "Сила чемпиона",
            "В этом разрезе различия долей побед не обнаружены",
            f"Ни у одного из {n} {gen} доли побед в коротких и длинных матчах не "
            f"расходятся сильнее, чем можно списать на случайность. {typical_text}",
        )
        return
    r = sig.loc[sig["delta"].abs().idxmax()]
    _card(
        "Сила чемпиона",
        f"Короткие и длинные матчи: различия обнаружены у {len(sig)} из {n} {gen}",
        f"Сильнее всех это видно у {r['champion_name']}: {r['wr_short']:.0%} побед в "
        f"коротких матчах и {r['wr_long']:.0%} в длинных. {typical_text} {why}",
    )


def _item_finding(source: str) -> None:
    """Вывод 4: дорогой предмет у победителей — следствие, а не причина."""
    df = run(f"""
        SELECT item_name, winrate, appearances FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= 2000 AND appearances >= 500
        ORDER BY winrate DESC LIMIT 1
    """)
    if df.empty:
        return
    r = df.iloc[0]
    _card(
        "Предметы",
        "Доля побед с предметом не доказывает его пользу",
        f"У предмета {r['item_name']} {r['winrate']:.0%} побед на {fmt_int(r['appearances'])} "
        "сборках. Riot сохраняет инвентарь на конец матча, без истории покупок. "
        "Связь может отражать ход матча, длительность и выбор игроков. Влияние самого "
        "предмета на победу по этой таблице определить нельзя.",
    )


def _backtest_finding(source: str) -> None:
    """Вывод 5: прогноз по чемпионам против простого правила «побеждает сторона»."""
    r = load_backtest(source)
    if r is None:
        return
    acc, side_acc = float(r["accuracy_raw"]), float(r["accuracy_sideonly"])
    weak = int(r["weak_side"])
    strong_nom = SIDE_NOM[300 - weak]
    weak_gen = SIDE_GEN[weak]
    verdict = ("Эта оценка составов уступает правилу стороны" if acc <= side_acc else
               "Эта оценка составов точнее правила стороны в проверенных матчах")
    _card(
        "Состав",
        verdict,
        f"Прогноз по чемпионам проверили на {fmt_int(r['test_matches'])} матчах патча "
        f"{r['test_patch']}. Оценки посчитаны по предыдущим патчам. Угадано {acc:.1%} матчей, а правило "
        f"«всегда побеждают {strong_nom}», в котором чемпионов нет вовсе, — {side_acc:.1%}. "
        f"Есть наблюдаемая связь: у {weak_gen} {float(r['weak_side_fav_wr']):.1%} побед, "
        f"когда оценка их чемпионов выше, и {float(r['weak_side_unfav_wr']):.1%}, когда ниже. "
        "Это не устанавливает причинный эффект выбора чемпионов. Варианты формулы "
        "сравнивались на этом же патче, поэтому независимая оценка ещё нужна.",
    )


def _segments_finding(source: str) -> None:
    """Вывод 6: осторожные игроки выигрывают чаще, но причина не только в стиле."""
    if not table_exists("player_segments"):
        return
    df = run(f"""
        SELECT archetype, COUNT(*) AS players, AVG(winrate) AS wr
        FROM player_segments WHERE data_source = '{source}'
        GROUP BY 1 HAVING COUNT(*) >= 50 ORDER BY wr DESC
    """)
    if len(df) < 2:
        return
    best, worst = df.iloc[0], df.iloc[-1]
    _card(
        "Игроки",
        f"Группа «{best['archetype']}» выигрывает чаще группы «{worst['archetype']}»",
        f"Сравниваем только матчи на основной роли каждого игрока. "
        f"Здесь показаны {len(df)} группы размером не меньше 50 игроков. У «{best['archetype']}» {best['wr']:.0%} побед, "
        f"у «{worst['archetype']}» — {worst['wr']:.0%}. Приписывать разницу одному стилю "
        "нельзя: группы отличаются ещё и уровнем самих игроков, а разделить одно "
        f"от другого здесь нечем. {outcome_note(source)}",
    )


def _about_count(n: int) -> str:
    """«26 тысяч» для больших наборов, точное число для маленьких."""
    if n < 1000:
        return f"{n} {plural(n, 'рейтинговый матч', 'рейтинговых матча', 'рейтинговых матчей')}"
    k = round(n / 1000)
    return f"{k} {plural(k, 'тысяча', 'тысячи', 'тысяч')} рейтинговых матчей"


def render(source: str) -> None:
    facts = sample_facts(source)
    st.markdown(
        "**League of Legends** — командная онлайн-игра: две команды по пять человек, у "
        "каждого свой персонаж (чемпион) и своя роль на карте, побеждает тот, кто первым "
        "разрушит базу соперника.\n\n"
        f"Здесь разобраны {_about_count(facts['matches'])}. Мы проверили на них то, что "
        "чаще всего интересует игроков:\n"
        "- есть ли чемпионы, которые действительно сильнее остальных;\n"
        "- помогают ли дорогие предметы победить;\n"
        "- какие стили игры встречаются у игроков;\n"
        "- можно ли угадать победителя по выбранным чемпионам.\n\n"
        "Ниже короткие ответы, подробный разбор — на остальных вкладках."
    )
    kpi = run(f"""
        SELECT COUNT(DISTINCT match_id) AS matches,
               COUNT(DISTINCT puuid) AS players,
               COUNT(DISTINCT champion_id) AS champions
        FROM fact_participant WHERE data_source = '{source}'
    """).iloc[0]
    span = run(f"""
        SELECT AVG(game_duration_min) AS avg_min
        FROM dim_match WHERE data_source = '{source}'
    """).iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Матчей", fmt_int(kpi["matches"]))
    c2.metric("Игроков", fmt_int(kpi["players"]))
    c3.metric("Чемпионов", int(kpi["champions"]))
    c4.metric("Матч в среднем", f"{span['avg_min']:.0f} мин",
              help="Средняя длительность одного матча в этой выборке")

    st.markdown("#### Что показали данные")
    where = " из Западной Европы" if facts["region"] == "EUW1" else ""
    period = ""
    if facts["patches"]:
        period = (f" Матчи основных патчей сыграны с {facts['first']:%d.%m.%Y} "
                  f"по {facts['last']:%d.%m.%Y}.")
    stray = facts["stray"]
    if not stray.empty:
        count = int(stray["n"].sum())
        patch_word = "патча" if len(stray) == 1 else "патчей"
        period += (f" В общих расчётах также учтены {count} "
                   f"{plural(count, 'матч', 'матча', 'матчей')} "
                   f"из {patch_word} {', '.join(stray['p'])}.")
    st.caption(
        f"Выводы посчитаны по набору «{source}», который содержит рейтинговые одиночные "
        f"матчи{where}.{period} Другой набор можно выбрать в панели «Фильтры» слева. "
        "Подпись над каждым выводом указывает вкладку с подробностями."
    )

    _strength_findings(source)
    _duration_finding(source)
    _item_finding(source)
    _backtest_finding(source)
    _segments_finding(source)

    who = ("Данные собраны по игрокам верхней части рейтинга (Challenger, Grandmaster, "
           "Master), поэтому всё сказанное относится к ним, а не к обычному игроку."
           if facts["top_only"] else
           "Рангов игроков в этом наборе нет, поэтому неизвестно, насколько выводы "
           "подходят для обычного игрока.")
    st.info(
        f"**О чём эти выводы не говорят.** {who} Остальные оговорки собраны на вкладке "
        "«Данные и качество».",
        icon="🧭",
    )
