"""LoL Analytics — дашборд на Streamlit.

Читает готовую звёздную схему (Parquet) напрямую через DuckDB — отдельная БД не нужна.
Логика разнесена по модулям: dashboard/data.py (доступ к данным), dashboard/stats.py
(статистика), dashboard/tabs/*.py (вкладки, каждая — функция render(source)).

Запуск локально:  streamlit run streamlit_app.py
Деплой:           GitHub -> streamlit.app (нужны streamlit_app.py, dashboard/,
                  outputs/sql/star/*.parquet, requirements.txt)
"""
from __future__ import annotations

import streamlit as st

from dashboard import theme
from dashboard.data import SOURCES, SOURCE_DESC, check_source
from dashboard.tabs import (
    about, champions, composition, duration, items, meta, overview, players,
    quality, segments,
)

st.set_page_config(page_title="LoL Analytics", page_icon="🎮", layout="wide")

# Оформление в стиле League of Legends (фон, шрифт Cinzel, золото, таблетки-вкладки).
theme.inject()

# ---------- боковая панель: общие фильтры ----------
st.sidebar.header("Фильтры")
source = check_source(st.sidebar.selectbox("Источник данных", SOURCES))
st.sidebar.caption(SOURCE_DESC[source])
if st.sidebar.button("⟳ Обновить данные", type="primary",
                     help="Сбросить кэш и перечитать Parquet-файлы"):
    st.cache_data.clear()
    st.rerun()

st.title("LoL Analytics")
tabs = st.tabs(
    [":material/dashboard: Обзор", ":material/emoji_events: Чемпионы",
     ":material/shield: Предметы", ":material/group: Игроки",
     ":material/schedule: Длительность", ":material/trending_up: Мета",
     ":material/groups: Состав", ":material/hub: Архетипы",
     ":material/verified: Качество", ":material/info: О метриках"]
)
renderers = [
    overview.render, champions.render, items.render, players.render,
    duration.render, meta.render, composition.render, segments.render,
    quality.render, about.render,
]
for tab, render in zip(tabs, renderers):
    with tab:
        render(source)

st.divider()
st.caption(
    "Не аффилировано с Riot Games. League of Legends — товарный знак Riot Games, Inc. "
    "Иллюстрации и справочники — Data Dragon."
)
