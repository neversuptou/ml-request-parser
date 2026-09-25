#!/usr/bin/env python3
"""
Оценка по полям: сколько полей заявки итоговый разбор (regex + модель) заполняет правильно.

Эталон — ручная построчная разметка (data/review_gold.json): значение поля собирается из
строк с этой меткой так же, как это делает модель. Сравнение:
  - одиночное поле: верно, если совпадает по словам >= 70% (порядок и знаки не важны);
  - список: верно, если найдено >= 80% пунктов эталона и лишних не больше 20%;
  - пустое в эталоне и пустое в разборе — тоже верно ("—" на своём месте).

    python scripts/field_score.py [--from 34]   # --from: только посты с этого номера (честная выборка)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import FIELDS, extract  # noqa: E402
from parser.line_model import LIST_FIELDS, _value, load_line_model  # noqa: E402

_W = re.compile(r"\w+")


def words(s):
    return {w.lower() for w in _W.findall(s or "")}


def same(a, b, need=0.7):
    wa, wb = words(a), words(b)
    if not wa and not wb:
        return True
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= need


def list_ok(pred, gold):
    if not gold and not pred:
        return True
    if not gold or not pred:
        return False
    hit = sum(any(same(g, p) for p in pred) for g in gold)
    extra = sum(not any(same(p, g) for g in gold) for p in pred)
    return hit / len(gold) >= 0.8 and extra / len(pred) <= 0.2


def gold_fields(rows, labels):
    out = {}
    for r, lab in zip(rows, labels):
        if lab in ("other", "header"):
            continue
        v = _value(r["text"], lab)
        if v:
            out.setdefault(lab, []).append(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--model", default=None,
                    help="model/lines-rubert (нейросеть) или model/lines-baseline.joblib; по умолчанию — лучшая есть")
    args = ap.parse_args()

    posts = OrderedDict()
    for line in open("data/lines_test.jsonl", encoding="utf-8"):
        r = json.loads(line)
        posts.setdefault(r["post_id"], []).append(r)
    ids = list(posts)
    gold = json.load(open("data/review_gold.json", encoding="utf-8"))
    model = load_line_model(args.model)
    print(f"модель: {type(model).__name__} ({args.model or 'по умолчанию'})")

    per, full_ok, n_posts = Counter(), 0, 0
    for i, pid in enumerate(ids):
        if i < args.start or pid not in gold or any("Ð" in r["text"] for r in posts[pid]):  # битая кодировка в БД
            continue
        rows = posts[pid]
        text = "\n".join(r["text"] for r in rows)
        pred = extract(text, model)
        g = gold_fields(rows, gold[pid])
        n_posts += 1
        post_ok = True
        for f in FIELDS:
            if f == "experience":
                continue  # стаж отдельно не размечали построчно — его достаёт regex из требований
            gv = g.get(f, [])
            if f in LIST_FIELDS:
                ok = list_ok(pred.get(f) or [], gv)
            else:
                ok = same(pred.get(f) or "", "; ".join(gv))
            per[(f, "ok")] += ok
            per[(f, "n")] += 1
            post_ok &= ok
        full_ok += post_ok

    fields = [f for f in FIELDS if f != "experience"]
    total_ok = sum(per[(f, "ok")] for f in fields)
    total = sum(per[(f, "n")] for f in fields)
    print(f"Постов: {n_posts}. Полей верно: {total_ok}/{total} = {total_ok / total:.1%}")
    print(f"В среднем на заявку: {total_ok / n_posts:.1f} из {len(fields)} полей верно")
    print(f"Заявок, разобранных без единой ошибки: {full_ok}/{n_posts}\n")
    for f in fields:
        print(f"{f:15s} {per[(f, 'ok')] / per[(f, 'n')]:6.0%}")


if __name__ == "__main__":
    main()
