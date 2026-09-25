"""Разбиение поста на строки для построчной классификации."""
import re
from dataclasses import dataclass

LINE_LABELS = [
    "other", "header",
    "request_number", "project", "position", "grade", "experience", "duration",
    "rate", "requirements", "nice_to_have", "tasks", "location", "contacts",
]

_PREFIX = re.compile(r"^[^\w№(«\"@]*")          # маркеры списка, эмодзи
_LABEL = re.compile(r"^[\w\s/()-]{2,40}?:\s*")    # "Проект: " в начале строки
_HEADER = re.compile(r"^[^\w]*[\w\s/()-]{2,60}:\s*$")  # "Требования:" — строка-заголовок


@dataclass
class Line:
    raw: str      # строка как есть
    body: str     # без маркера и "Метка:"
    context: str  # последний заголовок секции выше (подсказка модели)


def split_lines(text: str) -> list[Line]:
    out, header = [], ""
    for raw in (text or "").split("\n"):
        raw = raw.strip()
        if not re.search(r"\w", raw):
            continue
        body = _PREFIX.sub("", raw)
        if _HEADER.match(raw):
            header = body.rstrip(": ")
        lab = _LABEL.match(body)
        if lab and len(body) > lab.end():
            body = body[lab.end():]
        out.append(Line(raw=raw, body=body.strip(), context=header))
    return out
