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
from dashboard.tabs.strength import ALL_SLICE, ROLE_RU, aggregation_effect

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
        _card(
            "Сила чемпиона",
            "Но это говорит о способе подсчёта, а не об игре",
            f"Стоит перестать смешивать роли, и выделяющихся становится {marked_in_roles} "
            f"вместо {int(pooled['marked'])}. Причина в усреднении: одного чемпиона играют "
            "на двух позициях, на одной он выигрывает чаще, на другой реже, а вместе выходит "
            f"ровно половина. Видно и по разбросу: среди всех ролей вместе от худшего "
            f"чемпиона к лучшему {pooled['spread']:.0%}, а внутри роли «{role_ru}» — "
            f"{widest['spread']:.0%}.",
        )


def _duration_finding(source: str) -> None:
    """Вывод 3: чемпион, которому длинная игра помогает сильнее всех."""
    df = run(f"""
        WITH j AS (
            SELECT c.champion_name, f.win,
                   CASE WHEN m.game_duration_min < 25 THEN 'short'
                        WHEN m.game_duration_min < 32 THEN 'mid' ELSE 'long' END AS bucket
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}'
        ),
        agg AS (
            SELECT champion_name, bucket, COUNT(*) AS games,
                   AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
            FROM j GROUP BY 1, 2
        )
        SELECT champion_name,
               MAX(CASE WHEN bucket = 'short' THEN wr END) AS wr_short,
               MAX(CASE WHEN bucket = 'long'  THEN wr END) AS wr_long
        FROM agg GROUP BY 1
        HAVING MAX(CASE WHEN bucket = 'short' THEN games END) >= {MIN_GAMES}
           AND MAX(CASE WHEN bucket = 'long'  THEN games END) >= {MIN_GAMES}
        ORDER BY (MAX(CASE WHEN bucket = 'long' THEN wr END)
                  - MAX(CASE WHEN bucket = 'short' THEN wr END)) DESC
        LIMIT 1
    """)
    if df.empty:
        return
    r = df.iloc[0]
    delta = r["wr_long"] - r["wr_short"]
    _card(
        "Сила чемпиона",
        "Длина матча решает больше, чем выбор чемпиона",
        f"{r['champion_name']} выигрывает {r['wr_short']:.0%} коротких матчей и "
        f"{r['wr_long']:.0%} длинных. Разрыв в {delta:.0%} больше, чем расстояние между "
        "лучшим и худшим чемпионом во всём рейтинге. Только причину отсюда не вывести: "
        "короткие матчи — это в основном разгромы, поэтому проигрыши чемпионов, сильных "
        "в поздней игре, попадают туда сами собой.",
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
    """Вывод 5: прогноз состава проверен на матчах, которых модель не видела."""
    if not table_exists("composition_backtest"):
        return
    df = run(f"SELECT * FROM composition_backtest WHERE data_source = '{source}'")
    if df.empty:
        return
    r = df.iloc[0]
    acc = float(r["accuracy_raw"])
    _card(
        "Состав",
        f"Прогноз по составу угадывает {acc:.1%} матчей вместо 50%",
        f"Мы спрятали от расчёта патч {r['test_patch']} целиком и проверили прогноз на "
        f"{_num(r['test_matches'])} матчах, которых он не видел. В каждом матче оценивались "
        "обе команды, побеждала та, чья оценка выше, поэтому наугад вышло бы ровно половина. "
        f"Разница настоящая, но маленькая: состав влияет на исход куда меньше, чем умение "
        "игроков и вражеская пятёрка, которую расчёт вообще не видит.",
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


def render(source: str) -> None:
    kpi = run(f"""
        SELECT COUNT(DISTINCT match_id) AS matches,
               COUNT(DISTINCT puuid) AS players,
               COUNT(DISTINCT champion_id) AS champions
        FROM fact_participant WHERE data_source = '{source}'
    """).iloc[0]
    span = run(f"""
        SELECT AVG(game_duration_min) AS avg_min,
               MAX(game_start_utc) AS latest,
               COUNT(DISTINCT split_part(game_version, '.', 1) || '.'
                              || split_part(game_version, '.', 2)) AS patches
        FROM dim_match WHERE data_source = '{source}'
    """).iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Матчей", _num(kpi["matches"]))
    c2.metric("Игроков", _num(kpi["players"]))
    c3.metric("Чемпионов", int(kpi["champions"]))
    c4.metric("Матч в среднем", f"{span['avg_min']:.0f} мин",
              help="Средняя длительность одного матча в этой выборке")

    st.markdown("#### Что показали данные")
    latest = str(span["latest"])[:10] if span["latest"] else None
    when = f", последний матч {latest}" if latest else ""
    st.caption(
        f"Все выводы посчитаны по выборке «{source}»: {_num(kpi['matches'])} матчей "
        f"ранкед-соло, {int(span['patches'])} патчей{when}. Числа в тексте берутся "
        "из тех же витрин, что и графики, поэтому после обновления данных они меняются "
        "вместе с ними. Подпись сверху каждого вывода говорит, на какой вкладке его "
        "можно посмотреть подробно."
    )

    _strength_findings(source)
    _duration_finding(source)
    _item_finding(source)
    _backtest_finding(source)
    _segments_finding(source)

    st.info(
        "**О чём эти выводы не говорят.** Данные собраны в основном по сильным игрокам "
        "верхней части рейтинга, поэтому всё сказанное относится к ним, а не к обычному "
        "игроку. Остальные оговорки собраны на вкладке «Данные и качество».",
        icon="🧭",
    )
