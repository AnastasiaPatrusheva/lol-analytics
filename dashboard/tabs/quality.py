"""Вкладка «Данные и качество»: откуда цифры, чего они не показывают и как их проверяли.

Порядок — от того, что нужно любому читателю, к техническому: сначала что за
выборка и где её пределы, потом словарь, в конце отчёт проверок сборки.
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run
from dashboard.tabs.strength import _plural

# Отчёт стадии quality (scripts/run_data_quality.py) — проверки идут ДО фильтров
# звезды, поэтому именно они могут упасть на плохих данных.
DQ_REPORT = Path(__file__).resolve().parents[2] / "outputs" / "data_quality" / "data_quality_report.csv"

# Названия проверок в отчёте — технические ключи; на дашборде показываем по-русски.
CHECK_RU = {
    "not_empty": "Данные не пустые",
    "schema_columns": "Все поля на месте",
    "unique_participant_key": "Нет повторных записей",
    "keys_not_null": "Нет пустых ключей",
    "ten_participants_per_match": "В каждом матче 10 игроков",
    "team_id_values": "Сторона указана верно",
    "queue_is_ranked_solo": "Только рейтинговые одиночные игры",
    "non_negative_metrics": "Нет отрицательных чисел",
    "kda_finite": "KDA посчитан везде",
    "team_position_values": "Роли определены",
    "champion_id_in_reference": "Все чемпионы известны",
    "remake_share": "Мало ремейков",
    "freshness": "Данные свежие",
}
LEVEL_RU = {"ERROR": "Остановит сборку", "WARN": "Только предупредит"}


def _check_name(key: str) -> str:
    if key.startswith("win_balance["):
        return f"Побед ровно половина ({key[len('win_balance['):-1]})"
    return CHECK_RU.get(key, key)


def render(source: str) -> None:
    st.subheader("Данные и качество")
    st.caption(
        "Откуда взяты цифры, чего они не показывают, что означают термины и какие "
        "проверки прошли данные перед тем, как попасть на дашборд."
    )
    _sample(source)
    _limits(source)
    _glossary()
    _checks(source)


def _sample(source: str) -> None:
    """Что за выборка: факты одной строкой и длительность матчей."""
    st.markdown("#### Что за выборка")
    facts = run(f"""
        SELECT COUNT(*) AS matches,
               MIN(split_part(match_id, '_', 1)) FILTER (WHERE match_id LIKE '%\\_%' ESCAPE '\\')
                   AS region,
               string_agg(DISTINCT source_tier, ',') AS tiers
        FROM dim_match WHERE data_source = '{source}'
    """).iloc[0]
    by_patch = run(f"""
        SELECT split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2) AS p,
               COUNT(*) AS n, MIN(game_start_utc) AS first, MAX(game_start_utc) AS last
        FROM dim_match WHERE data_source = '{source}' AND game_version IS NOT NULL
        GROUP BY 1
    """)
    by_patch["key"] = by_patch["p"].map(lambda p: [int(x) for x in p.split(".") if x.isdigit()])
    by_patch = by_patch.sort_values("key")
    n = int(facts["matches"])
    # Патч, где меньше 20 матчей, — случайные залётные игры (в riot_full три матча из
    # 16.1). В общем списке они сдвигают начало данных на январь, поэтому называем их
    # отдельно. Порог в штуках, а не в долях: 1% от 26 тысяч отрезал настоящий патч 16.7.
    main = by_patch[by_patch["n"] >= 20]
    stray = by_patch[by_patch["n"] < 20]
    n_p = len(main)
    patch_text = ", ".join(main["p"]) + f" ({n_p} {_plural(n_p, 'патч', 'патча', 'патчей')})"
    if not stray.empty:
        k = int(stray["n"].sum())
        patch_text += (f"; ещё {k} {_plural(k, 'матч', 'матча', 'матчей')} из "
                       f"{', '.join(stray['p'])}, в расчётах они есть")
    first, last = main["first"].min(), main["last"].max()
    region = {"EUW1": "Западная Европа (EUW)"}.get(facts["region"], facts["region"]) \
        if facts["region"] else "не указан"
    known_tiers = sorted({t for t in str(facts["tiers"]).split(",")}
                         & {"challenger", "grandmaster", "master"})
    ranks = (", ".join(t.capitalize() for t in known_tiers) if known_tiers
             else "неизвестны, в данных их нет")
    st.markdown(
        f"- **Матчей:** {n:,}".replace(",", " ") + " рейтинговых одиночных игр\n"
        f"- **Патчи:** {patch_text}\n"
        f"- **Даты:** {first:%d.%m.%Y} — {last:%d.%m.%Y}\n"
        f"- **Регион:** {region}\n"
        f"- **Ранги игроков:** {ranks}\n"
        "- **Игроки не опознаются по номеру аккаунта.** Вместо постоянного номера "
        "аккаунта Riot хранится короткий код, вычисленный из него. Сам номер из кода не "
        "получить, а матчи одного игрока связать по-прежнему можно."
    )

    dur = run(f"""
        SELECT game_duration_min FROM dim_match
        WHERE data_source = '{source}' AND game_duration_min IS NOT NULL
    """)
    if dur.empty:
        return
    q1, med, q3 = (dur["game_duration_min"].quantile(0.25),
                   dur["game_duration_min"].median(),
                   dur["game_duration_min"].quantile(0.75))
    top = int(dur["game_duration_min"].max() // 5 + 1) * 5
    box = (
        alt.Chart(dur)
        .mark_boxplot(extent="min-max", size=40, color="#C8AA6E")
        .encode(x=alt.X("game_duration_min:Q", title="Длительность матча, мин",
                        axis=alt.Axis(values=list(range(0, top + 1, 5)))))
        .properties(height=140)
    )
    st.altair_chart(box, width="stretch")
    st.caption(
        f"Половина матчей длится примерно {q1:.0f}–{q3:.0f} мин (медиана {med:.0f}). "
        "«Коробка» — где лежит середина матчей, «усы» — самый короткий и самый длинный. "
        "Матчи короче 5 минут — ремейки: их отменяют, когда игрок не зашёл в игру или "
        "сразу вышел. На дашборд они не попадают."
    )


def _limits(source: str) -> None:
    st.divider()
    st.markdown("#### Чего эти данные не показывают")
    items = []
    red = run(f"""
        SELECT AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
        FROM fact_participant WHERE data_source = '{source}' AND team_id = 200
    """).iloc[0]
    if float(red["wr"]) > 0.51:
        # Необъяснённая странность выборки: пишем как есть, не выдавая догадку за причину.
        items.append(
            f"**Почему красные выигрывают заметно чаще синих.** В этой выборке команда с "
            f"базой в верхнем правом углу карты выиграла {float(red['wr']):.1%} матчей. "
            "Обычно бывает наоборот: в рейтинговых играх чуть чаще, примерно в 51% матчей, "
            "выигрывают синие. Стороны при обработке не перепутаны: в исходных файлах Riot "
            "перекос тот же. Причину установить не удалось, поэтому прогноз на вкладке "
            "«Состав» сравниваем не с 50%, а с правилом «всегда побеждают красные»."
        )
    tiers = run(f"SELECT DISTINCT source_tier FROM dim_match WHERE data_source = '{source}'")
    if set(tiers["source_tier"]) <= {"challenger", "grandmaster", "master"}:
        items.append(
            "**Как играет обычный игрок.** Здесь только верх рейтинга: Challenger, "
            "Grandmaster и Master. Выводы описывают сильнейших игроков."
        )
    else:
        items.append(
            "**Из каких рангов эти матчи.** В этом наборе нет рангов игроков, поэтому "
            "нельзя сказать, насколько выводы подходят для обычного игрока, а насколько "
            "только для сильных или слабых."
        )
    items += [
        "**Что игрок покупал.** Riot сохраняет только предметы в сумке на конец матча. "
        "Поэтому доля побед у предмета в основном показывает, что победитель прожил "
        "достаточно долго, чтобы его собрать.",
        "**Почему матч был длинным или коротким.** Длина матча — следствие игры, а не её "
        "причина: разгромы заканчиваются быстро.",
        "**Каким игрок был в день матча.** Ник и очки лиги записаны на день сбора. Если "
        "игрок сменил ник или поднялся в рейтинге, на дашборде будет только последнее "
        "состояние.",
        "**Точную границу «заметно / незаметно».** Один и тот же игрок встречается во "
        "многих матчах, а проверка на заметное отличие считает матчи независимыми. "
        "Поэтому эта граница примерная.",
    ]
    st.markdown("\n".join(f"- {x}" for x in items))


def _glossary() -> None:
    st.divider()
    st.markdown("#### Словарь")
    st.caption(
        "Здесь простыми словами то, что встречается на других вкладках. "
        "Названия методов даны в конце пункта — для тех, кому они что-то говорят."
    )
    st.markdown(
        "- **Winrate, он же доля побед** — сколько матчей из ста выиграно.\n"
        "- **Осторожная оценка побед** — заниженная нарочно. Пять побед из пяти дают "
        "100%, но верить такому нельзя: игр слишком мало. Чем меньше матчей сыграно, тем "
        "сильнее мы занижаем: 4 победы из 5 (80%) превращаются в 38%, а 54% на 800 играх — "
        "в 51%. Так наверх не всплывают случайные счастливчики. *(нижняя граница "
        "интервала Уилсона)*\n"
        "- **KDA** — все убийства и помощи, делённые на все смерти. Считаем суммарно за "
        "все матчи. Если усреднять KDA отдельных игр, одна игра без смертей даёт огромное "
        "число и перевешивает всё остальное.\n"
        "- **Что-то в минуту** (миньоны, урон, золото, обзор) — показатель, делённый на "
        "длину матча. Иначе игрок из сорокаминутной игры всегда выглядит лучше игрока "
        "из двадцатиминутной просто потому, что у него было больше времени.\n"
        "- **CS** — сколько миньонов (мелких существ, которые сами идут по линиям) игрок "
        "добил. За каждого дают золото.\n"
        "- **Обзор** — насколько игрок открывает карту для команды, в основном "
        "наблюдателями: их ставят на карту, и они показывают, что происходит рядом.\n"
        "- **Сторона карты** — синие или красные. База синих в нижнем левом углу карты, "
        "красных — в верхнем правом. Сторону назначает игра, сам игрок её не выбирает.\n"
        "- **Патч** — обновление игры. Riot выпускает их примерно раз в две недели и "
        "меняет силу чемпионов и предметов, поэтому матчи разных патчей не совсем "
        "одинаковы.\n"
        "- **Ремейк** — матч, отменённый в первые минуты, потому что кто-то не зашёл в "
        "игру. В расчёты не входит.\n"
        "- **Заметное отличие** — такое, которое трудно объяснить случайностью. "
        "Мы проверяем не одного чемпиона, а сразу всех, а когда проверок много, случайные "
        "совпадения неизбежны: у честной монетки в одной попытке из сотни выпадет "
        "подозрительно много орлов. Поэтому планка тем выше, чем больше сравнений. "
        "*(поправка Бонферрони, p-значение)*\n"
        "- **Ошибка выжившего** — когда причина и следствие меняются местами. Дорогой "
        "предмет чаще у победителей не потому, что он приносит победу, а потому что "
        "победитель дольше живёт и успевает его собрать.\n"
        "- **Архетип** — группа игроков со схожей манерой игры, найденная автоматически. "
        "Это не официальные категории Riot. Каждого игрока сравниваем с его же ролью, "
        "иначе вместо манеры игры находятся сами роли. *(кластеризация KMeans)*"
    )


def _checks(source: str) -> None:
    st.divider()
    st.markdown("#### Проверки при сборке данных")
    st.caption(
        "Прежде чем данные попадут на дашборд, они проходят набор проверок. Если не пройдена "
        "проверка из тех, что останавливают сборку, цифры на вкладках не обновляются: "
        "лучше показать вчерашние данные, чем сегодняшние с ошибкой. Отчёт один на все "
        "три источника сразу, фильтр слева на него не влияет."
    )
    if DQ_REPORT.exists():
        dq = pd.read_csv(DQ_REPORT)
        passed = dq["passed"].astype(bool)
        n_fail = int((~passed).sum())
        if n_fail == 0:
            st.success(f"Пройдены все {len(dq)} проверок последней сборки.")
        else:
            st.error(f"Не пройдено проверок: {n_fail} из {len(dq)}.")
        show = pd.DataFrame({
            "Проверка": dq["check"].map(_check_name),
            "Итог": passed.map({True: "✓", False: "⚠"}),
            "Если не пройдена": dq["severity"].map(LEVEL_RU).fillna(dq["severity"]),
            "Что нашли": dq["detail"],
        })
        # Высота под все строки: таблица короткая, прокрутка внутри неё прятала половину.
        st.dataframe(show, hide_index=True, width="stretch", height=35 * (len(show) + 1) + 3,
                     column_config={"Итог": st.column_config.TextColumn(width="small"),
                                    "Что нашли": st.column_config.TextColumn(width="large")})
    else:
        st.info("Отчёт проверок не найден: запустите `python main.py quality`.")

    # Те же инварианты, но уже по готовым данным выбранного источника: проверки сборки
    # идут до фильтров, а это — то, что реально читают вкладки.
    counts = run(f"""
        SELECT
          (SELECT COUNT(*) FROM (SELECT match_id FROM fact_participant
             WHERE data_source = '{source}' GROUP BY match_id HAVING COUNT(*) <> 10)) AS bad_size,
          (SELECT COUNT(*) FROM (SELECT match_id, participant_id FROM fact_participant
             WHERE data_source = '{source}' GROUP BY 1, 2 HAVING COUNT(*) > 1)) AS dups,
          (SELECT COUNT(*) FROM fact_participant f
             LEFT JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
             WHERE f.data_source = '{source}' AND m.match_id IS NULL) AS orphans
    """).iloc[0]
    bad = {k: int(counts[k]) for k in ("bad_size", "dups", "orphans")}
    line = (f"неполных матчей — {bad['bad_size']}, повторных записей — {bad['dups']}, "
            f"записей игрока без матча — {bad['orphans']}")
    if sum(bad.values()) == 0:
        st.caption(f"✓ Готовые данные источника «{source}»: {line}.")
    else:
        st.error(f"Готовые данные источника «{source}»: {line}.")
