"""Вкладка «Данные и качество»: откуда цифры, можно ли им верить и что они значат.

Собрана из бывших вкладок «Качество» и «О метриках». Обе отвечали на один вопрос —
насколько можно доверять числам на дашборде — и обе терялись в конце ряда.
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, table_with_download

# Отчёт стадии quality (scripts/run_data_quality.py) — проверки идут ДО фильтров
# звезды, поэтому именно они могут упасть на плохих данных.
DQ_REPORT = Path(__file__).resolve().parents[2] / "outputs" / "data_quality" / "data_quality_report.csv"


def _status(ok: bool, ok_text: str, bad_text: str) -> str:
    """Монохромный статус под тему: бирюзовая галочка / красный знак."""
    if ok:
        return f"<span style='color:#3fd0c9;font-weight:600'>✓ {ok_text}</span>"
    return f"<span style='color:#d9534f;font-weight:600'>⚠ {bad_text}</span>"


def render(source: str) -> None:
    st.subheader("Данные и качество")
    st.caption(
        "Основания, на которых держится всё остальное: что за выборка, какие проверки "
        "она прошла, что означает каждая метрика и где выводы упираются в ограничения."
    )

    st.markdown("#### Проверки пайплайна")
    st.caption(
        "Эти проверки выполняются на стадии `quality`, до сборки звезды, и при ошибке "
        "останавливают пайплайн: витрины просто не пересоберутся. Здесь показан отчёт "
        "последнего прогона."
    )
    if DQ_REPORT.exists():
        dq = pd.read_csv(DQ_REPORT)
        n_fail = int((~dq["passed"].astype(bool)).sum())
        if n_fail == 0:
            st.success(f"Пройдены все {len(dq)} проверок последнего прогона.")
        else:
            st.error(f"Не пройдено проверок: {n_fail} из {len(dq)}.")
        show = dq.assign(passed=dq["passed"].astype(bool).map({True: "✓", False: "⚠"})).rename(
            columns={"check": "Проверка", "passed": "Итог",
                     "severity": "Уровень", "detail": "Детали"})
        st.dataframe(show, hide_index=True, width="stretch")
    else:
        st.info("Отчёт проверок не найден: запустите `python main.py quality`.")

    st.divider()
    st.markdown("#### Живые проверки витрин")
    st.caption(
        "А это проверки поверх готовой звезды. Первые три по построению должны быть "
        "нулевыми: в витрины попадают только полные матчи. Они нужны как контроль "
        "самой сборки, а не данных, и их «ок» не заменяет отчёт выше."
    )

    dist = run(f"""
        SELECT participants, COUNT(*) AS matches FROM (
            SELECT match_id, COUNT(*) AS participants
            FROM fact_participant WHERE data_source = '{source}' GROUP BY match_id
        ) GROUP BY participants ORDER BY participants
    """)
    bad_size = int(dist[dist["participants"] != 10]["matches"].sum()) if not dist.empty else 0

    dups = int(run(f"""
        SELECT COUNT(*) AS d FROM (
            SELECT match_id, participant_id FROM fact_participant
            WHERE data_source = '{source}'
            GROUP BY match_id, participant_id HAVING COUNT(*) > 1
        )
    """).iloc[0]["d"])

    orphans = int(run(f"""
        SELECT COUNT(*) AS o
        FROM fact_participant f
        LEFT JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
        WHERE f.data_source = '{source}' AND m.match_id IS NULL
    """).iloc[0]["o"])

    wr = float(run(f"""
        SELECT AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
        FROM fact_participant WHERE data_source = '{source}'
    """).iloc[0]["wr"])

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Матчей не по 10", bad_size, help="В полном матче ровно 10 участников. Норма — 0.")
    q1.markdown(_status(bad_size == 0, "ок", "есть неполные"), unsafe_allow_html=True)
    q2.metric("Дубли записей", dups, help="Повторная запись одного игрока в матче. Норма — 0.")
    q2.markdown(_status(dups == 0, "ок", "есть дубли"), unsafe_allow_html=True)
    q3.metric("Строки-сироты", orphans, help="Запись игрока без привязки к матчу. Норма — 0.")
    q3.markdown(_status(orphans == 0, "ок", "есть сироты"), unsafe_allow_html=True)
    q4.metric("Ср. winrate", f"{wr:.3f}", help="Должен быть ≈0.500: в матче 5 побед и 5 поражений.")
    q4.markdown(_status(abs(wr - 0.5) <= 0.01, "ок", "дисбаланс"), unsafe_allow_html=True)

    dist_disp = dist.rename(columns={"participants": "Участников", "matches": "Матчей"})
    table_with_download(dist_disp, "Участников на матч", "participants_per_match.csv",
                        key="dl_quality",
                        caption="Ожидаем ровно один столбец — «10».")

    _sample(source)
    _glossary()
    _limits()


def _sample(source: str) -> None:
    """Описание выборки: сколько данных и какой они формы."""
    st.divider()
    st.markdown("#### Что за выборка")
    dur = run(f"""
        SELECT game_duration_min FROM dim_match
        WHERE data_source = '{source}' AND game_duration_min IS NOT NULL
    """)
    if dur.empty:
        return
    q1, med, q3 = (dur["game_duration_min"].quantile(0.25),
                   dur["game_duration_min"].median(),
                   dur["game_duration_min"].quantile(0.75))
    box = (
        alt.Chart(dur)
        .mark_boxplot(extent="min-max", size=40, color="#C8AA6E")
        .encode(x=alt.X("game_duration_min:Q", title="Длительность матча, мин"))
        .properties(height=140)
    )
    st.altair_chart(box, width="stretch")
    st.caption(
        f"Половина матчей длится примерно {q1:.0f}–{q3:.0f} мин (медиана {med:.0f}). "
        "«Коробка» — где лежит середина матчей, «усы» — общий разброс. "
        "Матчи короче 5 минут это ремейки (отмена из-за выхода игрока), они отфильтрованы "
        "при сборке и сюда не попадают."
    )


def _glossary() -> None:
    st.divider()
    st.markdown("#### Словарь метрик")
    st.markdown(
        "- **Winrate** — доля побед.\n"
        "- **Winrate с поправкой на число игр** — не «сырой» процент побед, а намеренно "
        "заниженная (осторожная) оценка с учётом числа игр: берётся **нижняя граница "
        "интервала Уилсона**, нижний край диапазона, где реально может лежать winrate. "
        "Чем меньше игр, тем сильнее занижение: 70% на 5 играх (скорее везение) "
        "опускаются ниже стабильных 54% на 800 играх.\n"
        "- **KDA** — (убийства + помощи) ÷ смерти. Считается по сумме за все матчи, "
        "а не как среднее KDA отдельных игр: иначе редкие матчи без смертей дают "
        "огромные значения и тянут среднее вверх.\n"
        "- **… в минуту** (CS, урон, золото, обзор) — значение, делённое на длину матча: "
        "так сравнимы игроки из коротких и длинных игр.\n"
        "- **p-значение** — насколько вероятно, что различие случайно.\n"
        "- **Поправка Бонферрони** — когда проверяешь не одну гипотезу, а сразу 170, "
        "часть «значимых» находок появится случайно. Поправка делит порог значимости "
        "на число проверок, поэтому 5% относятся ко всему набору, а не к каждой проверке.\n"
        "- **Архетип** — группа игроков со схожей манерой игры, найденная кластеризацией. "
        "Не официальная категория Riot. Метрики нормированы на среднюю по роли игрока."
    )

    st.markdown("#### Как пользоваться")
    st.markdown(
        "- **Источник данных** (панель «Фильтры» слева) переключает набор: `riot_full` "
        "(большой архив, 7 патчей), `kaggle` (исторический срез), `riot_api` (своя свежая "
        "выборка). Весь дашборд пересчитывается под выбранный источник; источники "
        "**не смешиваются**.\n"
        "- **⟳ Обновить данные** — сбросить кэш, если данные пересобрали.\n"
        "- **🗎 Скачать CSV** — в шапке каждой таблицы; график сохраняется в PNG через "
        "меню «⋯» в его правом верхнем углу."
    )


def _limits() -> None:
    st.divider()
    st.markdown("#### Где эти данные врут")
    st.markdown(
        "- **Выборка смещена в сторону высоких рангов.** Выводы описывают верхнюю часть "
        "ладдера, а не среднего игрока.\n"
        "- **Инвентарь — не покупки.** Riot отдаёт предметы на конец матча, поэтому "
        "winrate предмета в основном отражает то, что победители дожили до его сборки.\n"
        "- **Длина матча — следствие, а не фактор.** Разгромные игры заканчиваются быстро.\n"
        "- **Нет историчности.** Ник и очки лиги игрока хранятся одним снимком, а не на "
        "момент каждого матча, хотя данные охватывают 7 патчей.\n"
        "- **Идентификаторы игроков хешированы.** PUUID — постоянный идентификатор "
        "аккаунта Riot, в публичном репозитории его быть не должно; для связей достаточно "
        "устойчивого хеша.\n"
        "- **Наблюдения не полностью независимы.** Один игрок встречается в нескольких "
        "матчах, поэтому z-тест здесь приближённый."
    )
