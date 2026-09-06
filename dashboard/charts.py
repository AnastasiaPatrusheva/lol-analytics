"""Общие графики дашборда (используются несколькими вкладками)."""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

_SCALE = alt.Scale(domain=[-1.62, 1.62])
_XY = dict(x=alt.X("x:Q", axis=None, scale=_SCALE), y=alt.Y("y:Q", axis=None, scale=_SCALE))


def ring(r, n: int) -> pd.DataFrame:
    """Точки правильного n-угольника с радиусом r (скаляр или массив длины n).

    Первая вершина сверху, дальше по часовой стрелке. Колонка order задаёт порядок
    обхода вершин (иначе mark_line соединит их по возрастанию x); замыкать контур
    не нужно — это делает interpolate="linear-closed".
    """
    ang = np.arange(n) * 2 * np.pi / n - np.pi / 2
    return pd.DataFrame({"x": r * np.cos(ang), "y": r * np.sin(ang), "order": range(n)})


def normalize(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Доля от максимума по колонке: 1.0 у лидера, 0 если вся колонка нулевая."""
    return (df[cols] / df[cols].max()).fillna(0.0)


def radar_grid(df: pd.DataFrame, metrics: list[tuple[str, str]],
               titles: dict | None = None, height: int = 170) -> None:
    """Мини-радар на каждую строку df, в один ряд (small multiples).

    df      — индекс = название группы (архетип, роль), колонки = метрики;
    metrics — [(колонка, подпись оси)]; значения нормируются value/max по колонке,
              так что край радара = максимум среди групп;
    titles  — подпись над радаром для группы (по умолчанию — сам индекс).
    """
    n = len(metrics)
    norm = normalize(df, [c for c, _ in metrics])

    ref = (alt.Chart(ring(1.0, n))
           .mark_line(interpolate="linear-closed", strokeWidth=1, color="#2f3a4d")
           .encode(**_XY, order="order:Q"))
    labels = (alt.Chart(ring(1.34, n).assign(t=[lbl for _, lbl in metrics]))
              .mark_text(fontSize=9, color="#a49b86")
              .encode(**_XY, text="t:N"))
    for grp, col in zip(norm.index, st.columns(len(norm))):
        shape = (alt.Chart(ring(norm.loc[grp].to_numpy(), n))
                 .mark_line(interpolate="linear-closed", strokeWidth=2,
                            color="#C8AA6E", fill="#C8AA6E", fillOpacity=0.30)
                 .encode(**_XY, order="order:Q"))
        title = alt.TitleParams((titles or {}).get(grp, str(grp)),
                                anchor="middle", fontSize=13, color="#F0E6D2")
        col.altair_chart((ref + shape + labels).properties(height=height, title=title)
                         .configure_view(strokeWidth=0), width="stretch")
