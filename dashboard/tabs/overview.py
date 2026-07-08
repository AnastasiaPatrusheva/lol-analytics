"""Вкладка «Обзор»: KPI, авто-инсайты, победители vs проигравшие."""
import streamlit as st

from dashboard.data import run, table_with_download


def render(source: str) -> None:
    kpi = run(f"""
        SELECT COUNT(*) AS rows,
               COUNT(DISTINCT match_id) AS matches,
               COUNT(DISTINCT puuid) AS players,
               COUNT(DISTINCT champion_id) AS champions
        FROM fact_participant WHERE data_source = '{source}'
    """).iloc[0]
    duration = run(f"""
        SELECT AVG(game_duration_min) AS d FROM dim_match WHERE data_source = '{source}'
    """).iloc[0]["d"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Матчей", f"{int(kpi['matches']):,}".replace(",", " "))
    c2.metric("Игроков", f"{int(kpi['players']):,}".replace(",", " "))
    c3.metric("Чемпионов", int(kpi["champions"]))
    c4.metric("Ср. длительность", f"{duration:.1f} мин")

    st.caption(
        "Winrate в сумме ≈ 50%: в каждом матче 5 победителей и 5 проигравших — "
        "это контрольная проверка корректности данных."
    )

    st.markdown("#### 💡 Главное в мете")
    top_champ = run(f"""
        SELECT champion_name, wilson_low, games FROM champion_strength
        WHERE data_source = '{source}' AND verdict = 'значимо сильный'
        ORDER BY wilson_low DESC LIMIT 1
    """)
    top_item = run(f"""
        SELECT item_name, wilson_low, purchases FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= 2000
        ORDER BY wilson_low DESC LIMIT 1
    """)
    scaler = run(f"""
        WITH p AS (
            SELECT champion_name,
                   MAX(CASE WHEN duration_bucket LIKE '1.%' THEN winrate END) AS s,
                   MAX(CASE WHEN duration_bucket LIKE '3.%' THEN winrate END) AS l,
                   MAX(CASE WHEN duration_bucket LIKE '1.%' THEN games END) AS gs,
                   MAX(CASE WHEN duration_bucket LIKE '3.%' THEN games END) AS gl
            FROM champion_by_duration WHERE data_source = '{source}' GROUP BY champion_name
        )
        SELECT champion_name, (l - s) AS delta FROM p
        WHERE gs >= 20 AND gl >= 20 ORDER BY delta DESC LIMIT 1
    """)
    i1, i2, i3 = st.columns(3)
    if not top_champ.empty:
        r = top_champ.iloc[0]
        i1.success(f"🏆 **Сильнейший чемпион**\n\n{r['champion_name']} — winrate "
                   f"{r['wilson_low']:.0%} с поправкой на число игр ({int(r['games'])} игр)")
    if not top_item.empty:
        r = top_item.iloc[0]
        i2.success(f"🛡️ **Предмет с лучшим winrate**\n\n{r['item_name']} — {r['wilson_low']:.0%} "
                   f"({int(r['purchases'])} покупок)")
    if not scaler.empty:
        r = scaler.iloc[0]
        i3.success(f"📈 **Сильнее всего в долгой игре**\n\n{r['champion_name']} — +{r['delta']:.0%} "
                   f"winrate в долгих матчах")

    result = run(f"""
        SELECT CASE WHEN win THEN 'Победа' ELSE 'Поражение' END AS result,
               AVG(kda) AS avg_kda,
               AVG(gold_per_min) AS avg_gold_per_min,
               AVG(damage_per_min) AS avg_damage_per_min
        FROM fact_participant WHERE data_source = '{source}'
        GROUP BY win ORDER BY win
    """)
    table_with_download(result, "Победители против проигравших",
                        "winners_vs_losers.csv", key="dl_overview")
