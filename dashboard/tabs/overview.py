"""Вкладка «Обзор»: KPI, авто-инсайты, победители vs проигравшие."""
import streamlit as st

from dashboard.data import run, table_with_download, champion_images, item_images


def _insight_card(title, name, subtitle, img, accent="#C8AA6E"):
    pic = (f"<img src='{img}' style='width:48px;height:48px;border-radius:9px;"
           f"border:1px solid #2f3a4d;flex:none'>") if img else ""
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:14px;"
        "padding:13px 15px;display:flex;gap:12px;align-items:center'>"
        f"{pic}<div style='min-width:0'>"
        f"<div style='font-size:11px;color:#a49b86;text-transform:uppercase;letter-spacing:.05em'>{title}</div>"
        "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:17px;"
        f"font-weight:600;color:#e8ecec\">{name}</div>"
        f"<div style='font-size:12.5px;color:{accent}'>{subtitle}</div></div></div>"
    )


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

    st.markdown("#### Главное в мете")
    top_champ = run(f"""
        SELECT cs.champion_name, cs.wilson_low, cs.games, dc.champion_id
        FROM champion_strength cs
        JOIN dim_champion dc ON cs.champion_name = dc.champion_name
        WHERE cs.data_source = '{source}' AND cs.verdict = 'значимо сильный'
        ORDER BY cs.wilson_low DESC LIMIT 1
    """)
    top_item = run(f"""
        SELECT item_name, item_id, wilson_low, purchases FROM item_stats
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
        SELECT p.champion_name, (p.l - p.s) AS delta, dc.champion_id
        FROM p JOIN dim_champion dc ON p.champion_name = dc.champion_name
        WHERE p.gs >= 20 AND p.gl >= 20 ORDER BY delta DESC LIMIT 1
    """)
    champ_imgs = champion_images()
    it_imgs = item_images()
    i1, i2, i3 = st.columns(3)
    if not top_champ.empty:
        r = top_champ.iloc[0]
        i1.markdown(_insight_card(
            "Сильнейший чемпион", r["champion_name"],
            f"winrate {r['wilson_low']:.0%} · {int(r['games'])} игр",
            champ_imgs.get(int(r["champion_id"]), "")), unsafe_allow_html=True)
    if not top_item.empty:
        r = top_item.iloc[0]
        i2.markdown(_insight_card(
            "Предмет с лучшим winrate", r["item_name"],
            f"{r['wilson_low']:.0%} · {int(r['purchases'])} покупок",
            it_imgs.get(int(r["item_id"]), ""), accent="#5aa0c9"), unsafe_allow_html=True)
    if not scaler.empty:
        r = scaler.iloc[0]
        i3.markdown(_insight_card(
            "Сильнее всего в долгой игре", r["champion_name"],
            f"+{r['delta']:.0%} winrate в долгих матчах",
            champ_imgs.get(int(r["champion_id"]), ""), accent="#cda24a"), unsafe_allow_html=True)

    result = run(f"""
        SELECT CASE WHEN win THEN 'Победа' ELSE 'Поражение' END AS result,
               AVG(kda) AS avg_kda,
               AVG(gold_per_min) AS avg_gold_per_min,
               AVG(damage_per_min) AS avg_damage_per_min
        FROM fact_participant WHERE data_source = '{source}'
        GROUP BY win ORDER BY win
    """)
    disp = result.rename(columns={
        "result": "Результат", "avg_kda": "KDA",
        "avg_gold_per_min": "Золото/мин", "avg_damage_per_min": "Урон/мин",
    })
    disp["KDA"] = disp["KDA"].round(2)
    disp["Золото/мин"] = disp["Золото/мин"].round().astype(int)
    disp["Урон/мин"] = disp["Урон/мин"].round().astype(int)
    table_with_download(disp, "Победители против проигравших",
                        "winners_vs_losers.csv", key="dl_overview")
