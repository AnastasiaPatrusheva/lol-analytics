"""Вкладка «Игроки»: одна сущность в двух масштабах.

Сначала популяция целиком — распределение очков лиги и архетипы игроков, потом
карточка одного человека. Архетипы были отдельной вкладкой; связь между «какие
бывают игроки» и «вот конкретный игрок» при этом терялась.
"""
import altair as alt
import streamlit as st

from dashboard.data import run, download_csv, champion_images
from dashboard.tabs import segments
from dashboard.tabs.strength import _plural


def _player_name(row) -> str:
    n = row["name"]
    return n if isinstance(n, str) and n.strip() else str(row["puuid"])[:10]


# Очки лиги Riot отдаёт только для игроков, которых мы собирали сами через API,
# поэтому раздел всегда берёт этот источник, независимо от фильтра слева.
# Раньше он шёл через общий фильтр и на источнике по умолчанию пустовал.
LP_SOURCE = "riot_api"


def render(source: str) -> None:
    st.subheader("Сколько у игроков рейтинговых очков")
    lp = run(f"""
        SELECT league_points FROM dim_player
        WHERE data_source = '{LP_SOURCE}' AND league_points IS NOT NULL
    """)
    if lp.empty:
        st.caption("Очков лиги в данных пока нет: они появляются после сбора свежей "
                   "выборки через Riot API.")
    else:
        n = len(lp)
        st.info(
            "Этот раздел всегда показывает нашу собственную выборку, собранную через "
            "Riot API, — независимо от источника, выбранного слева. Очки лиги есть "
            "только в ней.",
            icon="📌",
        )
        st.caption(
            "Очки лиги (в игре их называют LP) — рейтинг игрока: чем их больше, тем выше "
            f"он в общем списке. Здесь {n} {_plural(n, 'игрок', 'игрока', 'игроков')} "
            "из самых верхних лиг. Столбик показывает, сколько человек набрали примерно "
            "одинаково."
        )
        lp_hist = (
            alt.Chart(lp)
            .mark_bar(color="#C8AA6E")
            .encode(
                x=alt.X("league_points:Q", bin=alt.Bin(maxbins=25), title="Очки лиги (LP)"),
                y=alt.Y("count()", title="Игроков"),
                tooltip=[alt.Tooltip("count()", title="игроков")],
            )
            .properties(height=220)
        )
        st.altair_chart(lp_hist, width="stretch")
    st.divider()

    # Популяция: какие вообще бывают игроки. Раньше это была отдельная вкладка.
    segments.render(source)

    st.divider()
    min_p_games = st.slider("Минимум матчей у игрока", 5, 100, 20, step=5)
    players = run(f"""
        SELECT p.riot_id_game_name AS name, p.puuid, p.source_tier,
               COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               wilson_low(AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END), COUNT(*)) AS wr_low,
               wilson_high(AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END), COUNT(*)) AS wr_high,
               (SUM(f.kills) + SUM(f.assists)) * 1.0 / GREATEST(SUM(f.deaths), 1) AS avg_kda,
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
    st.caption("Всё про одного человека: показатели, любимые чемпионы и роли. "
               "Выберите игрока из списка ниже.")
    if players.empty:
        st.info("Нет игроков с таким порогом. Снизьте минимум (богаче всего — источник riot_full).")
        return

    players = players.copy()
    def _matches(n: int) -> str:
        return f"{n} {_plural(n, 'матч', 'матча', 'матчей')}"

    players["label"] = players.apply(
        lambda r: f"{_player_name(r)} · {_matches(int(r['games']))} · "
                  f"побед {r['winrate']:.1%}",
        axis=1,
    )
    choice = st.selectbox("Игрок", players["label"])
    row = players[players["label"] == choice].iloc[0]
    puuid = row["puuid"]

    st.markdown(f"### {_player_name(row)}")
    cols = st.columns(7)
    cols[0].metric("Матчей", int(row["games"]))
    # Одна десятая, а не целые: у игроков доли плотно жмутся к половине,
    # и 49.6% против 50.4% при округлении до целых превращались в одинаковые 50%.
    cols[1].metric(
        "Доля побед", f"{row['winrate']:.1%}",
        help=f"Цифра точная только на вид. По {int(row['games'])} матчам настоящее умение "
             f"этого игрока лежит где-то между {row['wr_low']:.0%} и {row['wr_high']:.0%}. "
             "Чем меньше матчей, тем шире этот разбег и тем меньше значит само число.")
    cols[2].metric(
        "KDA", f"{row['avg_kda']:.2f}",
        help="Убийства и помощи, делённые на смерти, за все матчи игрока вместе. "
             "Больше единицы — игрок чаще помогает команде убить, чем погибает сам.")
    cols[3].metric("Урон/мин", f"{row['dmg_pm']:.0f}",
                   help="Сколько урона игрок наносит чемпионам противника за минуту матча.")
    cols[4].metric("Золото/мин", f"{row['gold_pm']:.0f}",
                   help="Сколько золота игрок зарабатывает за минуту. На золото покупаются предметы.")
    cols[5].metric(
        "CS/мин", f"{row['cs_pm']:.1f}",
        help="CS — сколько миньонов игрок добил за минуту. Миньоны — существа, которые "
             "сами идут по линиям карты; за каждого добитого игрок получает золото, "
             "поэтому CS показывает, насколько хорошо он зарабатывает.")
    cols[6].metric(
        "Обзор/мин", f"{row['vis_pm']:.2f}",
        help="Сколько карты игрок держит на виду за минуту: он ставит на карту "
             "наблюдателей, которые показывают, что происходит в этом месте.")

    st.markdown("**В среднем за игру**")
    kda_hint = f"Среднее значение за игру. Источник данных: {source}."
    kc = st.columns(3)
    kc[0].metric("Убийства", f"{row['k']:.1f}", help=kda_hint)
    kc[1].metric("Смерти", f"{row['d']:.1f}", help=kda_hint)
    kc[2].metric("Помощи", f"{row['a']:.1f}", help=kda_hint)

    champs = run(f"""
        SELECT c.champion_name, c.champion_id, COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate,
               wilson_low(AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END), COUNT(*)) AS wilson_low,
               (SUM(f.kills) + SUM(f.assists)) * 1.0 / GREATEST(SUM(f.deaths), 1) AS avg_kda
        FROM fact_participant f
        JOIN dim_champion c ON f.champion_id = c.champion_id
        WHERE f.data_source = '{source}' AND f.puuid = '{puuid}'
        GROUP BY c.champion_name, c.champion_id ORDER BY games DESC
    """)
    imgs = champion_images()
    # Тот же принцип, что на вкладке «Чемпионы»: ранжируем по нижней границе
    # Уилсона, а не по сырому winrate. Иначе «лучшим» становится чемпион с тремя
    # выигранными играми подряд. Порог в 10 матчей — чтобы цифра вообще что-то значила.
    MIN_CHAMP_GAMES = 10
    best_champ = (champs[champs["games"] >= MIN_CHAMP_GAMES]
                  .sort_values("wilson_low", ascending=False))
    if not best_champ.empty:
        b = best_champ.iloc[0]
        n = int(b["games"])
        # После «на» — предложный падеж: «на 1 матче», «на 111 матчах».
        st.success(
            f"Лучший чемпион игрока — **{b['champion_name']}**: {b['winrate']:.1%} побед "
            f"на {n} {_plural(n, 'матче', 'матчах', 'матчах')}."
        )
    else:
        st.caption(
            f"Ни на одном чемпионе нет {MIN_CHAMP_GAMES} матчей. На меньшем числе игр "
            "«любимый чемпион» чаще означает удачную серию, чем настоящее умение, "
            "поэтому мы такое не показываем."
        )

    # «Любимые чемпионы» и «Роли» идут друг под другом, а не в две колонки.
    # График чемпионов склеен из портретов и полос (hconcat), а склейка в Altair
    # не сжимается под ширину колонки: у неё фиксированный размер около 700 пикселей.
    # Когда колонка была уже (открыт фильтр, ноутбук), график залезал под соседние
    # «Роли»: полосы уходили под пончик, прятались число у первой полосы и цветовая
    # шкала. На всю ширину места хватает при любом обычном размере окна.
    st.markdown("#### Любимые чемпионы")
    favs = champs.head(12).copy()
    favs["image"] = favs["champion_id"].map(imgs)
    ysort = alt.EncodingSortField(field="games", op="max", order="descending")
    portraits = (
        alt.Chart(favs).mark_image(width=22, height=22)
        .encode(y=alt.Y("champion_name:N", sort=ysort, axis=None), url="image:N")
        .properties(width=26, height=360)
    )
    y_named = alt.Y("champion_name:N", sort=ysort, title=None,
                    axis=alt.Axis(labelPadding=6, domain=False, ticks=False))
    bars = (
        alt.Chart(favs).mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("games:Q", title="Игр", axis=alt.Axis(grid=True, domain=False)),
            y=y_named,
            color=alt.Color("winrate:Q", title="Побед",
                            scale=alt.Scale(scheme="redyellowgreen", domain=[0.3, 0.7])),
            tooltip=["champion_name", "games",
                     alt.Tooltip("winrate:Q", format=".1%"),
                     alt.Tooltip("avg_kda:Q", format=".2f")],
        )
        .properties(height=360)
    )
    vals = (
        alt.Chart(favs).mark_text(align="left", dx=5, fontSize=11, color="#cfd6d6")
        .encode(x=alt.X("games:Q"), y=y_named, text=alt.Text("games:Q"))
    )
    ch = alt.hconcat(portraits, (bars + vals), spacing=4).configure_view(strokeWidth=0)
    st.altair_chart(ch, width="stretch")

    roles = run(f"""
        SELECT r.role_name_ru AS role, COUNT(*) AS games,
               AVG(CASE WHEN f.win THEN 1.0 ELSE 0.0 END) AS winrate
        FROM fact_participant f
        JOIN dim_role r ON f.role_key = r.role_key
        WHERE f.data_source = '{source}' AND f.puuid = '{puuid}'
        GROUP BY r.role_name_ru ORDER BY games DESC
    """)
    st.markdown("#### Роли")
    # Пончик на всю ширину разросся бы до огромного — держим его в средней колонке.
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        rc = (
            alt.Chart(roles)
            .mark_arc(innerRadius=50)
            .encode(
                theta=alt.Theta("games:Q"),
                color=alt.Color("role:N", title="Роль"),
                tooltip=["role", "games", alt.Tooltip("winrate:Q", format=".1%")],
            )
            .properties(height=300)
        )
        st.altair_chart(rc, width="stretch")

    with st.expander("Все чемпионы игрока"):
        _, dl_col = st.columns([4, 1])
        with dl_col:
            download_csv(champs, "player_champions.csv", key="dl_player_champs", use_container_width=True)
        cshow = champs.copy()
        cshow.insert(0, "icon", cshow["champion_id"].map(imgs))
        st.dataframe(
            cshow[["icon", "champion_name", "games", "winrate", "avg_kda"]],
            hide_index=True, width="stretch",
            column_config={
                "icon": st.column_config.ImageColumn(" ", width="small"),
                "champion_name": "Чемпион",
                "games": st.column_config.NumberColumn("Игр"),
                "winrate": st.column_config.ProgressColumn(
                    "Побед", format="percent", min_value=0.0, max_value=1.0),
                "avg_kda": st.column_config.NumberColumn("KDA", format="%.2f"),
            },
        )

    st.markdown("#### Все игроки источника — по числу матчей")
    st.caption(
        "Колонка «Осторожно» — та же доля побед, но заниженная с учётом числа матчей. "
        "По ней видно, у кого высокий процент подкреплён игрой, а у кого держится "
        "на десятке удачных матчей."
    )
    hdr, dl = st.columns([4, 1])
    export = players.drop(columns=["label", "puuid", "wr_high"])
    with dl:
        download_csv(export, "players.csv", key="dl_players", use_container_width=True)
    tp = export.head(50).rename(columns={
        "name": "Игрок", "source_tier": "Лига", "games": "Матчей", "winrate": "Побед",
        "wr_low": "Осторожно",
        "avg_kda": "KDA", "dmg_pm": "Урон/мин", "gold_pm": "Золото/мин",
        "cs_pm": "CS/мин", "vis_pm": "Обзор/мин", "k": "Уб.", "d": "См.", "a": "Пом.",
    })
    st.dataframe(
        tp, hide_index=True, width="stretch",
        column_config={
            "Побед": st.column_config.ProgressColumn("Побед", format="percent",
                                                     min_value=0.0, max_value=1.0),
            "Осторожно": st.column_config.NumberColumn(
                "Осторожно", format="percent",
                help="Доля побед, заниженная с учётом того, сколько матчей сыграно"),
            "KDA": st.column_config.NumberColumn("KDA", format="%.2f"),
            "Урон/мин": st.column_config.NumberColumn("Урон/мин", format="%d"),
            "Золото/мин": st.column_config.NumberColumn("Золото/мин", format="%d"),
            "CS/мин": st.column_config.NumberColumn("CS/мин", format="%.1f"),
            "Обзор/мин": st.column_config.NumberColumn("Обзор/мин", format="%.2f"),
            "Уб.": st.column_config.NumberColumn("Уб.", format="%.1f"),
            "См.": st.column_config.NumberColumn("См.", format="%.1f"),
            "Пом.": st.column_config.NumberColumn("Пом.", format="%.1f"),
        },
    )
