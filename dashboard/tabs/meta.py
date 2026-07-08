"""Вкладка «Мета»: сравнение патчей с проверкой статзначимости (z-тест)."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard.data import run, table_with_download
from dashboard.stats import two_proportion_pvalue


def render(source: str) -> None:
    st.subheader("Сравнение патчей — сдвиги меты")
    patches_df = run(f"""
        SELECT split_part(game_version, '.', 1) || '.' || split_part(game_version, '.', 2) AS patch,
               COUNT(*) AS matches
        FROM dim_match
        WHERE data_source = '{source}' AND game_version IS NOT NULL
        GROUP BY 1 HAVING COUNT(*) >= 50 ORDER BY patch
    """)
    # Числовая сортировка патчей: 16.7 < 16.8 < 16.10 < 16.11 (а не как строки).
    patches = sorted(
        [p for p in patches_df["patch"].tolist() if p and p != "."],
        key=lambda x: [int(n) for n in x.split(".")],
    )

    if len(patches) < 2:
        st.info(
            f"У источника «{source}» меньше двух патчей с данными. "
            "Переключите источник на **riot_full** — там 7 патчей (16.7–16.12)."
        )
        return

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
        return

    cmp["p_value"] = cmp.apply(
        lambda r: two_proportion_pvalue(r["w_a"], r["g_a"], r["w_b"], r["g_b"]), axis=1
    )
    cmp["is_sig"] = cmp["p_value"] < 0.05
    sig = cmp[cmp["is_sig"]]

    only_sig = st.checkbox(
        f"Только значимые изменения (p < 0.05) — их {len(sig)} из {len(cmp)}",
        value=False,
        help="Оставляет только те изменения winrate, которые слишком велики, чтобы быть "
             "случайностью (статистически значимые). Мелкие колебания на малом числе игр "
             "отфильтровываются как шум. Тест приближённый: матчи не полностью независимы "
             "(один игрок встречается в нескольких).",
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
        return

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
    table_with_download(view, "Сравнение патчей (таблица)", "patch_comparison.csv",
                        key="dl_meta",
                        caption="Насыщенные столбцы — значимые сдвиги (p<0.05); "
                                "блёклые — в пределах шума. Сверху усиление, снизу ослабление.")
