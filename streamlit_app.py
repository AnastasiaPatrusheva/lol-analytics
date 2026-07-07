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

from dashboard.data import SOURCES, SOURCE_DESC, check_source
from dashboard.tabs import (
    champions, duration, items, meta, overview, players, quality, segments,
)

st.set_page_config(page_title="LoL Analytics", page_icon="🎮", layout="wide")

# ---------- боковая панель: общие фильтры ----------
st.sidebar.header("Фильтры")
source = check_source(st.sidebar.selectbox("Источник данных", SOURCES))
st.sidebar.caption(SOURCE_DESC[source])
if st.sidebar.button("🔄 Обновить данные", help="Сбросить кэш и перечитать Parquet-файлы"):
    st.cache_data.clear()
    st.rerun()

st.title("🎮 LoL Analytics")
tabs = st.tabs(
    ["📋 Обзор", "🏆 Чемпионы", "🛡️ Предметы", "👤 Игроки", "⏱ Длительность",
     "📊 Мета", "🧩 Архетипы", "✅ Качество"]
)
renderers = [
    overview.render, champions.render, items.render, players.render,
    duration.render, meta.render, segments.render, quality.render,
]
for tab, render in zip(tabs, renderers):
    with tab:
        render(source)
