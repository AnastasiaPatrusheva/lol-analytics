"""Вкладка «Качество данных»: живые проверки прямо в интерфейсе."""
import streamlit as st

from dashboard.data import run, table_with_download


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
    q1.write("✅ ок" if bad_size == 0 else "⚠️ есть неполные")
    q2.metric("Дубли записей", dups, help="Повторная запись одного игрока в матче. Норма — 0.")
    q2.write("✅ ок" if dups == 0 else "⚠️ есть дубли")
    q3.metric("Строки-сироты", orphans, help="Запись игрока без привязки к матчу. Норма — 0.")
    q3.write("✅ ок" if orphans == 0 else "⚠️ есть сироты")
    q4.metric("Ср. winrate", f"{wr:.3f}", help="Должен быть ≈0.500: в матче 5 побед и 5 поражений.")
    q4.write("✅ ок" if abs(wr - 0.5) <= 0.01 else "⚠️ дисбаланс")

    table_with_download(dist, "Участников на матч", "participants_per_match.csv",
                        key="dl_quality",
                        caption="Ожидаем ровно один столбец — «10».")
