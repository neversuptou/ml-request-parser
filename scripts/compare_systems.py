#!/usr/bin/env python3
"""
Сравнение с текущим продом: насколько верно поля разбирал DeepSeek / шаблон (то, что лежит в БД)
и насколько верно разбирает наша модель — на одних и тех же вручную проверенных постах.

Правила сравнения те же, что в field_score.py. В проде нет отдельного поля «Будет преимуществом»
(DeepSeek и шаблон сливают его в требования), поэтому для честности считаем два варианта:
  - строго по 11 полям;
  - «требования + преимущества» как одно поле (10 полей) — так прод не штрафуется за формат.

    python scripts/compare_systems.py [--from 34]
"""
import argparse
import ast
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import FIELDS, extract  # noqa: E402
from parser.line_model import LIST_FIELDS, load_line_model  # noqa: E402
from scripts.field_score import gold_fields, list_ok, same  # noqa: E402
from scripts.import_template_csv import COLUMNS  # noqa: E402

_BULLET = re.compile(r"^\s*(?:[*\-•–—·▪►●✅✔️🔹🔸]+|\d{1,2}[.)])\s*")
EVAL_FIELDS = [f for f in FIELDS if f != "experience"]


def prod_list(value: str) -> list[str]:
    """Список из БД: у DeepSeek — "['a', 'b']", у шаблона — многострочный текст."""
    v = (value or "").strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            return [str(x).strip() for x in ast.literal_eval(v) if str(x).strip()]
        except (ValueError, SyntaxError):
            pass
    items = [_BULLET.sub("", x).strip() for x in v.split("\n")]
    return [x for x in items if len(x) > 2 and not x.endswith(":")]


def prod_fields(row: dict) -> dict:
    out = {}
    for col, f in COLUMNS.items():
        v = row.get(col, "")
        out[f] = prod_list(v) if f in LIST_FIELDS else (v or "").strip()
    out["nice_to_have"] = []
    return out


_W = re.compile(r"\w+")


def lenient(a, b) -> bool:
    """Верно, если одно значение словами входит в другое ("DevOps Engineer" в строке
    "Срочно ищем Senior DevOps Engineer") или совпадают наполовину. Не штрафует краткость."""
    # основа слова (5 букв): "разработчик" = "разработчика", падеж не ошибка
    wa = {w.lower()[:5] for w in _W.findall(a or "")}
    wb = {w.lower()[:5] for w in _W.findall(b or "")}
    if not wa and not wb:
        return True
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    return inter / min(len(wa), len(wb)) >= 0.8 or inter / len(wa | wb) >= 0.5


def lenient_list(pred, gold) -> bool:
    if not gold and not pred:
        return True
    if not gold or not pred:
        return False
    joined_pred, joined_gold = " ".join(pred), " ".join(gold)
    hit = sum(lenient(g, joined_pred) or any(lenient(g, p) for p in pred) for g in gold)
    extra = sum(not (lenient(p, joined_gold) or any(lenient(p, g) for g in gold)) for p in pred)
    return hit / len(gold) >= 0.8 and extra / len(pred) <= 0.2


def score(pred: dict, gold: dict, merge_nice: bool) -> dict[str, bool]:
    if LENIENT:
        cmp_list, cmp_one = lenient_list, lenient
    else:
        cmp_list, cmp_one = list_ok, same
    res = {}
    for f in EVAL_FIELDS:
        if merge_nice and f == "nice_to_have":
            continue
        gv = gold.get(f, [])
        pv = pred.get(f) or ([] if f in LIST_FIELDS else "")
        if merge_nice and f == "requirements":
            gv = gv + gold.get("nice_to_have", [])
            pv = list(pv) + list(pred.get("nice_to_have") or [])
        res[f] = cmp_list(pv, gv) if f in LIST_FIELDS else cmp_one(pv, "; ".join(gv))
    return res


LENIENT = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--lenient", action="store_true", help="мягкое сравнение: краткий верный ответ не штрафуется")
    args = ap.parse_args()
    global LENIENT
    LENIENT = args.lenient

    csv.field_size_limit(10**9)
    rows = {r["Ссылка в Telegram"]: r for r in csv.DictReader(open("applications_with_text.csv", encoding="utf-8"))}
    posts = OrderedDict()
    for line in open("data/lines_test.jsonl", encoding="utf-8"):
        r = json.loads(line)
        posts.setdefault(r["post_id"], []).append(r)
    gold = json.load(open("data/review_gold.json", encoding="utf-8"))
    model = load_line_model()

    stats = Counter()
    for i, pid in enumerate(posts):
        if i < args.start or pid not in gold or pid not in rows or any("Ð" in r["text"] for r in posts[pid]):
            continue
        lines = posts[pid]
        g = gold_fields(lines, gold[pid])
        src = "DeepSeek" if rows[pid]["Обработано"] in ("ai", "cache") else "шаблон"
        ours = extract("\n".join(r["text"] for r in lines), model)
        prod = prod_fields(rows[pid])
        stats[(src, "posts")] += 1
        for merge in (False, True):
            for name, pred in (("прод", prod), ("наша", ours)):
                res = score(pred, g, merge)
                key = (src, name, merge)
                stats[key + ("ok",)] += sum(res.values())
                stats[key + ("n",)] += len(res)
                stats[key + ("perfect",)] += all(res.values())
                for f, ok in res.items():
                    stats[(src, name, merge, f)] += ok

    for merge in (False, True):
        title = "11 полей строго" if not merge else "10 полей (требования+преимущества вместе)"
        print(f"\n=== {title} ===")
        print(f"{'посты разбирал':15s} {'постов':>6s} {'прод':>8s} {'наша':>8s}   {'без ошибок: прод / наша':>24s}")
        for src in ("DeepSeek", "шаблон"):
            n = stats[(src, "posts")]
            if not n:
                continue
            p = stats[(src, "прод", merge, "ok")] / stats[(src, "прод", merge, "n")]
            o = stats[(src, "наша", merge, "ok")] / stats[(src, "наша", merge, "n")]
            print(f"{src:15s} {n:6d} {p:8.1%} {o:8.1%}   {stats[(src, 'прод', merge, 'perfect')]:>11d} / "
                  f"{stats[(src, 'наша', merge, 'perfect')]}")

    print("\n=== По полям, посты DeepSeek (10 полей) — прод / наша ===")
    n = stats[("DeepSeek", "posts")]
    for f in EVAL_FIELDS:
        if f == "nice_to_have" or not n:
            continue
        print(f"{f:15s} {stats[('DeepSeek', 'прод', True, f)] / n:6.0%} / {stats[('DeepSeek', 'наша', True, f)] / n:.0%}")


if __name__ == "__main__":
    main()
