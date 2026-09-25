#!/usr/bin/env python3
"""
Шаг 4. Нестрогая оценка по полям на тестовых постах.

Строгий F1 засчитывает кусок только при точных границах. Здесь поле считается
найденным, если ответ пересекается с эталоном DeepSeek по словам (>= 50%).
Сравнивает три режима: только regex, только модель, regex + модель.

    python scripts/eval_fields.py [--model model/vacancy-ner]
"""
import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import FIELDS, extract  # noqa: E402
from parser.ner_model import NerModel  # noqa: E402
from parser.regex_rules import LIST_FIELDS  # noqa: E402

_WORD = re.compile(r"\w+")


def words(s) -> set[str]:
    if isinstance(s, list):
        s = " ".join(s)
    return {w.lower() for w in _WORD.findall(s or "")}


def match(pred, gold) -> bool:
    p, g = words(pred), words(gold)
    return bool(p and g) and len(p & g) / len(g | p) >= 0.5


def test_records() -> list[dict]:
    # тот же сплит, что в build_ner_dataset.py
    records = [json.loads(l) for l in open("data/labeled.jsonl", encoding="utf-8") if l.strip()]
    random.Random(42).shuffle(records)
    return records[int(len(records) * 0.9):]


def ner_only(ner, text: str) -> dict:
    preds = ner.predict(text)
    return {f: (preds.get(f, []) if f in LIST_FIELDS else (preds.get(f) or [None])[0]) for f in FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="model/vacancy-ner")
    args = ap.parse_args()

    ner = NerModel(args.model)
    recs = test_records()
    modes = {
        "regex": lambda t: extract(t, ner=None),
        "model": lambda t: ner_only(ner, t),
        "regex+model": lambda t: extract(t, ner=ner),
    }
    hits = {m: {f: [0, 0] for f in FIELDS} for m in modes}  # [найдено верно, всего в эталоне]

    for i, r in enumerate(recs, 1):
        preds = {m: fn(r["text"]) for m, fn in modes.items()}
        for f in FIELDS:
            gold = r["fields"].get(f)
            if not gold:
                continue
            for m in modes:
                hits[m][f][1] += 1
                hits[m][f][0] += match(preds[m].get(f), gold)
        print(f"\r{i}/{len(recs)}", end="", flush=True)

    print(f"\n\nДоля полей, найденных верно (по смыслу), {len(recs)} тестовых постов:\n")
    print(f"{'поле':16s}" + "".join(f"{m:>14s}" for m in modes))
    for f in FIELDS:
        if hits["regex"][f][1]:
            print(f"{f:16s}" + "".join(f"{hits[m][f][0] / hits[m][f][1]:14.0%}" for m in modes))
    print(f"{'ИТОГО':16s}" + "".join(
        f"{sum(v[0] for v in hits[m].values()) / sum(v[1] for v in hits[m].values()):14.0%}" for m in modes))


if __name__ == "__main__":
    main()
