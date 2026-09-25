FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parser/ parser/
COPY api/ api/
COPY cli.py .

# Веса моделей в образ не кладём — монтируются томом в /app/model (см. docker-compose.yml):
#   model/lines-rubert/          — нейросеть (по умолчанию)
#   model/lines-baseline.joblib  — быстрая модель (запасная)
# Выбор — env LINE_MODEL_PATH; без моделей сервис работает на одних правилах (status=degraded).

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health', timeout=4)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]
