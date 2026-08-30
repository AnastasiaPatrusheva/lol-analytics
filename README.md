# 🎮 LoL Analytics — аналитическая платформа по League of Legends

[![CI](https://github.com/AnastasiaPatrusheva/lol-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/AnastasiaPatrusheva/lol-analytics/actions/workflows/ci.yml)

Портфолио-проект по дата-инженерии и аналитике: полный путь данных — от сбора
(**Riot API** + большой архив матчей) до интерактивного дашборда на **Streamlit**,
со звёздной схемой, статистической строгостью и живым деплоем.

> **🔴 Живой дашборд:** **https://lol-analytics-asvnevc2yjcwphjea7dyru.streamlit.app/**
>
> **📖 Руководство пользователя:** [docs/РУКОВОДСТВО.md](docs/РУКОВОДСТВО.md) — источники, вкладки и словарь метрик.

---

## Чем выделяется

- **Три источника вместе, а не один.** Собственная свежая выборка (Riot API),
  большой архив `riot_full` (~26k матчей, 7 патчей) и Kaggle — приведены к единой
  схеме и сравниваются через поле `data_source` (не смешиваются вслепую).
- **Статистическая строгость, а не «голый winrate»:**
  - **интервал Уилсона** для силы чемпионов — высокий winrate на малой выборке
    считается шумом, а не силой;
  - **z-тест долей** в сравнении патчей — баф/нерф отличается от случайности;
  - **KMeans-сегментация** игроков по стилю (архетипы).
- **Настоящий ETL:** оркестратор со стадиями (`main.py`), слой контроля качества
  с кодами возврата, звёздная схема с мостом предметов, загрузка в БД.
- **SQL-аналитика в дашборде:** оконные функции (`RANK()`, `AVG() OVER (PARTITION BY …)`)
  для рейтинга чемпионов и отклонения от среднего по классу; прогноз winrate собранного
  состава по историческим долям побед в ролях.
- **Живой деплой** на Streamlit Cloud (дашборд читает Parquet напрямую через DuckDB).

## Архитектура пайплайна

```mermaid
flowchart LR
    API[Riot API<br/>Match-V5 / League-V4] --> TR[Transform<br/>единая схема]
    KAG[Kaggle xlsx] --> TR
    RAW[raw.zip<br/>~26k матчей] --> ING[ingest] --> TR
    DD[Data Dragon] --> REF[reference<br/>справочники]
    TR --> DQ[Data Quality<br/>авто-проверки]
    DQ --> STAR[Star schema<br/>DuckDB / Parquet]
    REF --> STAR
    STAR --> SEG[Segments<br/>KMeans]
    STAR --> LOAD[Load<br/>SQLite / Supabase]
    STAR --> DASH[Streamlit dashboard]
    SEG --> DASH
```

Всё управляется одним оркестратором (`main.py`, `argparse`); прогон логируется в `etl.log`.

| Стадия | Скрипт | Что делает |
|:--|:--|:--|
| `reference` | `fetch_reference.py` | справочники чемпионов/предметов из Data Dragon |
| `ingest` | `ingest_riot_full.py` | разбор архива `raw.zip` (~26k матчей, патчи 16.7–16.12) |
| `extract` | `riot_data_collector.py` | инкрементальный сбор через Riot API (retry, rate-limit, дедуп по логу) |
| `transform` | `build_common_analytics_layer.py` | источники → единая схема, фильтр ранкед-соло (`queue_id=420`), Parquet |
| `quality` | `run_data_quality.py` | серия авто-проверок (10 игроков в матче, winrate ≈ 0.5, нет дублей/отрицательных метрик…), падает с ненулевым кодом |
| `star` | `build_star_schema.py` | звёздная схема на DuckDB (факт + измерения + витрины) |
| `segments` | `build_player_segments.py` | витрина архетипов игроков (KMeans) |
| `load` | `load_to_warehouse.py` | звезда в SQLite (локально) или PostgreSQL/Supabase (`DATABASE_URL`) |

## Звёздная схема

```mermaid
erDiagram
    dim_champion   ||--o{ fact_participant : champion_id
    dim_match      ||--o{ fact_participant : "data_source + match_id"
    dim_player     ||--o{ fact_participant : puuid
    dim_role       ||--o{ fact_participant : role_key
    fact_participant ||--o{ fact_participant_item : участник
    dim_item       ||--o{ fact_participant_item : item_id
```

Факт `fact_participant` (1 строка = игрок в матче) + измерения
`dim_champion / dim_match / dim_player / dim_role`, мост «многие-ко-многим»
`fact_participant_item` → `dim_item`. Витрины: `item_stats`,
`champion_strength` (интервалы Уилсона), `champion_by_duration`, `player_segments`.

## Дашборд (вкладки)

| Вкладка | Что показывает |
|:--|:--|
| **📋 Обзор** | ключевые цифры (матчи, игроки, чемпионы), авто-инсайты, сравнение победителей с проигравшими |
| **🏆 Чемпионы** | топ по winrate с поправкой на число игр (**нижняя граница Уилсона**), рейтинг с рангом и отклонением от среднего по классу (**оконные функции SQL**), scatter «убийства vs смерти», подсветка значимых аномалий меты |
| **🛡️ Предметы** | «Покупки × Winrate» — какие предметы одновременно популярны *и* приносят победы |
| **👤 Игроки** | распределение игроков по очкам лиги (LP) и карточка игрока: метрики, любимые чемпионы, роли |
| **⏱ Длительность** | размах длительности матчей и кто сильнее в долгих играх, а кто в коротких |
| **📊 Мета** | сравнение патчей с проверкой статзначимости (z-тест долей): баф/нерф отделён от шума |
| **👥 Состав** | подбор пятёрки по ролям с прогнозом ожидаемого winrate (осторожная оценка по Уилсону) и профилями ролей на радарах |
| **🧩 Архетипы** | сегментация игроков (KMeans) по стилю: кэрри, саппорт, командный игрок… (с профилем каждой группы) |
| **✅ Качество** | живые проверки данных прямо в интерфейсе (участников на матч, дубли, сироты, баланс winrate) |
| **ℹ️ О метриках** | краткая справка по дашборду и словарь метрик прямо в интерфейсе |

## Словарь метрик

| Метрика | Что означает |
|:--|:--|
| **Winrate** | доля побед |
| **Winrate с поправкой на число игр** | не «сырой» процент побед, а намеренно заниженная (осторожная) оценка с учётом числа игр — **нижняя граница интервала Уилсона**, то есть нижний край диапазона, где реально может лежать истинный winrate. Чем меньше игр, тем шире диапазон и сильнее занижение: 70% на 5 играх (скорее везение) опускаются ниже стабильных 54% на 800 играх. По этой метрике строится рейтинг, чтобы наверх попадали действительно сильные, а не случайные лидеры малой выборки |
| **KDA** | (убийства + помощи) ÷ смерти — общая эффективность в схватках |
| **… в минуту** (CS, урон, золото, обзор) | значение, делённое на длину матча: так сравнимы игроки из коротких и длинных игр |
| **p-значение** | насколько вероятно, что различие случайно; p < 0.05 — вряд ли случайность, изменение реально |
| **Аномалия меты** | чемпион, чей winrate статистически значимо отличается от 50% |
| **Архетип** | группа игроков со схожим стилем (кластеризация), не официальная категория Riot |

## Запуск

```bash
pip install -r requirements.txt          # зависимости дашборда

# сборка данных локально (пайплайн)
python main.py transform                 # нормализация источников
python main.py quality                   # проверки качества
python main.py star                      # звёздная схема
python main.py all                       # всё сразу: transform → quality → star → segments → load

# витрина архетипов (KMeans) — нужен scikit-learn
pip install -r requirements-build.txt
python main.py segments

# дашборд
streamlit run streamlit_app.py
```

## Обновление данных (свежая выборка через API)

Сбор через Riot API — **локальная ручная операция** (на живом дашборде API не
вызывается: он читает готовый снимок Parquet). Нужен dev-ключ Riot — действует ~24 ч,
берётся на developer.riotgames.com.

```bash
# 1) ключ Riot в текущую сессию терминала (PowerShell):
$env:RIOT_API_KEY = "RGAPI-..."

# 2) одна команда: extract -> transform -> quality -> star
python main.py refresh --tier master --max-players 10 --matches-per-player 5
```

Стадия `refresh` сама прогоняет сбор из API, приведение к общей схеме, проверки
качества и пересборку звёздной схемы (`outputs/sql/star/*.parquet`). Стадии можно
запускать и по отдельности (`python main.py extract` / `transform` / `quality` / `star`).

Чтобы свежие данные попали на **живой дашборд**, закоммитьте обновлённые
`outputs/sql/star/*.parquet` в репозиторий и запушьте — Streamlit Cloud пересоберётся
автоматически.

## Структура

```
main.py                     оркестратор (стадии ETL)
streamlit_app.py            дашборд — точка входа (тонкая)
dashboard/                  модули дашборда: data, stats, tabs/ (по вкладке на файл)
scripts/                    стадии пайплайна
src/lol_utils/              общий код: config, логирование, метрики, пути
outputs/sql/star/*.parquet  звёздная схема + витрины (данные для дашборда)
data/reference/*.csv        справочники Data Dragon
tests/                      юнит-тесты (pytest)
requirements.txt            зависимости дашборда (рантайм)
requirements-build.txt      зависимости сборки (ETL + scikit-learn)
```

## Тесты

```bash
pip install -r requirements-build.txt
pytest tests/
```

Юнит-тесты на ключевые функции: производные метрики (`add_metrics`), разбор матча
(`flatten_match`), нормализация id, интервал Уилсона, ярлыки архетипов.

**CI:** тесты гоняются автоматически на каждый push и pull request в `main` через
GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); есть и ручной
запуск (workflow_dispatch). Живого обновления данных по расписанию нет намеренно:
dev-ключ Riot живёт ~24 ч, для cron-пайплайна нужен постоянный product-ключ.

## Docker

Запуск дашборда в контейнере:

```bash
docker compose up        # соберёт образ и поднимет дашборд на http://localhost:8501
```

`Dockerfile` кладёт в образ дашборд, пакет `dashboard/` и готовые Parquet-витрины —
внешняя БД не нужна.

## Стек

`Python` · `pandas` · `DuckDB` · `Parquet` · `scikit-learn` · `SQLAlchemy` ·
`Supabase / PostgreSQL` · `Streamlit` · `Altair`
Источники: **Riot API** (Match-V5, League-V4), **Data Dragon** (справочники), **Kaggle**.

## Заметки по данным и методике

- Анализ ограничен ранкед-соло (`queue_id=420`), чтобы роли и метрики были сопоставимы.
- Tier-list строится по нижней границе интервала Уилсона: высокий winrate на малой
  выборке — это шум, а не сила.
- Источники не смешиваются вслепую — сравниваются через `data_source`; основной
  объём даёт `riot_full` (~26k матчей, патчи 16.7–16.12).
- Большой архив `raw.zip` (~436 МБ, в репозиторий не входит) — набор Parquet-чанков,
  где каждый матч хранится сырым JSON формата Match-V5 (`match_id`, `_raw_json`);
  распаковывается в `data/riot_full/` и разбирается стадией `ingest`.
- Архетипы игроков — **сегменты, найденные кластеризацией** (не официальные классы
  Riot); официальные классы у Riot есть только для чемпионов (Fighter / Tank / Mage /
  Assassin / Marksman / Support).
