"""
LoL Analytics — дашборд на Streamlit.

Читает готовую звёздную схему (Parquet) напрямую через DuckDB — отдельная БД не нужна.
Те же данные, что в Supabase, лежат локально в outputs/sql/star/*.parquet.

Запуск локально:   streamlit run streamlit_app.py
Деплой:            GitHub -> streamlit.app (нужны streamlit_app.py + outputs/sql/star/*.parquet + requirements.txt)
"""

from __future__ import annotations

from pathlib import Path
from statistics import NormalDist

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

STAR_DIR = Path(__file__).parent / "outputs" / "sql" / "star"
TABLES = [
    "fact_participant", "dim_champion", "dim_match", "dim_player", "dim_role",
    "fact_participant_item", "dim_item", "item_stats",
    "champion_strength", "champion_by_duration", "player_segments",
]
POSITIONS = ["Все", "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

st.set_page_config(page_title="LoL Analytics", page_icon="🎮", layout="wide")


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    for table in TABLES:
        parquet = STAR_DIR / f"{table}.parquet"
        # Витрина может отсутствовать (напр. player_segments до сборки) — пропускаем.
        if parquet.exists():
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{parquet.as_posix()}')")
    return con


def table_exists(name: str) -> bool:
    return (STAR_DIR / f"{name}.parquet").exists()


@st.cache_data
def run(sql: str):
    return get_connection().execute(sql).df()


# ---------- боковая панель: общие фильтры ----------
SOURCE_DESC = {
    "riot_full": "Большой набор: ~26 000 матчей, 7 патчей (16.7–16.12), регион EUW.",
    "kaggle": "Исторический срез матчей с Kaggle.",
    "riot_api": "Собственная свежая выборка, собранная через Riot API.",
}
st.sidebar.header("Фильтры")
source = st.sidebar.selectbox("Источник данных", ["riot_full", "kaggle", "riot_api"])
st.sidebar.caption(SOURCE_DESC[source])

st.title("🎮 LoL Analytics")
(tab_overview, tab_champions, tab_items, tab_players, tab_duration,
 tab_meta, tab_segments, tab_quality) = st.tabs(
    ["📋 Обзор", "🏆 Чемпионы", "🛡️ Предметы", "👤 Игроки", "⏱ Длительность",
     "📊 Мета", "🧩 Архетипы", "✅ Качество"]
)


# ---------- Обзор ----------
with tab_overview:
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

    # --- Главное (авто-инсайты / storytelling) ---
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
    st.subheader("Победители против проигравших")
    st.dataframe(result, width="stretch", hide_index=True)


# ---------- Чемпионы ----------
with tab_champions:
    col_a, col_b, col_c = st.columns([1, 1.4, 1.4])
    position = col_a.selectbox("Позиция", POSITIONS)
    rank_by = col_b.radio(
        "Ранжировать по", ["С поправкой на число игр", "Сырой winrate"], horizontal=True,
        help="Метод Уилсона строит доверительный интервал winrate с учётом числа игр: "
             "чем меньше выборка, тем осторожнее оценка. Ранжируем по нижней границе интервала — "
             "чтобы 70% на 5 играх не оказались выше 53% на 500.",
    )
    min_games = col_c.slider("Минимум игр", 5, 100, 30, step=5)

    pos_filter = "" if position == "Все" else f"AND f.role_key = '{position}'"
    order_col = "wilson_low" if rank_by.startswith("С поправкой") else "winrate"

    # Wilson 95% считаем прямо в запросе, с учётом фильтра позиции.
    champions = run(f"""
        WITH base AS (
            SELECT c.champion_name, c.primary_class,
                   COUNT(DISTINCT f.match_id) AS games,
                   SUM(CASE WHEN f.win THEN 1 ELSE 0 END) AS wins,
                   AVG(f.kda) AS avg_kda
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' {pos_filter}
            GROUP BY c.champion_name, c.primary_class
            HAVING COUNT(DISTINCT f.match_id) >= {min_games}
        ),
        ci AS (
            SELECT *, wins * 1.0 / games AS winrate,
                   (wins*1.0/games + 1.96*1.96/(2*games)
                    - 1.96*sqrt((wins*1.0/games*(1-wins*1.0/games)+1.96*1.96/(4*games))/games))
                   / (1+1.96*1.96/games) AS wilson_low,
                   (wins*1.0/games + 1.96*1.96/(2*games)
                    + 1.96*sqrt((wins*1.0/games*(1-wins*1.0/games)+1.96*1.96/(4*games))/games))
                   / (1+1.96*1.96/games) AS wilson_high
            FROM base
        )
        SELECT champion_name, primary_class, games, winrate, wilson_low, wilson_high, avg_kda,
               CASE WHEN wilson_low > 0.5 THEN 'значимо сильный'
                    WHEN wilson_high < 0.5 THEN 'значимо слабый'
                    ELSE 'в норме' END AS verdict
        FROM ci ORDER BY {order_col} DESC
    """)

    metric_title = "Winrate (с поправкой на число игр)" if order_col == "wilson_low" else "Winrate"
    st.subheader(f"Топ чемпионов ({position})")
    st.caption(
        "Цвет столбца = значимость: зелёный — значимо сильный (весь интервал уверенности выше 50%), "
        "красный — значимо слабый, серый — в норме (высокий % может быть просто шумом малой выборки)."
    )
    if champions.empty:
        st.info("Нет чемпионов с таким порогом игр. Снизьте минимум игр.")
    else:
        strong = champions[champions["verdict"].str.contains("значимо сильный")]
        if not strong.empty:
            t = strong.iloc[0]
            st.success(
                f"🏆 Сильнейший (значимо): **{t['champion_name']}** — winrate "
                f"{t['wilson_low']:.0%} с поправкой на число игр ({int(t['games'])} игр). "
                f"Статистически доказанных сильных всего {len(strong)}."
            )
        chart = (
            alt.Chart(champions.head(20))
            .mark_bar()
            .encode(
                x=alt.X(f"{order_col}:Q", title=metric_title, axis=alt.Axis(format="%")),
                y=alt.Y("champion_name:N", sort="-x", title=None),
                color=alt.Color(
                    "verdict:N", title="Вердикт",
                    scale=alt.Scale(
                        domain=["значимо сильный", "в норме", "значимо слабый"],
                        range=["#3fa45b", "#9aa0a6", "#d9534f"],
                    ),
                ),
                tooltip=[
                    "champion_name", "primary_class", "games",
                    alt.Tooltip("winrate:Q", format=".1%", title="winrate"),
                    alt.Tooltip("wilson_low:Q", format=".1%", title="Уилсон ниж."),
                    "verdict",
                ],
            )
            .properties(height=480)
        )
        st.altair_chart(chart, width="stretch")

        st.markdown("#### Убийства vs смерти по чемпионам")
        st.caption(
            "Каждая точка — чемпион: по горизонтали среднее число смертей за игру, "
            "по вертикали — убийств. Левее и выше = агрессивные и живучие; цвет — winrate."
        )
        kd = run(f"""
            SELECT c.champion_name, c.primary_class,
                   COUNT(DISTINCT f.match_id) AS games,
                   AVG(f.kills) AS avg_kills,
                   AVG(f.deaths) AS avg_deaths,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' {pos_filter}
            GROUP BY c.champion_name, c.primary_class
            HAVING COUNT(DISTINCT f.match_id) >= {min_games}
        """)
        kd_scatter = (
            alt.Chart(kd)
            .mark_circle(opacity=0.6)
            .encode(
                x=alt.X("avg_deaths:Q", title="Смертей за игру (в среднем)"),
                y=alt.Y("avg_kills:Q", title="Убийств за игру (в среднем)"),
                size=alt.Size("games:Q", title="Игр"),
                color=alt.Color("winrate:Q", title="Winrate",
                                scale=alt.Scale(scheme="redyellowgreen", domain=[0.4, 0.6])),
                tooltip=["champion_name", "primary_class", "games",
                         alt.Tooltip("avg_kills:Q", format=".1f", title="убийств"),
                         alt.Tooltip("avg_deaths:Q", format=".1f", title="смертей"),
                         alt.Tooltip("winrate:Q", format=".0%")],
            )
            .interactive()
            .properties(height=380)
        )
        st.altair_chart(kd_scatter, width="stretch")

        anomalies = champions[champions["verdict"].str.contains("значимо")]
        with st.expander(f"🔎 Аномалии меты: {len(anomalies)} чемпионов со значимым отклонением от 50%"):
            verdict_colors = {"значимо сильный": "#3fa45b", "значимо слабый": "#d9534f"}
            disp = anomalies.rename(columns={
                "champion_name": "Чемпион", "primary_class": "Класс", "games": "Игр",
                "winrate": "Winrate", "wilson_low": "Ниж. оценка", "wilson_high": "Верх. оценка",
                "avg_kda": "KDA", "verdict": "Вердикт",
            })
            styled = (
                disp.style
                .format({"Winrate": "{:.1%}", "Ниж. оценка": "{:.1%}",
                         "Верх. оценка": "{:.1%}", "KDA": "{:.2f}"})
                .apply(
                    lambda col: [f"color: {verdict_colors.get(v, '#9aa0a6')}; font-weight: 600"
                                 for v in col],
                    subset=["Вердикт"],
                )
            )
            st.dataframe(styled, width="stretch", hide_index=True)


# ---------- Предметы ----------
with tab_items:
    min_gold = st.slider(
        "Минимальная цена предмета (золото)", 0, 4000, 2000, step=250,
        help="Отсекает дешёвые предметы и триннкеты-варды, чтобы видеть «билдовые» предметы",
    )
    items = run(f"""
        SELECT item_name, purchases, winrate, wilson_low, gold_total
        FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= {min_gold}
        ORDER BY purchases DESC
    """)

    st.subheader("Какие предметы стоит собирать")
    st.caption(
        "Точка на графике — предмет: правее — покупают чаще, выше — чаще с ним побеждают. "
        "Верх-право = и популярны, и приносят победы."
    )
    if items.empty:
        st.info("Нет предметов с таким порогом цены.")
    else:
        best = items.sort_values("wilson_low", ascending=False).iloc[0]
        st.success(
            f"🛡️ Лучший по winrate: **{best['item_name']}** — "
            f"{best['winrate']:.0%} при {int(best['purchases'])} покупках."
        )
        scatter = (
            alt.Chart(items)
            .mark_circle(size=70, opacity=0.7, color="#3fa45b")
            .encode(
                x=alt.X("purchases:Q", title="Покупок"),
                y=alt.Y("winrate:Q", title="Winrate", axis=alt.Axis(format="%"),
                        scale=alt.Scale(zero=False)),
                tooltip=[
                    "item_name", "purchases",
                    alt.Tooltip("winrate:Q", format=".1%"),
                    alt.Tooltip("gold_total:Q", title="Цена"),
                ],
            )
            .interactive()
            .properties(height=420)
        )
        st.altair_chart(scatter, width="stretch")
        st.markdown("#### Все предметы (сортировка по winrate)")
        st.dataframe(
            items.sort_values("winrate", ascending=False),
            width="stretch", hide_index=True,
        )


# ---------- Игроки ----------
with tab_players:
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
    else:
        players = players.copy()

        def player_name(r):
            n = r["name"]
            return n if isinstance(n, str) and n.strip() else str(r["puuid"])[:10]

        players["label"] = players.apply(
            lambda r: f"{player_name(r)} · {int(r['games'])} матчей · WR {r['winrate']:.0%}",
            axis=1,
        )
        choice = st.selectbox("Игрок", players["label"])
        row = players[players["label"] == choice].iloc[0]
        puuid = row["puuid"]

        st.markdown(f"### 👤 {player_name(row)}")
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
            st.dataframe(champs, width="stretch", hide_index=True)

        st.markdown("#### Все игроки источника — рейтинг по числу матчей")
        st.dataframe(
            players.drop(columns=["label", "puuid"]).head(50),
            width="stretch", hide_index=True,
        )


# ---------- Длительность ----------
with tab_duration:
    st.subheader("Длительность матчей")
    dur = run(f"""
        SELECT game_duration_min FROM dim_match
        WHERE data_source = '{source}' AND game_duration_min IS NOT NULL
    """)
    if not dur.empty:
        box = (
            alt.Chart(dur)
            .mark_boxplot(extent="min-max", size=40, color="#3fa45b")
            .encode(x=alt.X("game_duration_min:Q", title="Длительность матча, мин"))
            .properties(height=140)
        )
        st.altair_chart(box, width="stretch")
        q1 = dur["game_duration_min"].quantile(0.25)
        q3 = dur["game_duration_min"].quantile(0.75)
        med = dur["game_duration_min"].median()
        st.caption(
            f"Половина матчей длится примерно {q1:.0f}–{q3:.0f} мин (медиана {med:.0f}). "
            "«Коробка» — где лежит середина матчей, «усы» — общий разброс."
        )
    st.divider()

    min_b = st.slider("Минимум игр в каждой длине (короткие и длинные)", 5, 50, 15, step=5)
    st.subheader("Кто сильнее в долгих играх, а кто в коротких")
    st.caption(
        "Разница winrate между долгими (>32 мин) и короткими (<25 мин) матчами. "
        "Зелёный (плюс) — чемпион сильнее в долгой игре, красный (минус) — в короткой."
    )

    scaling = run(f"""
        WITH b AS (
            SELECT c.champion_name,
                   CASE WHEN m.game_duration_min < 25 THEN 'short'
                        WHEN m.game_duration_min < 32 THEN 'mid'
                        ELSE 'long' END AS bucket,
                   COUNT(*) AS games,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS wr
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            JOIN dim_match m ON f.data_source = m.data_source AND f.match_id = m.match_id
            WHERE f.data_source = '{source}'
            GROUP BY c.champion_name, bucket
        ),
        piv AS (
            SELECT champion_name,
                   MAX(CASE WHEN bucket = 'short' THEN wr END) AS wr_short,
                   MAX(CASE WHEN bucket = 'long' THEN wr END) AS wr_long,
                   MAX(CASE WHEN bucket = 'short' THEN games END) AS g_short,
                   MAX(CASE WHEN bucket = 'long' THEN games END) AS g_long
            FROM b GROUP BY champion_name
        )
        SELECT champion_name, wr_short, wr_long,
               (wr_long - wr_short) AS delta, g_short, g_long
        FROM piv
        WHERE g_short >= {min_b} AND g_long >= {min_b}
        ORDER BY delta DESC
    """)

    if scaling.empty:
        st.info("Мало данных при таком пороге. Снизьте минимум игр.")
    else:
        top_s = scaling.iloc[0]
        bot_s = scaling.iloc[-1]
        st.success(
            f"📈 Больше всех выигрывает от долгой игры — **{top_s['champion_name']}** "
            f"(+{top_s['delta']:.0%} winrate); а **{bot_s['champion_name']}** наоборот сильнее "
            f"в короткой ({bot_s['delta']:+.0%} в долгой)."
        )
        diverging = pd.concat([scaling.head(12), scaling.tail(12)])
        chart = (
            alt.Chart(diverging)
            .mark_bar()
            .encode(
                x=alt.X("delta:Q", title="Δ winrate (длинные − короткие)",
                        axis=alt.Axis(format="+%")),
                y=alt.Y("champion_name:N", sort="-x", title=None),
                color=alt.condition("datum.delta > 0", alt.value("#3fa45b"), alt.value("#d9534f")),
                tooltip=[
                    "champion_name",
                    alt.Tooltip("wr_short:Q", format=".1%", title="короткие"),
                    alt.Tooltip("wr_long:Q", format=".1%", title="длинные"),
                    alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
                ],
            )
            .properties(height=520)
        )
        st.altair_chart(chart, width="stretch")
        st.caption("Сверху — сильнее в долгой игре, снизу — сильнее в короткой.")
        st.dataframe(scaling, width="stretch", hide_index=True)


# ---------- Мета (сравнение патчей) ----------
with tab_meta:
    st.subheader("Сравнение патчей — сдвиги меты")
    # патч = первые две части game_version (16.11.782.9736 -> 16.11)
    patches_df = run(f"""
        SELECT split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2) AS patch,
               COUNT(*) AS matches
        FROM dim_match
        WHERE data_source = '{source}' AND game_version IS NOT NULL
        GROUP BY 1 HAVING COUNT(*) >= 50 ORDER BY patch
    """)
    # числовая сортировка патчей: 16.7 < 16.8 < 16.10 < 16.11 (а не как строки)
    patches = sorted(
        [p for p in patches_df["patch"].tolist() if p and p != "."],
        key=lambda x: [int(n) for n in x.split(".")],
    )

    if len(patches) < 2:
        st.info(
            f"У источника «{source}» меньше двух патчей с данными. "
            "Переключите источник на **riot_full** — там 7 патчей (16.7–16.12)."
        )
    else:
        c1, c2, c3 = st.columns(3)
        patch_a = c1.selectbox("Патч A", patches, index=len(patches) - 2)
        patch_b = c2.selectbox("Патч B", patches, index=len(patches) - 1)
        min_g = c3.slider("Минимум игр в каждом патче", 10, 200, 30, step=10)
        # Порядок выбора не важен — всегда сравниваем от раннего патча к позднему.
        patch_a, patch_b = sorted([patch_a, patch_b], key=lambda x: [int(n) for n in x.split(".")])
        st.caption(
            f"Сравниваем winrate чемпионов от раннего патча ({patch_a}) к позднему ({patch_b}); "
            "порядок выбора не важен. Зелёный — усилился (бафф), красный — ослаб (нерф)."
        )

        cmp = run(f"""
            WITH m AS (
                SELECT data_source, match_id,
                       split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2) AS patch
                FROM dim_match WHERE data_source = '{source}'
            ),
            f AS (
                SELECT c.champion_name, c.primary_class, fp.win, m.patch
                FROM fact_participant fp
                JOIN m ON fp.data_source = m.data_source AND fp.match_id = m.match_id
                JOIN dim_champion c ON fp.champion_id = c.champion_id
                WHERE fp.data_source = '{source}' AND m.patch IN ('{patch_a}', '{patch_b}')
            ),
            agg AS (
                SELECT champion_name, primary_class, patch,
                       COUNT(*) AS games,
                       SUM(CASE WHEN win THEN 1 ELSE 0 END) AS wins,
                       AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
                FROM f GROUP BY champion_name, primary_class, patch
            ),
            piv AS (
                SELECT champion_name, primary_class,
                       MAX(CASE WHEN patch = '{patch_a}' THEN wr END) AS wr_a,
                       MAX(CASE WHEN patch = '{patch_b}' THEN wr END) AS wr_b,
                       MAX(CASE WHEN patch = '{patch_a}' THEN games END) AS g_a,
                       MAX(CASE WHEN patch = '{patch_b}' THEN games END) AS g_b,
                       MAX(CASE WHEN patch = '{patch_a}' THEN wins END) AS w_a,
                       MAX(CASE WHEN patch = '{patch_b}' THEN wins END) AS w_b
                FROM agg GROUP BY champion_name, primary_class
            )
            SELECT champion_name, primary_class, wr_a, wr_b,
                   (wr_b - wr_a) AS delta, g_a, g_b, w_a, w_b
            FROM piv
            WHERE g_a >= {min_g} AND g_b >= {min_g}
            ORDER BY delta DESC
        """)

        if cmp.empty:
            st.info("Нет чемпионов с достаточной выборкой в обоих патчах. Снизьте минимум игр.")
        else:
            # Значимость сдвига winrate: two-proportion z-тест (winrate = доля побед).
            # H0: сила чемпиона между патчами не изменилась. Значимо, если p < 0.05.
            def patch_pvalue(r):
                n_a, n_b = r["g_a"], r["g_b"]
                if not n_a or not n_b:
                    return 1.0
                p_a, p_b = r["w_a"] / n_a, r["w_b"] / n_b
                pool = (r["w_a"] + r["w_b"]) / (n_a + n_b)
                se = (pool * (1 - pool) * (1 / n_a + 1 / n_b)) ** 0.5
                if se == 0:
                    return 1.0
                z = (p_b - p_a) / se
                return 2 * (1 - NormalDist().cdf(abs(z)))

            cmp["p_value"] = cmp.apply(patch_pvalue, axis=1)
            cmp["is_sig"] = cmp["p_value"] < 0.05
            sig = cmp[cmp["is_sig"]]

            only_sig = st.checkbox(
                f"Только значимые изменения (p < 0.05) — их {len(sig)} из {len(cmp)}",
                value=False,
                help="Оставляет только те изменения winrate, которые слишком велики, чтобы "
                     "быть случайностью (статистически значимые). Небольшие колебания на малом "
                     "числе игр отфильтровываются как шум.",
            )
            view = sig if only_sig else cmp

            if not sig.empty:
                buff = sig.iloc[0]
                nerf = sig.iloc[-1]
                st.success(
                    f"📊 Значимые сдвиги {patch_a} → {patch_b}: усилился "
                    f"**{buff['champion_name']}** (+{buff['delta']:.0%}, p={buff['p_value']:.3f}); "
                    f"ослаб **{nerf['champion_name']}** ({nerf['delta']:+.0%}, p={nerf['p_value']:.3f})."
                )
            else:
                st.info(
                    f"Между {patch_a} и {patch_b} нет статистически значимых сдвигов (p < 0.05) "
                    "при текущем пороге игр — изменения в пределах шума выборки."
                )

            if view.empty:
                st.caption("При текущих настройках значимых изменений нет. Снимите галочку или снизьте минимум игр.")
            else:
                diverging = pd.concat([view.head(12), view.tail(12)])
                chart = (
                    alt.Chart(diverging)
                    .mark_bar()
                    .encode(
                        x=alt.X("delta:Q", title=f"Δ winrate ({patch_b} − {patch_a})",
                                axis=alt.Axis(format="+%")),
                        y=alt.Y("champion_name:N", sort="-x", title=None),
                        color=alt.condition("datum.delta > 0", alt.value("#3fa45b"), alt.value("#d9534f")),
                        opacity=alt.condition("datum.is_sig", alt.value(0.95), alt.value(0.3)),
                        tooltip=[
                            "champion_name", "primary_class",
                            alt.Tooltip("wr_a:Q", format=".1%", title=patch_a),
                            alt.Tooltip("wr_b:Q", format=".1%", title=patch_b),
                            alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
                            alt.Tooltip("p_value:Q", format=".3f", title="p-значение"),
                        ],
                    )
                    .properties(height=520)
                )
                st.altair_chart(chart, width="stretch")
                st.caption(
                    "Насыщенные столбцы — статистически значимые сдвиги (p<0.05); "
                    "блёклые — в пределах шума. Сверху усиление, снизу ослабление."
                )
                st.dataframe(view, width="stretch", hide_index=True)


# ---------- Архетипы игроков (KMeans) ----------
with tab_segments:
    st.subheader("Архетипы игроков")
    st.caption(
        "Игроки разбиты на группы по стилю игры. Названия описательные — это не официальные "
        "категории Riot."
    )
    st.markdown(
        "**Что значат названия архетипов:**\n"
        "- **фарм** — много миньонов (CS)\n"
        "- **урон** — высокий урон по чемпионам\n"
        "- **обзор** — контроль карты (вардинг)\n"
        "- **экономика** — много золота\n"
        "- **командный** — высокий KDA при низком фарме (участие в командных боях)"
    )
    if not table_exists("player_segments"):
        st.info("Данные по архетипам пока недоступны.")
    else:
        seg = run(f"SELECT * FROM player_segments WHERE data_source = '{source}'")
        if seg.empty:
            st.info(
                f"Для источника «{source}» мало игроков с ≥20 играми для группировки. "
                "Выберите источник riot_full в панели «Фильтры» слева."
            )
        else:
            counts = (
                seg.groupby("archetype")
                .agg(players=("puuid", "count"), winrate=("winrate", "mean"),
                     kda=("kda", "mean"), cs=("cs_per_min", "mean"),
                     dmg=("damage_per_min", "mean"), vision=("vision_per_min", "mean"),
                     gold=("gold_per_min", "mean"))
                .reset_index()
                .sort_values("players", ascending=False)
            )
            top = counts.iloc[0]
            st.success(
                f"🧩 Самый массовый архетип: **{top['archetype']}** — "
                f"{int(top['players'])} игроков, ср. winrate {top['winrate']:.0%}."
            )

            c_left, c_right = st.columns([1, 1.4])
            with c_left:
                st.markdown("#### Игроков в каждом архетипе")
                bar = (
                    alt.Chart(counts)
                    .mark_bar()
                    .encode(
                        x=alt.X("players:Q", title="Игроков"),
                        y=alt.Y("archetype:N", sort="-x", title=None),
                        color=alt.Color("archetype:N", legend=None),
                        tooltip=["archetype", "players", alt.Tooltip("winrate:Q", format=".0%")],
                    )
                    .properties(height=300)
                )
                st.altair_chart(bar, width="stretch")
            with c_right:
                st.markdown("#### Урон в минуту vs контроль карты (вардинг)")
                scatter = (
                    alt.Chart(seg)
                    .mark_circle(size=60, opacity=0.5)
                    .encode(
                        x=alt.X("damage_per_min:Q", title="Урон/мин"),
                        y=alt.Y("vision_per_min:Q", title="Контроль карты (обзор), в минуту"),
                        color=alt.Color("archetype:N", title="Архетип"),
                        tooltip=["name", "archetype", "games",
                                 alt.Tooltip("winrate:Q", format=".0%"),
                                 alt.Tooltip("kda:Q", format=".2f")],
                    )
                    .interactive()
                    .properties(height=300)
                )
                st.altair_chart(scatter, width="stretch")

            st.markdown("#### Профиль архетипов (средние метрики)")
            st.caption("Средние показатели каждой группы — видно, чем они реально отличаются.")
            st.dataframe(
                counts.rename(columns={
                    "archetype": "Архетип", "players": "Игроков", "winrate": "Winrate",
                    "kda": "KDA", "cs": "CS/мин", "dmg": "Урон/мин",
                    "vision": "Обзор/мин", "gold": "Золото/мин",
                }),
                width="stretch", hide_index=True,
            )


# ---------- Качество данных ----------
with tab_quality:
    st.subheader("Качество данных")
    st.caption("Автоматические проверки данных — показывают, что данным можно доверять.")

    # --- живые проверки прямо в дашборде (тот же смысл, что в run_data_quality.py) ---
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

    st.markdown("#### Участников на матч")
    st.caption("Ожидаем ровно один столбец — «10».")
    st.dataframe(dist, width="stretch", hide_index=True)
