import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LINE_MODEL_PATH", "")  # в тестах модель берётся какая есть; без весов — правила

from fastapi.testclient import TestClient  # noqa: E402

import api.main as api_main  # noqa: E402

EXAMPLE = (ROOT / "data/raw/example.txt").read_text(encoding="utf-8")
PROD_KEYS = {"application_number", "project_title", "position", "level", "experience", "project_duration",
             "rate", "requirements", "tasks", "location", "contact_details"}

client = TestClient(api_main.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")


def test_parse_prod_format():
    r = client.post("/parse", json={"text": EXAMPLE})
    assert r.status_code == 200
    body = r.json()
    assert set(body["fields"]) == PROD_KEYS  # ключи — как колонки Application в tg_application
    f = body["fields"]
    assert f["position"] == "Fullstack аналитик"
    assert f["project_title"] == "Мосбиржа"
    assert f["level"] == "Middle"
    assert all(isinstance(v, str) or v is None for v in f.values())  # списки склеены в строку
    assert "Будет преимуществом:" in f["requirements"]
    assert body["post_kind"] is None
    assert body["needs_fallback"] is False
    assert body["rendered"].startswith("Найден запрос")


def test_digest_needs_fallback():
    digest = ("Добрый день, коллеги! Актуальные запросы:\n"
              "Запрос 1628 Бизнес аналитик Middle\nЗапрос 1650 Системный Аналитик Senior\n"
              "Запрос 1695 Инженер по ИБ Senior\nВопросы к @someone")
    body = client.post("/parse", json={"text": digest}).json()
    assert body["post_kind"] == "digest"
    assert body["needs_fallback"] is True


def test_not_vacancy():
    bench = ("🔥АКТУАЛЬНЫЙ БЕНЧ🔥\nАктуализирую бенч компании по сильным штатным специалистам\n"
             "Наталья И. Java разработчик Middle+\nМихаил З. Java разработчик Senior\n"
             "За резюме обращайтесь к @someone")
    assert client.post("/parse", json={"text": bench}).json()["post_kind"] == "not_vacancy"


def test_empty_text():
    body = client.post("/parse", json={"text": ""}).json()
    assert body["fields"]["position"] is None
    assert body["needs_fallback"] is True
