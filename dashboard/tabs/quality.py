"""Вкладка «Качество данных»: живые проверки прямо в интерфейсе."""
import streamlit as st

from dashboard.data import run, table_with_download


def _status(ok: bool, ok_text: str, bad_text: str) -> str:
    """Монохромный статус под тему: бирюзовая галочка / красный знак."""
    if ok:
        return f"<span style='color:#3fd0c9;font-weight:600'>✓ {ok_text}</span>"
    return f"<span style='color:#d9534f;font-weight:600'>⚠ {bad_text}</span>"


def render(source: str) -> None:
    st.subheader("Качество данных")
    st.caption("Автоматические проверки данных — показывают, что данным можно доверять.")

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
