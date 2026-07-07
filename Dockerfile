# Дашборд LoL Analytics. Читает готовые Parquet-витрины — внешняя БД не нужна.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY streamlit_app.py .
COPY dashboard/ ./dashboard/
COPY outputs/sql/star/ ./outputs/sql/star/

EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
