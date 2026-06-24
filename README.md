# 🎮 LoL Analytics — аналитическая платформа по League of Legends

Учебный проект дата-инженерии и аналитики: полный путь данных от сбора через **Riot API**
до интерактивного дашборда на **Streamlit**.

> **🔴 Живой дашборд:** **https://lol-analytics-asvnevc2yjcwphjea7dyru.streamlit.app/**

---

## Что внутри

Конвейер разбит на слои и управляется одним оркестратором (`main.py`, `argparse`);
весь прогон логируется в `etl.log`:

```
Riot API ─┐
          ├─► Transform ─► Data Quality ─► Star schema ─► Load ─► BI
Kaggle ───┘   (общая        (12 проверок)   (DuckDB)       (DB)   (Streamlit /
Data Dragon    схема)                                              DataLens)
```

- **Extract** — `scripts/riot_data_collector.py`: инкрементальный сбор матчей через Riot API (retry, rate-limit, дедуп). `scripts/ingest_riot_full.py`: разбор большого датасета (~26k матчей, 7 патчей) из сырого JSON Match-V5.
- **Transform** — `scripts/build_common_analytics_layer.py`: два источника → единая схема, фильтр ранкед-соло (`queue_id=420`), хранение в **Parquet**.
- **Data Quality** — `scripts/run_data_quality.py`: 12 авто-проверок (10 игроков в матче, winrate ≈ 0.5, нет дублей/отрицательных метрик и т.д.), падает с ненулевым кодом.
- **Star schema** — `scripts/build_star_schema.py`: факт `fact_participant` + измерения `dim_champion / dim_match / dim_player / dim_role` + мост предметов `fact_participant_item` → `dim_item`. Витрины: `item_stats`, `champion_strength` (с **доверительными интервалами Уилсона**), `champion_by_duration`.
- **Load** — `scripts/load_to_warehouse.py`: звезда в SQLite (локально) или PostgreSQL/Supabase (`DATABASE_URL`).
- **BI** — `streamlit_app.py`: дашборд читает Parquet напрямую через DuckDB.

## Дашборд (вкладки)

- **Обзор** — KPI (матчи, игроки, чемпионы), победители vs проигравшие.
- **Чемпионы** — топ по winrate с поправкой на размер выборки (**нижняя граница Уилсона**), подсветка статистических аномалий меты.
- **Предметы** — «Покупки × Winrate» (какие предметы популярны И эффективны).
- **Игроки** — профиль игрока: имя (Riot ID), плитки метрик (KDA, CS, урон / золото / vision в минуту), любимые чемпионы, роли.
- **Длительность** — «скейлящиеся» чемпионы: разница winrate в длинных и коротких играх.
- **Мета** — сравнение патчей: кто усилился (баффы) и ослаб (нерфы) между версиями.

## Запуск

```bash
pip install -r requirements.txt

# собрать данные локально (пайплайн)
python main.py transform     # нормализация источников
python main.py quality       # проверки качества
python main.py star          # звёздная схема
python main.py all           # всё сразу (transform → quality → star → load)

# дашборд
streamlit run streamlit_app.py
```

Свежий сбор через API: `python main.py extract --tier master --max-players 10 --matches-per-player 5`
(нужен ключ Riot в `RIOT_API_KEY`).

## Стек

`Python` · `pandas` · `DuckDB` · `Parquet` · `SQLAlchemy` · `Supabase/PostgreSQL` · `Streamlit` · `Altair`
Источники: **Riot API** (Match-V5, League-V4), **Data Dragon** (справочники), **Kaggle**.

## Заметки по данным

- Анализ ограничен ранкед-соло (`queue_id=420`), чтобы роли и метрики были сопоставимы.
- Tier-list строится по нижней границе интервала Уилсона: высокий winrate на малой выборке — это шум, а не сила.
- Основной источник `riot_full` — ~26k матчей по 7 патчам (16.7–16.12); плюс Kaggle и собственная API-выборка. Источники сравниваются через поле `data_source`.
