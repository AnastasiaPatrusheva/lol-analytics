"""Оформление в стиле League of Legends: фон-арт, шрифт Cinzel, золотая палитра.

Ассеты лежат в dashboard/assets (bg.jpg, cinzel.woff2) и встраиваются в CSS как
data-URI. Фон — приглушённый арт-антураж под тёмным оверлеем; данные — на панелях.
"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"


@st.cache_data
def _b64(name: str) -> str:
    p = ASSETS / name
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


def inject() -> None:
    bg = _b64("bg.jpg")
    font = _b64("cinzel.woff2")
    bg_layer = (
        f'url("data:image/jpeg;base64,{bg}") center top / cover fixed' if bg
        else "#0A1428"
    )
    st.markdown(
        f"""
        <style>
        @font-face {{
            font-family: 'Cinzel';
            src: url(data:font/woff2;base64,{font}) format('woff2');
            font-weight: 700; font-display: swap;
        }}
        /* Фон-арт с тёмным оверлеем (данные читаются на панелях) */
        [data-testid="stAppViewContainer"] {{
            background:
              radial-gradient(120% 90% at 50% 12%, rgba(10,20,40,.30), rgba(3,8,15,.84) 82%),
              linear-gradient(180deg, rgba(3,8,15,.45), rgba(3,8,15,.86)),
              {bg_layer};
        }}
        [data-testid="stHeader"] {{ background: transparent; }}
        /* Заголовок — Cinzel, золото */
        h1 {{
            font-family: 'Cinzel', 'Palatino Linotype', serif !important;
            color: #C8AA6E !important; letter-spacing: 2px; font-weight: 700;
            text-shadow: 0 2px 20px rgba(0,0,0,.7);
        }}
        h2, h3, h4 {{
            font-family: 'Palatino Linotype', 'Book Antiqua', serif !important;
            color: #F0E6D2;
        }}
        [data-testid="stMetricValue"] {{
            font-family: 'Palatino Linotype', serif !important; color: #F0E6D2;
        }}
        /* Вкладки — таблетки, активная золотая */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 6px; border-bottom: 1px solid rgba(200,170,110,.28);
        }}
        .stTabs button[role="tab"] {{
            border-radius: 999px; padding: 6px 14px; background: rgba(255,255,255,.04);
        }}
        .stTabs button[role="tab"] p {{ font-size: 15px; font-weight: 600; }}
        .stTabs button[role="tab"][aria-selected="true"] {{
            background: linear-gradient(180deg, #C8AA6E, #785A28);
        }}
        .stTabs button[role="tab"][aria-selected="true"] p {{ color: #0A1428; }}
        .stTabs [data-baseweb="tab-highlight"],
        .stTabs [data-baseweb="tab-border"] {{ background: transparent; }}
        /* Инфо-плашки (success/info) под тему: navy + золотая черта, не зелёные */
        [data-testid="stAlert"] {{
            background: rgba(16, 35, 58, .85) !important;
            border: 1px solid rgba(200, 170, 110, .28) !important;
            border-left: 3px solid #C8AA6E !important;
            border-radius: 10px !important;
        }}
        [data-testid="stAlert"] * {{ color: #F0E6D2 !important; }}
        /* Inline-код (`riot_full` и т.п.): бирюза вместо зелёного */
        [data-testid="stMarkdownContainer"] code {{
            color: #3fd0c9 !important;
            background: rgba(63, 208, 201, .10) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
