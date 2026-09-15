"""Оформление в стиле League of Legends: фон-арт, шрифт Cinzel, золотая палитра.

Ассеты лежат в dashboard/assets (bg.jpg, cinzel.woff2) и встраиваются в CSS как
data-URI. Фон — приглушённый арт-антураж под тёмным оверлеем; данные — на панелях.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ASSETS = Path(__file__).resolve().parent / "assets"


def hero_card(title: str, name: str, value: str, img: str = "", accent: str = "#C8AA6E") -> str:
    """HTML карточки «картинка + подпись + имя + значение» (лидеры на «Силе» и «Предметах»)."""
    pic = (f"<img src='{img}' style='width:56px;height:56px;border-radius:10px;"
           f"border:1px solid #2f3a4d;flex:none'>") if img else ""
    return (
        "<div style='background:#10233a;border:1px solid #2f3a4d;border-radius:14px;"
        "padding:13px 15px;display:flex;gap:12px;align-items:center'>"
        f"{pic}<div style='min-width:0'>"
        f"<div style='font-size:11px;color:#a49b86;text-transform:uppercase;"
        f"letter-spacing:.05em'>{title}</div>"
        "<div style=\"font-family:'Palatino Linotype','Book Antiqua',serif;font-size:19px;"
        f"font-weight:600;color:#e8ecec\">{name}</div>"
        f"<div style='font-size:13px;color:{accent}'>{value}</div>"
        "</div></div>"
    )


@st.cache_data
def _b64(name: str) -> str:
    p = ASSETS / name
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


_TO_TOP_JS = """
(() => {
  // Заменяем кнопку, если она уже есть: страница не перезагружается при перезапуске
  // сервера, и старая версия кнопки иначе оставалась бы жить до ручного F5.
  const old = document.getElementById('to-top');
  if (old) old.remove();
  clearInterval(window.__toTopTimer);
  const b = document.createElement('button');
  b.id = 'to-top'; b.title = 'Наверх';
  b.setAttribute('aria-label', 'Наверх');
  // Стрелка — SVG, симметричная в своём viewBox, а не символ «↑»: у символа поля
  // задаёт шрифт, и на разных системах он садился ниже центра круга.
  b.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.6" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true" style="display:block">' +
    '<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>';
  Object.assign(b.style, {
    position: 'fixed', right: '28px', bottom: '28px', width: '46px', height: '46px',
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0',
    borderRadius: '50%', border: '1px solid rgba(200,170,110,.55)', cursor: 'pointer',
    background: 'linear-gradient(180deg,#C8AA6E,#785A28)', color: '#0A1428',
    zIndex: '999990',
    boxShadow: '0 4px 16px rgba(0,0,0,.55)', opacity: '0', pointerEvents: 'none',
    transition: 'opacity .2s'
  });
  document.body.appendChild(b);
  // Прокручивается обычно блок stMain, но на узком экране может прокручиваться сама
  // страница — смотрим оба.
  const scrollers = () =>
    [document.querySelector('[data-testid="stMain"]'), document.scrollingElement].filter(Boolean);
  // Мгновенно, без behavior: 'smooth': плавная прокрутка stMain в Chrome срабатывала
  // через раз, и клик иногда ничего не делал.
  b.onclick = () => scrollers().forEach(s => { s.scrollTop = 0; });
  const update = () => {
    // порог небольшой: «Главное» прокручивается всего на ~900 px, и при 600 кнопка
    // появлялась только у самого низа
    const show = scrollers().some(s => s.scrollTop > 200);
    b.style.opacity = show ? '1' : '0';
    b.style.pointerEvents = show ? 'auto' : 'none';
  };
  // Опрос вместо событий scroll: события не приходят, если прокрутили до появления
  // кнопки, а проверка трижды в секунду ничего не стоит.
  window.__toTopTimer = setInterval(update, 300);
  update();
})();
"""


def back_to_top() -> None:
    """Круглая кнопка «наверх», появляется, когда страницу прокрутили вниз.

    st.markdown скрипты не выполняет, поэтому код идёт через components.html. Его
    iframe пересоздаётся при перезапусках, поэтому скрипт вставляем в сам документ
    страницы: так кнопка и обработчик живут там, а не в iframe.
    """
    components.html(
        "<script>const d = window.parent.document, s = d.createElement('script');"
        f"s.textContent = {json.dumps(_TO_TOP_JS)}; d.head.appendChild(s);</script>",
        height=0,
    )


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
