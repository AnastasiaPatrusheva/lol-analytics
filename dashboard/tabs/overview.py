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

from dashboard.data import run, table_exists
from dashboard.tabs.composition import SIDE_NOM
from dashboard.tabs.quality import sample_facts
from dashboard.tabs.strength import (
    ALL_SLICE, ROLE_RU, _plural, aggregation_effect, duration_shift, role_gap_example,
    role_gap_text,
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


def _num(x: float) -> str:
    """Целое с пробелом в разрядах: 25 947."""
    return f"{int(x):,}".replace(",", " ")


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
            "Чемпионов, которые заметно сильнее остальных, нет",
            f"Все {int(pooled['champions'])} чемпиона выигрывают примерно половину матчей. "
            "Ни один не отрывается от половины настолько, чтобы это нельзя было объяснить "
            "везением в тех матчах, что попали в выборку.",
        )
    else:
        _card(
            "Сила чемпиона",
            f"Заметно выделяются {int(pooled['marked'])} из {int(pooled['champions'])} чемпионов",
            f"Чаще половины побеждают {int(pooled['strong'])}, реже — {int(pooled['weak'])}. "
            "Остальные от половины неотличимы.",
        )

    if marked_in_roles > int(pooled["marked"]):
        # Пример берём из данных: доли по ролям складываются не поровну, а с весом
        # по числу игр, и выдуманные числа в таком примере почти наверняка не сойдутся.
        ex = role_gap_example(source, "", MIN_GAMES)
        if ex:
            why = f"Вот как это выглядит: {role_gap_text(ex)} — чемпион выглядит обычным."
        else:
            why = ("Причина в усреднении: одного чемпиона играют на разных позициях, "
                   "и разные доли побед сливаются в одну, близкую к половине.")
        _card(
            "Сила чемпиона",
            "Но это говорит о способе подсчёта, а не об игре",
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
    gen = _plural(n, "чемпиона", "чемпионов", "чемпионов")
    typical = round(float(dur["delta"].abs().median()) * 100)
    typical_text = (f"У обычного чемпиона разница около {typical} "
                    f"{_plural(typical, 'пункта', 'пунктов', 'пунктов')}.")
    why = ("Только причину отсюда не вывести: короткие матчи — это в основном разгромы, "
           "поэтому проигрыши чемпионов, сильных в поздней игре, попадают туда сами собой.")
    sig = dur[dur["is_sig"]]
    if sig.empty:
        _card(
            "Сила чемпиона",
            "Длина матча почти не меняет силу чемпионов",
            f"Ни у одного из {n} {gen} доли побед в коротких и длинных матчах не "
            f"расходятся сильнее, чем можно списать на случайность. {typical_text}",
        )
        return
    r = sig.loc[sig["delta"].abs().idxmax()]
    _card(
        "Сила чемпиона",
        f"Длина матча заметно важна только для {len(sig)} из {n} {gen}",
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
        "Победа даёт предмет, а не предмет победу",
        f"У предмета {r['item_name']} {r['winrate']:.0%} побед на {_num(r['appearances'])} "
        "сборках, но покупать его от этого не стоит. Riot сохраняет только то, что лежало "
        "в сумке в конце матча. Дорогую вещь успевает достроить тот, кто дольше живёт, "
        "то есть тот, кто и так выигрывает.",
    )


def _backtest_finding(source: str) -> None:
    """Вывод 5: прогноз по чемпионам против простого правила «побеждает сторона»."""
    if not table_exists("composition_backtest"):
        return
    df = run(f"SELECT * FROM composition_backtest WHERE data_source = '{source}'")
    if df.empty or "accuracy_sideonly" not in df.columns:
        return
    r = df.iloc[0]
    acc, side_acc = float(r["accuracy_raw"]), float(r["accuracy_sideonly"])
    weak = int(r["weak_side"])
    strong_nom = SIDE_NOM[300 - weak]
    weak_gen = {100: "синих", 200: "красных"}[weak]
    verdict = ("Одних чемпионов мало, чтобы угадать победителя" if acc <= side_acc else
               "Чемпионы угадывают победителя лучше, чем сторона карты")
    _card(
        "Состав",
        verdict,
        f"Прогноз по чемпионам проверили на {_num(r['test_matches'])} матчах патча "
        f"{r['test_patch']}, которых расчёт не видел. Он угадал {acc:.1%} матчей, а правило "
        f"«всегда побеждают {strong_nom}», в котором чемпионов нет вовсе, — {side_acc:.1%}. "
        f"Чемпионы всё же влияют: у {weak_gen} {float(r['weak_side_fav_wr']):.1%} побед, "
        f"когда чемпионы сильнее у них, и {float(r['weak_side_unfav_wr']):.1%}, когда "
        "у соперника. Но сторона карты в этой выборке значит больше, и почему, "
        "мы не выяснили.",
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
        f"Если сравнивать каждого игрока не со всеми подряд, а со своей же ролью, "
        f"получаются {len(df)} группы. У «{best['archetype']}» {best['wr']:.0%} побед, "
        f"у «{worst['archetype']}» — {worst['wr']:.0%}. Приписывать разницу одному стилю "
        "нельзя: группы отличаются ещё и уровнем самих игроков, а разделить одно "
        "от другого здесь нечем.",
    )


def _about_count(n: int) -> str:
    """«26 тысяч» для больших наборов, точное число для маленьких."""
    if n < 1000:
        return f"{n} {_plural(n, 'рейтинговый матч', 'рейтинговых матча', 'рейтинговых матчей')}"
    k = round(n / 1000)
    return f"{k} {_plural(k, 'тысяча', 'тысячи', 'тысяч')} рейтинговых матчей"


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
    c1.metric("Матчей", _num(kpi["matches"]))
    c2.metric("Игроков", _num(kpi["players"]))
    c3.metric("Чемпионов", int(kpi["champions"]))
    c4.metric("Матч в среднем", f"{span['avg_min']:.0f} мин",
              help="Средняя длительность одного матча в этой выборке")

    st.markdown("#### Что показали данные")
    # Патчи с 20+ матчами (см. sample_facts): три залётных матча из 16.1 превращали
    # «16.7–16.12» в «7 патчей».
    n_p = len(facts["patches"])
    where = " из Западной Европы" if facts["region"] == "EUW1" else ""
    # Число матчей здесь не повторяем: оно уже во вступлении и в карточке «Матчей».
    st.caption(
        f"Выводы посчитаны по набору «{source}»: рейтинговые одиночные матчи"
        f"{where} за {n_p} {_plural(n_p, 'патч', 'патча', 'патчей')}, "
        f"с {facts['first']:%d.%m.%Y} по {facts['last']:%d.%m.%Y}. Другой набор можно "
        "выбрать в панели «Фильтры» слева. Числа в тексте считаются из данных, а не "
        "вписаны вручную. Мелкая подпись над каждым выводом говорит, на какой вкладке он "
        "разобран подробно."
    )

    _strength_findings(source)
    _duration_finding(source)
    _item_finding(source)
    _backtest_finding(source)
    _segments_finding(source)

    tiers = set(run(f"SELECT DISTINCT source_tier FROM dim_match "
                    f"WHERE data_source = '{source}'")["source_tier"])
    who = ("Данные собраны по игрокам верхней части рейтинга (Challenger, Grandmaster, "
           "Master), поэтому всё сказанное относится к ним, а не к обычному игроку."
           if tiers <= {"challenger", "grandmaster", "master"} else
           "Рангов игроков в этом наборе нет, поэтому неизвестно, насколько выводы "
           "подходят для обычного игрока.")
    st.info(
        f"**О чём эти выводы не говорят.** {who} Остальные оговорки собраны на вкладке "
        "«Данные и качество».",
        icon="🧭",
    )
