#!/usr/bin/env python3
"""
Импорт готовой разметки DeepSeek (parse_dataset.jsonl) в формат data/labeled.jsonl.

Заменяет шаг label_with_deepseek.py, если посты уже размечены.

    python scripts/import_dataset.py [parse_dataset.jsonl]
"""
import ast
import json
import re
import sys

IN_FILE = sys.argv[1] if len(sys.argv) > 1 else "parse_dataset.jsonl"
OUT_FILE = "data/labeled.jsonl"

# поле в parse_dataset -> наше поле
FIELD_MAP = {
    "application_number": "request_number",
    "project_title": "project",
    "position": "position",
    "level": "grade",
    "experience": "experience",
    "project_duration": "duration",
    "rate": "rate",
    "requirements": "requirements",
    "tasks": "tasks",
    "location": "location",
    "contact_details": "contacts",
}
LIST_FIELDS = {"requirements", "tasks"}
_NICE = re.compile(r"^\s*(будет\s+(плюсом|преимуществом)|плюсом\s+будет|желательно)\s*:?\s*", re.I)


def parse_list(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    try:
        items = ast.literal_eval(value)
        if isinstance(items, (list, tuple)):
            return [str(i).strip() for i in items if str(i).strip()]
    except (ValueError, SyntaxError):
        pass
    return [value]


def convert(src: dict) -> dict:
    fields = {"nice_to_have": []}
    for old, new in FIELD_MAP.items():
        v = src.get(old)
        if new in LIST_FIELDS:
            fields[new] = parse_list(v)
        else:
            fields[new] = (v or "").strip() or None

    # "Будет плюсом ..." внутри требований -> nice_to_have
    reqs = []
    for item in fields["requirements"]:
        if _NICE.match(item):
            rest = _NICE.sub("", item).strip()
            if rest:
                fields["nice_to_have"].append(rest)
        else:
            reqs.append(item)
    fields["requirements"] = reqs
    return fields


def main():
    n_in = n_out = 0
    with open(OUT_FILE, "w", encoding="utf-8") as out:
        for line in open(IN_FILE, encoding="utf-8"):
            if not line.strip():
                continue
            n_in += 1
            r = json.loads(line)
            if r.get("parsed_by") not in ("ai", "template", "cache") or not r.get("text"):
                continue
            out.write(json.dumps({"id": str(r["id"]), "text": r["text"], "fields": convert(r["fields"])},
                                 ensure_ascii=False) + "\n")
            n_out += 1
    print(f"Прочитано {n_in}, записано {n_out} -> {OUT_FILE}")


if __name__ == "__main__":
    main()
