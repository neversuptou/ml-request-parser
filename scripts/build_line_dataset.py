#!/usr/bin/env python3
"""
Построчная разметка: каждая строка поста -> одно поле (или other).

Черновик меток строится автоматически по разметке учителя (data/labeled.jsonl):
строка получает поле, чьё значение с ней лучше всего совпадает. Ручные правки
лежат в data/line_labels_manual.jsonl и перекрывают черновик.

Выход: data/lines_{train,val,test}.jsonl  {"post_id", "idx", "prev", "text", "label"}

    python scripts/build_line_dataset.py
"""
import json
import os
import random
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.lines import _HEADER, LINE_LABELS, split_lines  # noqa: E402

IN_FILE = "data/labeled.jsonl"
MANUAL_FILE = "data/line_labels_manual.jsonl"
MATCH_RATIO = 0.6
_NICE_HEADER = re.compile(r"плюс|преимуществ|желательно|nice", re.I)
_FRAGMENT_SPLIT = re.compile(r"\s*;\s*|\.\s+(?=[А-ЯЁA-Z])|\n+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .;,").lower()


def auto_labels(text: str, fields: dict) -> list[str]:
    lines = split_lines(text)
    values = []  # (field, normalized value)
    for f, v in fields.items():
        for x in (v if isinstance(v, list) else [v]):
            if not x or not isinstance(x, str):
                continue
            values.append((f, _norm(x)))
            if f in ("requirements", "tasks", "nice_to_have"):
                values += [(f, _norm(p)) for p in _FRAGMENT_SPLIT.split(x) if len(p.strip()) > 3]

    labels = []
    for ln in lines:
        body = _norm(ln.body)
        best, best_score = "other", MATCH_RATIO
        for f, v in values:
            if not v or not body:
                continue
            if v == body:
                score = 1.0
            elif v in body and len(v) / len(body) >= 0.3:
                score = 0.9  # "Проект: Мосбиржа" содержит значение "мосбиржа"
            elif body in v and len(body) >= 10:
                score = 0.85  # строка — часть склеенного значения
            else:
                score = SequenceMatcher(None, v, body).ratio()
            if score > best_score:
                best, best_score = f, score
        if _HEADER.match(ln.raw) and best_score < 0.9:
            best = "header"
        elif best == "requirements" and _NICE_HEADER.search(ln.context):
            best = "nice_to_have"  # учитель сливал "Будет плюсом" в требования
        labels.append(best)
    return labels


def load_manual() -> dict[str, list[str]]:
    if not os.path.exists(MANUAL_FILE):
        return {}
    out = {}
    for line in open(MANUAL_FILE, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r["labels"]
    return out


def main():
    records = [json.loads(l) for l in open(IN_FILE, encoding="utf-8") if l.strip()]
    manual = load_manual()
    random.Random(42).shuffle(records)
    n = len(records)
    splits = {"train": records[: int(n * 0.8)], "val": records[int(n * 0.8): int(n * 0.9)],
              "test": records[int(n * 0.9):]}

    stats = Counter()
    for name, recs in splits.items():
        with open(f"data/lines_{name}.jsonl", "w", encoding="utf-8") as out:
            count = 0
            for r in recs:
                lines = split_lines(r["text"])
                labels = manual.get(r["id"]) or auto_labels(r["text"], r["fields"])
                if len(labels) != len(lines):
                    print(f"пропуск {r['id']}: {len(labels)} меток на {len(lines)} строк")
                    continue
                for i, (ln, lab) in enumerate(zip(lines, labels)):
                    assert lab in LINE_LABELS, lab
                    out.write(json.dumps({"post_id": r["id"], "idx": i, "prev": ln.context,
                                          "text": ln.raw, "label": lab}, ensure_ascii=False) + "\n")
                    stats[lab] += 1
                    count += 1
        print(f"{name}: {len(recs)} постов, {count} строк")
    print(f"\nРучная разметка: {len(manual)} постов")
    print("Метки:", dict(stats.most_common()))


if __name__ == "__main__":
    main()
