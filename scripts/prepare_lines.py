#!/usr/bin/env python3
"""
Выгрузка из БД (applications_with_text.csv) -> построчная разметка.

- Шаблонные заявки: метки из дословных полей (scripts/import_template_csv.line_labels).
- ИИ-заявки: метки по похожести строк на значения DeepSeek (build_line_dataset.auto_labels).
- Добивка regex: строка "Продолжительность проекта: 1-3 месяца" с меткой other получает
  поле по своей подписи — шаблон канала мог это поле не настраивать.
- Ручные правки (data/line_labels_manual.jsonl) перекрывают всё.

Выход: data/lines_{train,val,test}.jsonl  {"post_id","idx","prev","text","label","source"}

    python scripts/prepare_lines.py [applications_with_text.csv]
"""
import ast
import csv
import json
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.lines import LINE_LABELS, split_lines  # noqa: E402
from scripts.build_line_dataset import auto_labels, load_manual  # noqa: E402
from scripts.import_template_csv import COLUMNS, line_labels  # noqa: E402

IN_CSV = sys.argv[1] if len(sys.argv) > 1 else "applications_with_text.csv"

# подпись в начале строки -> поле (для добивки пропусков шаблона)
# "9. Локация спеца (РФ или без ограничений): РФ" — номер пункта и хвост подписи до двоеточия
# разделитель — ":" перед пробелом/концом ("1С:Предприятие" — не подпись) или тире в пробелах
_LINE_FIELD = [(re.compile(r"^[^\w№]*(?:\d{1,2}[.)]\s*)?(?:" + p + r")\b[^:\n]{0,40}?(?::(?:\s|$)|\s[\-–—]\s)", re.I), f)
               for p, f in [
    (r"номер\s+заявки|id\s+(?:запроса|вакансии)|заявка\s*№|№\s*заявки", "request_number"),
    (r"стек\s+и\s+уровень", "position"),
    (r"описание\s+проекта", "project"),
    (r"(?:обязательные|дополнительные)\s+требования", "requirements"),
    (r"проект|наименование\s+проекта|заказчик|сфера\s+деятельности\s+заказчика", "project"),
    (r"позиция|должность|вакансия|роль", "position"),
    (r"грейд|уровень|level|seniority", "grade"),
    (r"опыт(?:\s+работы)?", "experience"),
    (r"длительность(?:\s+проекта)?|продолжительность(?:\s+проекта)?|срок(?:\s+проекта|\s+привлечения)?", "duration"),
    (r"ставка|рейт|rate|бюджет|оплат\w*|формат\s+оплаты|условия\s+оплаты|заработная\s+плата|зарплата|з/п", "rate"),
    (r"локация(?:\s+проживания)?|география|гражданство|формат(?:\s+работы)?|местоположение|время\s+работы|часовой\s+пояс", "location"),
    (r"критично|обязательно|важно", "requirements"),
    (r"контакты?|связь|отклик|резюме\s+(?:присылать|направлять|отправлять)", "contacts"),
]]
_NICE = re.compile(r"плюс|преимуществ|желательно|ценятся|nice", re.I)
# первая строка-номер: "ВЗ-0234", "ID 175", "#1103/2", "💥Запрос №552💥", "id19"
_REQ_NUM_LINE = re.compile(r"^[^\w#№]*(?:#\s*\d[\d/-]*|[А-ЯA-Z]{1,4}-\d{2,}|id\s*:?\s*\d+|запрос\s*№\s*\d+)\W*$", re.I)
_REQ_NUM_START = re.compile(r"^[^\w#№]*(?:#\s*\d+|id\s*:?\s*\d+|запрос\s*№?\s*\d+)", re.I)
_INLINE_NICE = re.compile(r"^[^\w]*(?:будет\s+плюсом|плюсом\s+будет|плюсом|желательно|преимуществом)", re.I)
_SALARY = re.compile(r"^[^\w]*(?:заработная\s+плата|зарплата|з/п|доход)", re.I)
# "Резюме направляйте @x", "Вопросы — @y", почта
_CONTACT_LINE = re.compile(r"(?:резюме|cv|вопрос|пиш|направля|присыла|связ|обращ).{0,80}(?:@\w|\S+@\S+\.\w+)"
                           r"|^\W*\S+@\S+\.\w+\W*$|forms\.gle|гугл\s*форм|google\s*form", re.I)
_LOCATION_LINE = re.compile(r"^\W*(?:удал[её]нк|удал[её]нн|гибрид|офис\b|гражданство|локация|remote|hybrid|"
                            r"разница\s+во\s+времени|по\s+времени\s+мск|часовой)", re.I)
_EMPTY_VALUE = re.compile(r":\s*(?:нет|не\s+требуется|отсутствуют|-|—)\s*\.?\s*$", re.I)
# ссылки-навигация в конце поста, случайно попавшие в список
_NAV_LINE = re.compile(r"подробнее\s+о\s+вакансии|навигация:|#\w+\s*$", re.I)
_ROLE = re.compile(r"разработчик|аналитик|инженер|архитектор|тестировщик|менеджер|руководител|developer|engineer|"
                   r"analyst|devops|lead|designer|дизайнер|консультант|администратор|специалист|qa\b", re.I)


def parse_list(v: str) -> list[str]:
    v = (v or "").strip()
    if v.startswith("["):
        try:
            return [str(x) for x in ast.literal_eval(v)]
        except (ValueError, SyntaxError):
            pass
    return [v] if v else []


# заголовок секции -> поле для строк под ним (шаблоны части каналов, напр. SkillStaff,
# не вытаскивают списки — строки под "Требования:" оставались other)
_SECTION = [
    (re.compile(r"плюс|преимуществ|желательно|ценятся|дополнительн|приветствуется|nice to have|bonus", re.I),
     "nice_to_have"),
    (re.compile(r"требовани|навыки|стек|ожидаем|что\s+нужно|важно|обязательно|must|requirements|skills", re.I),
     "requirements"),
    (re.compile(r"задачи|обязанности|предстоит|чем\s+заниматься|функционал|responsibilities|tasks", re.I), "tasks"),
    (re.compile(r"контакт", re.I), "contacts"),
]
_SECTION_END = re.compile(r"резюме|направля|присыла|отклик|@\w|https?://|t\.me/|подробнее|навигация", re.I)
_HEADER_LINE = re.compile(r"^[^\w]*[\w\s/(),.+-]{2,60}:\s*$")  # и "4. Обязательные требования:"


LIST_SECTIONS = ("requirements", "tasks", "nice_to_have")


def _section_field(header_text: str) -> str | None:
    for rx, f in _SECTION:
        if rx.search(header_text):
            return f
    return None


def regex_fill(lines, labels: list[str]) -> list[str]:
    out, section, foreign = [], None, False
    for i, (ln, lab) in enumerate(zip(lines, labels)):
        if _REQ_NUM_LINE.match(ln.raw):
            out.append("request_number")
            continue
        if _HEADER_LINE.match(ln.raw):
            section = _section_field(ln.raw)
            # заголовок не про поле ("Присылать CV + данные:", "Этапы:") — список под ним не требования
            foreign = section is None
            out.append("header")
            continue
        if foreign and lab in ("requirements", "tasks", "nice_to_have"):
            lab = "other"
        if section in LIST_SECTIONS and lab in LIST_SECTIONS and lab != section:
            lab = section  # заголовок секции надёжнее «жадного» шаблона ("Задачи:" -> tasks)
        if lab in LIST_SECTIONS and _NAV_LINE.search(ln.raw):
            lab = "other"
        if lab != "other" and _EMPTY_VALUE.search(ln.raw):
            lab = "other"  # "Дополнительные требования к кандидату: Нет"
        if lab in LIST_SECTIONS and _LOCATION_LINE.match(ln.raw):
            lab = "location"
        if lab in LIST_SECTIONS:
            # "Ставка: ваша" / "Локация: РФ" внутри списка — подписанное одиночное поле
            for rx, f in _LINE_FIELD:
                if f not in LIST_SECTIONS and f != "experience" and rx.match(ln.raw):
                    lab = f
                    break
        if _SALARY.match(ln.raw):
            lab = "rate"
        if lab == "other" and _CONTACT_LINE.search(ln.raw):
            lab = "contacts"
        if lab == "other" and _LOCATION_LINE.match(ln.raw):
            lab = "location"
        if lab == "other":
            for rx, f in _LINE_FIELD:
                if rx.match(ln.raw) and len(ln.body) > 1:
                    lab = f
                    break
        if lab == "other" and section:
            if section != "contacts" and _SECTION_END.search(ln.raw):
                section = None  # "Резюме направляйте ..." — дальше уже не список требований
            else:
                lab = section
                if section == "contacts":
                    section = None  # под "Контакты:" — одна строка
        elif lab not in ("other", "requirements", "tasks", "nice_to_have", "experience"):
            section = None  # подписанное поле закрывает секцию (стаж внутри списка — нет)
        if lab in ("requirements", "nice_to_have", "experience") and _INLINE_NICE.match(ln.raw):
            lab = "nice_to_have"
        if lab == "requirements" and _NICE.search(ln.context):
            lab = "nice_to_have"
        if lab == "experience" and section in ("requirements", "nice_to_have"):
            lab = "requirements"  # пункт списка про стаж — это требование; стаж достаёт regex
        if lab in ("other", "position") and i < 2 and _REQ_NUM_START.match(ln.raw) and len(ln.body) > 25:
            lab = "position"  # "ID 175 Fullstack-аналитик ..." — номер + позиция, главное позиция
        out.append(lab)

    if "position" not in out:  # "👉Vue.js разработчик" второй строкой после номера
        for i, (ln, lab) in enumerate(zip(lines[:6], out[:6])):
            if lab == "other" and _ROLE.search(ln.raw) and len(ln.raw) < 120:
                out[i] = "position"
                break
    return out


def main():
    csv.field_size_limit(10**9)
    manual = load_manual()
    posts, stats = [], Counter()
    for row in csv.DictReader(open(IN_CSV, encoding="utf-8")):
        text = row["source_text"]
        link = row["Ссылка в Telegram"]
        lines = split_lines(text)
        if len(lines) < 3:
            continue
        fields = {f: row.get(c, "") for c, f in COLUMNS.items()}
        if row["Обработано"] in ("", "template"):
            source = "template"
            labels = line_labels(text, fields)
        else:
            source = "ai"
            for f in ("requirements", "tasks"):
                fields[f] = parse_list(fields[f])
            labels = auto_labels(text, fields)
        if labels is None or len(labels) != len(lines):
            stats["skip_" + source] += 1
            continue
        labels = regex_fill(lines, labels)
        if link in manual:
            labels, source = manual[link], "manual"
        posts.append({"id": link, "lines": lines, "labels": labels, "source": source,
                      "channel": row["template__title"]})
        stats[source] += 1

    random.Random(42).shuffle(posts)
    n = len(posts)
    splits = {"train": posts[: int(n * 0.8)], "val": posts[int(n * 0.8): int(n * 0.9)],
              "test": posts[int(n * 0.9):]}
    label_stats = Counter()
    for name, ps in splits.items():
        with open(f"data/lines_{name}.jsonl", "w", encoding="utf-8") as out:
            count = 0
            for p in ps:
                for i, (ln, lab) in enumerate(zip(p["lines"], p["labels"])):
                    assert lab in LINE_LABELS, lab
                    prev_text = p["lines"][i - 1].raw if i else ""
                    out.write(json.dumps({"post_id": p["id"], "idx": i, "prev": ln.context, "prev_text": prev_text,
                                          "text": ln.raw, "label": lab, "source": p["source"]},
                                         ensure_ascii=False) + "\n")
                    label_stats[lab] += 1
                    count += 1
        print(f"{name}: {len(ps)} постов, {count} строк")
    print("Источники:", dict(stats))
    print("Метки:", dict(label_stats.most_common()))


if __name__ == "__main__":
    main()
