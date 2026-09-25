import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parser.extractor import extract, render  # noqa: E402

EXAMPLE = (ROOT / "data/raw/example.txt").read_text(encoding="utf-8")


def test_example_fields():
    f = extract(EXAMPLE, ner=None)
    assert f["project"] == "Мосбиржа"
    assert f["position"] == "Fullstack аналитик"
    assert f["grade"] == "Middle"
    assert f["experience"] == "от 2х лет"
    assert f["location"] == "РФ/РБ"
    assert f["rate"] == "обсуждаемая"
    assert f["duration"] == "длительный"
    assert f["request_number"] is None
    assert len(f["requirements"]) == 6
    assert f["requirements"][0] == "Знание Rest, интерации через брокеры * сообщений kafka/rabbit."
    assert len(f["nice_to_have"]) == 4
    assert f["tasks"] == []
    assert f["contacts"].startswith("Резюме можно отправить")


def test_render():
    out = render(extract(EXAMPLE, ner=None))
    assert out.startswith("Найден запрос\n\nНомер заявки: —")
    assert "Позиция: Fullstack аналитик" in out
    assert "\nБудет преимуществом:\nопыт аналитика" in out
    assert "Выполняемы задачи на проекте: —" in out


def test_empty():
    f = extract("", ner=None)
    assert all(not v for k, v in f.items() if k not in ("check", "post_kind"))
    assert f["post_kind"] == "short"
    assert "не найдена позиция" in f["check"]  # пустой пост — повод проверить вручную
    out = render(f)
    assert "Позиция: —" in out
    assert "⚠️ Проверить вручную" in out


def test_other_format():
    text = (
        "🔥 Java разработчик\n"
        "Номер заявки: 1234\n"
        "Уровень: Senior\n"
        "Рейт: 2500 руб/ч\n\n"
        "Задачи:\n- писать код\n- ревью\n\n"
        "Требования:\n• опыт не менее 5 лет\n\n"
        "Контакты: @hr_bot\n"
    )
    f = extract(text, ner=None)
    assert f["position"] == "Java разработчик"
    assert f["request_number"] == "1234"
    assert f["grade"] == "Senior"
    assert f["rate"] == "2500 руб/ч"
    assert f["tasks"] == ["писать код", "ревью"]
    assert f["requirements"] == ["опыт не менее 5 лет"]
    assert f["experience"] == "не менее 5 лет"
    assert f["contacts"] == "@hr_bot"


class _FakeNer:
    def predict(self, text):
        return {"project": ["ИгнорNER"], "tasks": ["задача из NER"], "request_number": ["77"]}


def test_ner_fills_gaps_only():
    f = extract(EXAMPLE, ner=_FakeNer())
    assert f["project"] == "Мосбиржа"
    assert f["tasks"] == ["задача из NER"]
    assert f["request_number"] == "77"
