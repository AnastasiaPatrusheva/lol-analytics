"""Вкладка «Игроки»: распределение LP и карточка игрока."""
import altair as alt
import streamlit as st

from dashboard.data import run, download_csv, table_with_download


def _player_name(row) -> str:
    n = row["name"]
    return n if isinstance(n, str) and n.strip() else str(row["puuid"])[:10]


def render(source: str) -> None:
    st.subheader("Распределение игроков по очкам лиги (LP)")
    lp = run(f"""
        SELECT league_points FROM dim_player
        WHERE data_source = '{source}' AND league_points IS NOT NULL
    """)
    if lp.empty:
        st.caption(
            "Очки лиги (LP) есть только у источника **riot_api**. "
            "Выберите его в панели «Фильтры» слева, чтобы увидеть распределение."
        )
    else:
        st.caption(
            "LP (league points) — рейтинговые очки: чем выше, тем выше место в топ-ладдере. "
            f"Собрано {len(lp)} игроков верхних лиг (Challenger/GM/Master)."
        )
        lp_hist = (
            alt.Chart(lp)
            .mark_bar(color="#3fa45b")
            .encode(
                x=alt.X("league_points:Q", bin=alt.Bin(maxbins=25), title="Очки лиги (LP)"),
                y=alt.Y("count()", title="Игроков"),
                tooltip=[alt.Tooltip("count()", title="игроков")],
            )
            .properties(height=220)
        )
        st.altair_chart(lp_hist, width="stretch")
    st.divider()

    min_p_games = st.slider("Минимум матчей у игрока", 5, 100, 20, step=5)
    players = run(f"""
        SELECT p.riot_id_game_name AS name, p.puuid, p.source_tier,
               COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               AVG(f.kda) AS avg_kda,
               AVG(f.damage_per_min) AS dmg_pm,
               AVG(f.gold_per_min) AS gold_pm,
               AVG(f.cs_per_min) AS cs_pm,
               AVG(f.vision_per_min) AS vis_pm,
               AVG(f.kills) AS k, AVG(f.deaths) AS d, AVG(f.assists) AS a
        FROM fact_participant f
        JOIN dim_player p ON f.data_source = p.data_source AND f.puuid = p.puuid
        WHERE f.data_source = '{source}'
        GROUP BY p.riot_id_game_name, p.puuid, p.source_tier
        HAVING COUNT(*) >= {min_p_games}
        ORDER BY games DESC
    """)

    st.subheader("Профиль игрока")
    st.caption("Карточка одного игрока: метрики, любимые чемпионы и роли. Выберите игрока из списка ниже.")
    if players.empty:
        st.info("Нет игроков с таким порогом. Снизьте минимум (богаче всего — источник riot_full).")
        return

    players = players.copy()
    players["label"] = players.apply(
        lambda r: f"{_player_name(r)} · {int(r['games'])} матчей · WR {r['winrate']:.0%}",
        axis=1,
    )
    choice = st.selectbox("Игрок", players["label"])
    row = players[players["label"] == choice].iloc[0]
    puuid = row["puuid"]

    st.markdown(f"### 👤 {_player_name(row)}")
    cols = st.columns(7)
    cols[0].metric("Матчей", int(row["games"]))
    cols[1].metric("Winrate", f"{row['winrate']:.0%}")
    cols[2].metric("KDA", f"{row['avg_kda']:.2f}")
    cols[3].metric("Урон/мин", f"{row['dmg_pm']:.0f}")
    cols[4].metric("Золото/мин", f"{row['gold_pm']:.0f}")
    cols[5].metric("CS/мин", f"{row['cs_pm']:.1f}")
    cols[6].metric("Обзор/мин", f"{row['vis_pm']:.2f}")

    st.markdown("**В среднем за игру**")
    kda_hint = f"Среднее значение за игру. Источник данных: {source}."
    kc = st.columns(3)
    kc[0].metric("Убийства", f"{row['k']:.1f}", help=kda_hint)
    kc[1].metric("Смерти", f"{row['d']:.1f}", help=kda_hint)
    kc[2].metric("Помощи", f"{row['a']:.1f}", help=kda_hint)

    champs = run(f"""
        SELECT c.champion_name, COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               AVG(f.kda) AS avg_kda
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        WHERE f.data_source = '{source}' AND f.puuid = '{puuid}'
        GROUP BY c.champion_name ORDER BY games DESC
    """)
    best_champ = champs[champs["games"] >= 3].sort_values("winrate", ascending=False)
    if not best_champ.empty:
        b = best_champ.iloc[0]
        st.success(
            f"⭐ Лучший чемпион игрока: **{b['champion_name']}** — "
            f"{b['winrate']:.0%} winrate на {int(b['games'])} играх."
        )

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Любимые чемпионы")
        ch = (
            alt.Chart(champs.head(12))
            .mark_bar()
            .encode(
                x=alt.X("games:Q", title="Игр"),
                y=alt.Y("champion_name:N", sort="-x", title=None),
                color=alt.Color("winrate:Q", title="WR",
                                scale=alt.Scale(scheme="redyellowgreen", domain=[0.3, 0.7])),
                tooltip=["champion_name", "games",
                         alt.Tooltip("winrate:Q", format=".0%"),
                         alt.Tooltip("avg_kda:Q", format=".2f")],
            )
            .properties(height=360)
        )
        st.altair_chart(ch, width="stretch")

    roles = run(f"""
        SELECT r.role_name_ru AS role, COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM fact_participant f
        JOIN dim_role r ON f.role_key = r.role_key
        WHERE f.data_source = '{source}' AND f.puuid = '{puuid}'
        GROUP BY r.role_name_ru ORDER BY games DESC
    """)
    with right:
        st.markdown("#### Роли")
        rc = (
            alt.Chart(roles)
            .mark_arc(innerRadius=50)
            .encode(
                theta=alt.Theta("games:Q"),
                color=alt.Color("role:N", title="Роль"),
                tooltip=["role", "games", alt.Tooltip("winrate:Q", format=".0%")],
            )
            .properties(height=320)
        )
        st.altair_chart(rc, width="stretch")

    with st.expander("📋 Все чемпионы игрока"):
        _, dl_col = st.columns([4, 1])
        with dl_col:
            download_csv(champs, "player_champions.csv", key="dl_player_champs", use_container_width=True)
        st.dataframe(champs, width="stretch", hide_index=True)

    top_players = players.drop(columns=["label", "puuid"]).head(50)
    table_with_download(top_players, "Все игроки источника — по числу матчей",
                        "players.csv", key="dl_players")
