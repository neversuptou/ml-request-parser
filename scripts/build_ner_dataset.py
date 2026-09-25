#!/usr/bin/env python3
"""
Шаг 2. Разметка DeepSeek -> BIO-датасет для NER.

Каждое значение поля ищется в исходном тексте, найденный кусок
помечается B-FIELD/I-FIELD на уровне токенов.

Вход:  data/labeled.jsonl
Выход: data/ner_{train,val,test}.jsonl, data/labels.json

    python scripts/build_ner_dataset.py
"""
import json
import os
import random
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import FIELDS  # noqa: E402

from transformers import AutoTokenizer  # noqa: E402

MODEL_NAME = "distilbert-base-multilingual-cased"
IN_FILE = "data/labeled.jsonl"
MAX_LEN = 512
STRIDE = 128
LABELS = ["O"] + [f"{p}-{f.upper()}" for f in FIELDS for p in ("B", "I")]


MIN_POST_COVERAGE = 0.6  # посты, где найдено меньше значений, — шум, в обучение не идут
FUZZY_RATIO = 0.8
# стаж почти всегда внутри пункта требований (вложенность NER не умеет) — его берёт regex
NER_SKIP = {"experience"}

# DeepSeek склеивает несколько пунктов в одно значение через ";" или ". "
_FRAGMENT_SPLIT = re.compile(r"\s*;\s*|\.\s+(?=[А-ЯЁA-Z])|\n+")
# маркер списка / эмодзи в начале строки и "Метка:" перед значением
_LINE_PREFIX = re.compile(r"^[^\w№(«\"]*")
_LINE_LABEL = re.compile(r"^[\w\s/-]{2,40}?:\s*")


def _free(s: int, e: int, taken: list) -> bool:
    return all(e <= ts or s >= te for ts, te in taken)


def _exact(text: str, value: str, taken: list) -> tuple[int, int] | None:
    start = text.find(value)
    while start != -1:
        if _free(start, start + len(value), taken):
            return start, start + len(value)
        start = text.find(value, start + 1)
    pattern = r"\s+".join(re.escape(w) for w in value.split())
    for m in re.finditer(pattern, text, re.I):
        if _free(*m.span(), taken):
            return m.span()
    return None


def _line_candidates(text: str) -> list[tuple[int, int]]:
    """Содержимое строк без маркеров и без "Метка:" — кандидаты для нечёткого сравнения."""
    out, pos = [], 0
    for line in text.split("\n"):
        s = pos + len(_LINE_PREFIX.match(line).group(0))
        body = text[s:pos + len(line)]
        e = s + len(body.rstrip(" \t.,;💌"))
        if e - s > 2:
            out.append((s, e))
            lab = _LINE_LABEL.match(text[s:e])
            if lab and e - s - lab.end() > 1:
                out.append((s + lab.end(), e))
        pos += len(line) + 1
    return out


def _fuzzy(text: str, value: str, lines: list, taken: list) -> tuple[int, int] | None:
    v = value.lower()
    best, best_r = None, FUZZY_RATIO
    for s, e in lines:
        if not _free(s, e, taken) or abs((e - s) - len(v)) > max(len(v), 20):
            continue
        r = SequenceMatcher(None, v, text[s:e].lower()).ratio()
        if r >= best_r:
            best, best_r = (s, e), r
    return best


def find_spans(text: str, value: str, lines: list, taken: list) -> list[tuple[int, int]]:
    value = value.strip()
    if not value:
        return []
    span = _exact(text, value, taken) or _fuzzy(text, value, lines, taken)
    if span:
        return [span]
    # склеенное значение -> ищем по частям
    spans = []
    for frag in _FRAGMENT_SPLIT.split(value):
        frag = frag.strip(" .;")
        if len(frag) < 4:
            continue
        span = _exact(text, frag, taken + spans) or _fuzzy(text, frag, lines, taken + spans)
        if span:
            spans.append(span)
    return spans


def spans_for(text: str, fields: dict, stats: Counter) -> tuple[list[tuple[int, int, str]], float]:
    """-> (спаны, доля найденных значений)."""
    pairs = []
    for f in FIELDS:
        if f in NER_SKIP:
            continue
        value = fields.get(f)
        values = value if isinstance(value, list) else [value]
        pairs += [(f, v) for v in values if v and isinstance(v, str)]

    # Длинные значения первыми: "от 2х лет" внутри пункта требований
    # не должен отнимать весь пункт (NER не умеет вложенные сущности).
    lines = _line_candidates(text)
    taken, spans, found = [], [], 0
    for f, v in sorted(pairs, key=lambda p: -len(p[1])):
        stats[f"{f}_total"] += 1
        got = find_spans(text, v, lines, taken)
        if got:
            found += 1
            stats[f"{f}_found"] += 1
            taken += got
            spans += [(s, e, f.upper()) for s, e in got]
    return spans, (found / len(pairs) if pairs else 0.0)


def encode(tokenizer, text: str, spans: list, label2id: dict) -> list[dict]:
    enc = tokenizer(text, truncation=True, max_length=MAX_LEN, stride=STRIDE,
                    return_overflowing_tokens=True, return_offsets_mapping=True)
    windows = []
    for ids, mask, offsets in zip(enc["input_ids"], enc["attention_mask"], enc["offset_mapping"]):
        labels, prev = [], None
        for s, e in offsets:
            if s == e:
                labels.append(-100)
                prev = None
                continue
            tag = "O"
            for ss, se, name in spans:
                if s >= ss and e <= se:
                    tag = ("I-" if prev == (ss, name) else "B-") + name
                    prev = (ss, name)
                    break
            else:
                prev = None
            labels.append(label2id[tag])
        windows.append({"input_ids": ids, "attention_mask": mask, "labels": labels})
    return windows


def main():
    records = [json.loads(l) for l in open(IN_FILE, encoding="utf-8") if l.strip()]
    print(f"Записей: {len(records)}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    label2id = {l: i for i, l in enumerate(LABELS)}

    random.Random(42).shuffle(records)
    n = len(records)
    splits = {
        "train": records[: int(n * 0.8)],
        "val": records[int(n * 0.8): int(n * 0.9)],
        "test": records[int(n * 0.9):],
    }

    stats = Counter()
    for name, recs in splits.items():
        with open(f"data/ner_{name}.jsonl", "w", encoding="utf-8") as out:
            count = kept = 0
            for r in recs:
                spans, coverage = spans_for(r["text"], r["fields"], stats)
                if coverage < MIN_POST_COVERAGE:
                    continue
                kept += 1
                for w in encode(tokenizer, r["text"], spans, label2id):
                    out.write(json.dumps(w) + "\n")
                    count += 1
        print(f"{name}: {kept}/{len(recs)} постов (покрытие >= {MIN_POST_COVERAGE:.0%}), {count} окон")

    json.dump(LABELS, open("data/labels.json", "w", encoding="utf-8"), ensure_ascii=False)

    print("\nПокрытие (значение DeepSeek найдено в тексте):")
    for f in FIELDS:
        total = stats[f"{f}_total"]
        if total:
            print(f"  {f:16s} {stats[f'{f}_found'] / total:6.1%}  ({stats[f'{f}_found']}/{total})")


if __name__ == "__main__":
    main()
