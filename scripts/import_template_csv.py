#!/usr/bin/env python3
"""
Выгрузка админки (CSV с полями) + исходные тексты -> data/labeled_template.jsonl

Тексты берутся из data/tg_texts.jsonl (fetch_tg_texts.py) или из колонки
source_text, если выгрузка сделана SQL-запросом из БД (см. GUIDE.md).

Шаблонные поля — дословные куски текста, но «жадные»: поле захватывает всё до
следующего маркера. Поэтому каждая строка поста получает поле, которое
НАЧАЛОСЬ последним выше неё (а не любое поле, в котором строка встречается).

    python scripts/import_template_csv.py "D:/Download browser/zapros_....csv"
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.lines import _HEADER, split_lines  # noqa: E402

TEXTS_FILE = "data/tg_texts.jsonl"
OUT_FILE = "data/labeled_template.jsonl"

# Шаблон «жадный»: одиночное поле (локация, рейт…) захватывает хвост до следующего
# маркера. Многострочными считаем только списки.
LIST_FIELDS = {"requirements", "tasks"}

COLUMNS = {
    "Номер заявки": "request_number",
    "Наименование проекта": "project",
    "Позиция": "position",
    "Уровень": "grade",
    "Опыт работы": "experience",
    "Длительность проекта": "duration",
    "Рейт": "rate",
    "Требования": "requirements",
    "Выполняемы задачи на проекте": "tasks",
    "Локация проживания": "location",
    "Контакты": "contacts",
}


def line_labels(text: str, fields: dict[str, str]) -> list[str] | None:
    """Метка каждой строки = поле, чьё значение начинается последним до этой строки."""
    starts = []  # (позиция начала значения в тексте, конец, поле)
    for f, v in fields.items():
        v = (v or "").strip()
        if len(v) < 2:
            continue
        pos = text.find(v[:60])  # начало значения; хвост мог быть обрезан/склеен
        if pos != -1:
            starts.append((pos, pos + len(v), f))
    if len(starts) < 3:
        return None  # текст не совпал с полями (сообщение отредактировано/удалено)
    starts.sort()

    labels, pos = [], 0
    raw_lines = text.split("\n")
    for raw in raw_lines:
        line_start = pos
        pos += len(raw) + 1
        if not raw.strip() or not any(c.isalnum() for c in raw):
            continue
        label = "other"
        line_end = line_start + len(raw)
        for s, e, f in starts:
            if f in LIST_FIELDS:
                if s < line_end and line_start < e:
                    label = f  # список может занимать много строк
            elif line_start <= s < line_end:
                label = f  # одиночное поле — только строка, где значение начинается
        if _HEADER.match(raw.strip()) and label in ("other", *LIST_FIELDS):
            label = "header"
        labels.append(label)
    return labels


def main():
    csv_path = sys.argv[1]
    csv.field_size_limit(10**9)
    texts = {}
    if os.path.exists(TEXTS_FILE):
        for l in open(TEXTS_FILE, encoding="utf-8"):
            r = json.loads(l)
            texts[r["link"]] = r["text"]

    n = kept = 0
    with open(OUT_FILE, "w", encoding="utf-8") as out:
        for row in csv.DictReader(open(csv_path, encoding="utf-8")):
            if row.get("Обработано", "") not in ("", "template"):
                continue  # ИИ пересказывал — берём только шаблонные
            link = row["Ссылка в Telegram"].strip()
            text = row.get("source_text") or texts.get(link)
            if not text:
                continue
            n += 1
            fields = {f: row.get(col, "") for col, f in COLUMNS.items()}
            labels = line_labels(text, fields)
            if labels is None or len(labels) != len(split_lines(text)):
                continue
            kept += 1
            out.write(json.dumps({"id": link, "text": text, "labels": labels,
                                  "channel": row.get("template__title", "")}, ensure_ascii=False) + "\n")
    print(f"С текстом: {n}, размечено: {kept} -> {OUT_FILE}")


if __name__ == "__main__":
    main()
