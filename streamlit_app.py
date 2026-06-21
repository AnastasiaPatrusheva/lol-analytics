"""
LoL Analytics — дашборд на Streamlit.

Читает готовую звёздную схему (Parquet) напрямую через DuckDB — без отдельной БД,
как советовал наставник («DuckDB отлично читает Streamlit»). Те же данные, что в
Supabase, лежат локально в outputs/sql/star/*.parquet.

Запуск локально:   streamlit run streamlit_app.py
Деплой:            GitHub -> streamlit.app (нужны streamlit_app.py + outputs/sql/star/*.parquet + requirements.txt)
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

STAR_DIR = Path(__file__).parent / "outputs" / "sql" / "star"
TABLES = [
    "fact_participant", "dim_champion", "dim_match", "dim_player", "dim_role",
    "fact_participant_item", "dim_item", "item_stats",
]
POSITIONS = ["Все", "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

st.set_page_config(page_title="LoL Analytics", page_icon="🎮", layout="wide")


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    for table in TABLES:
        path = (STAR_DIR / f"{table}.parquet").as_posix()
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
    return con


@st.cache_data
def run(sql: str):
    return get_connection().execute(sql).df()


# ---------- боковая панель: общие фильтры ----------
st.sidebar.header("Фильтры")
source = st.sidebar.selectbox(
    "Источник данных", ["riot_full", "kaggle", "riot_api"],
    help="riot_full — большой набор (~26k матчей, патчи 16.7–16.12); "
         "kaggle — исторический срез; riot_api — собственная свежая выборка",
)
st.sidebar.caption("Данные: Riot API + Kaggle → Parquet → DuckDB. Учебный проект.")

st.title("🎮 LoL Analytics")
tab_overview, tab_champions, tab_items, tab_players, tab_duration, tab_meta = st.tabs(
    ["Обзор", "Чемпионы", "Предметы", "Игроки", "⏱ Длительность", "📊 Мета"]
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
        "Ранжировать по", ["Уилсон (надёжно)", "Сырой winrate"], horizontal=True,
        help="Уилсон = нижняя граница доверительного интервала: учитывает размер выборки",
    )
    min_games = col_c.slider("Минимум игр", 5, 100, 30, step=5)

    pos_filter = "" if position == "Все" else f"AND f.role_key = '{position}'"
    order_col = "wilson_low" if rank_by.startswith("Уилсон") else "winrate"

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
               CASE WHEN wilson_low > 0.5 THEN '🟢 значимо сильный'
                    WHEN wilson_high < 0.5 THEN '🔴 значимо слабый'
                    ELSE '⚪ в норме' END AS verdict
        FROM ci ORDER BY {order_col} DESC
    """)

    metric_title = "Winrate (нижняя граница Уилсона)" if order_col == "wilson_low" else "Winrate"
    st.subheader(f"Топ чемпионов ({position})")
    st.caption(
        "Цвет = статистическая значимость: 🟢 значимо сильный (интервал выше 50%), "
        "🔴 значимо слабый, ⚪ в норме (высокий % может быть шумом малой выборки)."
    )
    if champions.empty:
        st.info("Нет чемпионов с таким порогом игр. Снизь минимум игр.")
    else:
        chart = (
            alt.Chart(champions.head(20))
            .mark_bar()
            .encode(
                x=alt.X(f"{order_col}:Q", title=metric_title, axis=alt.Axis(format="%")),
                y=alt.Y("champion_name:N", sort="-x", title=None),
                color=alt.Color(
                    "verdict:N", title="Вердикт",
                    scale=alt.Scale(
                        domain=["🟢 значимо сильный", "⚪ в норме", "🔴 значимо слабый"],
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

        anomalies = champions[champions["verdict"].str.contains("значимо")]
        with st.expander(f"🔎 Аномалии меты: {len(anomalies)} чемпионов со значимым отклонением от 50%"):
            st.dataframe(anomalies, width="stretch", hide_index=True)

        st.dataframe(champions, width="stretch", hide_index=True)


# ---------- Предметы ----------
with tab_items:
    min_gold = st.slider(
        "Минимальная цена предмета (золото)", 0, 4000, 2000, step=250,
        help="Отсекает дешёвые предметы и триннкеты-варды, чтобы видеть «билдовые» предметы",
    )
    items = run(f"""
        SELECT item_name, purchases, winrate, gold_total
        FROM item_stats
        WHERE data_source = '{source}' AND gold_total >= {min_gold}
        ORDER BY purchases DESC
    """)

    st.subheader("Покупки × Winrate")
    st.caption("Правый верхний угол = популярные И эффективные предметы.")
    if items.empty:
        st.info("Нет предметов с таким порогом цены.")
    else:
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
        st.dataframe(
            items.sort_values("winrate", ascending=False),
            width="stretch", hide_index=True,
        )


# ---------- Игроки ----------
with tab_players:
    min_p_games = st.slider("Минимум матчей у игрока", 3, 50, 5, step=1)
    players = run(f"""
        SELECT p.summoner_name, p.puuid, p.source_tier,
               COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               AVG(f.kda) AS avg_kda,
               AVG(f.damage_per_min) AS avg_damage_per_min
        FROM fact_participant f
        JOIN dim_player p ON f.data_source = p.data_source AND f.puuid = p.puuid
        WHERE f.data_source = '{source}'
        GROUP BY p.summoner_name, p.puuid, p.source_tier
        HAVING COUNT(*) >= {min_p_games}
        ORDER BY games DESC, winrate DESC
    """)

    st.subheader("Профиль игрока (drill-down)")
    if players.empty:
        st.info("Нет игроков с таким порогом матчей.")
    else:
        players = players.copy()

        def make_label(row):
            # summoner_name бывает NaN (float) у части игроков — берём короткий puuid.
            name = row["summoner_name"]
            if not isinstance(name, str) or not name.strip():
                name = str(row["puuid"])[:12]
            return f"{name}  ({int(row['games'])} матчей)"

        players["label"] = players.apply(make_label, axis=1)
        choice = st.selectbox("Выбери игрока", players["label"])
        puuid = players.loc[players["label"] == choice, "puuid"].iloc[0]

        by_champion = run(f"""
            SELECT c.champion_name, f.role_key AS role,
                   COUNT(*) AS games,
                   AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
                   AVG(f.kda) AS avg_kda,
                   AVG(f.damage_per_min) AS avg_damage_per_min
            FROM fact_participant f
            JOIN dim_champion c ON f.champion_id = c.champion_id
            WHERE f.data_source = '{source}' AND f.puuid = '{puuid}'
            GROUP BY c.champion_name, f.role_key
            ORDER BY games DESC
        """)
        st.dataframe(by_champion, width="stretch", hide_index=True)
        st.caption("Топ игроков по числу матчей:")
        st.dataframe(
            players.drop(columns=["label"]).head(50),
            width="stretch", hide_index=True,
        )


# ---------- Длительность ----------
with tab_duration:
    min_b = st.slider("Минимум игр в каждой длине (короткие и длинные)", 5, 50, 15, step=5)
    st.subheader("Кто «скейлится» — сила чемпиона по длине матча")
    st.caption(
        "Δ = winrate в длинных играх (>32 мин) минус в коротких (<25 мин). "
        "Положительная (зелёная) = поздняя игра, отрицательная (красная) = ранняя."
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
        st.info("Мало данных при таком пороге. Снизь минимум игр.")
    else:
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
        st.caption("Сверху — скейлящиеся (сильнее в долгих играх), снизу — ранние пики.")
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
            "Переключи источник на **riot_full** — там 7 патчей (16.7–16.12)."
        )
    else:
        c1, c2, c3 = st.columns(3)
        patch_a = c1.selectbox("Патч A (раньше)", patches, index=len(patches) - 2)
        patch_b = c2.selectbox("Патч B (позже)", patches, index=len(patches) - 1)
        min_g = c3.slider("Минимум игр в каждом патче", 10, 200, 30, step=10)
        st.caption(
            f"Δ = winrate в патче {patch_b} минус в {patch_a}. "
            "🟢 вверх = усилились (баффы), 🔴 вниз = ослабли (нерфы)."
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
                       AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS wr
                FROM f GROUP BY champion_name, primary_class, patch
            ),
            piv AS (
                SELECT champion_name, primary_class,
                       MAX(CASE WHEN patch = '{patch_a}' THEN wr END) AS wr_a,
                       MAX(CASE WHEN patch = '{patch_b}' THEN wr END) AS wr_b,
                       MAX(CASE WHEN patch = '{patch_a}' THEN games END) AS g_a,
                       MAX(CASE WHEN patch = '{patch_b}' THEN games END) AS g_b
                FROM agg GROUP BY champion_name, primary_class
            )
            SELECT champion_name, primary_class, wr_a, wr_b,
                   (wr_b - wr_a) AS delta, g_a, g_b
            FROM piv
            WHERE g_a >= {min_g} AND g_b >= {min_g}
            ORDER BY delta DESC
        """)

        if cmp.empty:
            st.info("Нет чемпионов с достаточной выборкой в обоих патчах. Снизь минимум игр.")
        else:
            diverging = pd.concat([cmp.head(12), cmp.tail(12)])
            chart = (
                alt.Chart(diverging)
                .mark_bar()
                .encode(
                    x=alt.X("delta:Q", title=f"Δ winrate ({patch_b} − {patch_a})",
                            axis=alt.Axis(format="+%")),
                    y=alt.Y("champion_name:N", sort="-x", title=None),
                    color=alt.condition("datum.delta > 0", alt.value("#3fa45b"), alt.value("#d9534f")),
                    tooltip=[
                        "champion_name", "primary_class",
                        alt.Tooltip("wr_a:Q", format=".1%", title=patch_a),
                        alt.Tooltip("wr_b:Q", format=".1%", title=patch_b),
                        alt.Tooltip("delta:Q", format="+.1%", title="Δ"),
                    ],
                )
                .properties(height=520)
            )
            st.altair_chart(chart, width="stretch")
            st.caption(f"Сверху — кто усилился к патчу {patch_b}, снизу — кто ослаб.")
            st.dataframe(cmp, width="stretch", hide_index=True)
