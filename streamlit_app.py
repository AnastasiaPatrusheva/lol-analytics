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
from dashboard.tabs import composition, items, overview, players, quality, strength

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
st.sidebar.caption(
    "Все вкладки пересчитываются под выбранный источник, источники не смешиваются. "
    "Таблицы скачиваются кнопкой «Скачать CSV», графики сохраняются картинкой через "
    "меню «⋯» в правом верхнем углу графика."
)

st.title("LoL Analytics")
# Шесть вкладок, каждая отвечает на один вопрос. Порядок — от вывода к разбору,
# от общего к частному, в конце основания, на которых всё держится.
tabs = st.tabs(
    [":material/lightbulb: Главное", ":material/emoji_events: Сила чемпиона",
     ":material/shield: Предметы", ":material/group: Игроки",
     ":material/groups: Состав", ":material/verified: Данные и качество"]
)
renderers = [
    overview.render, strength.render, items.render, players.render,
    composition.render, quality.render,
]
for tab, render in zip(tabs, renderers):
    with tab:
        render(source)

st.divider()
st.caption(
    "Не аффилировано с Riot Games. League of Legends — товарный знак Riot Games, Inc. "
    "Иллюстрации и справочники — Data Dragon."
)
