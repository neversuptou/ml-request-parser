#!/usr/bin/env python3
"""
Эталон значений одиночных полей (как заполнил бы менеджер) и честное сравнение «прод vs наша».

Построчная разметка не видит полей внутри чужих строк ("ID:14918_... Senior в телеком" —
номер, грейд и проект в строке позиции), поэтому для одиночных полей нужен отдельный эталон.
Списки (требования, задачи) оцениваются по построчному эталону — там он честный.

    python scripts/field_gold.py show 34 38     # текст поста + наш ответ + ответ прода
    python scripts/field_gold.py set 34 '{"request_number": "14918", "grade": "Senior", ...}'
    python scripts/field_gold.py score          # прод vs наша по размеченным постам

Пустое значение в эталоне = в посте этого поля нет (верно ответить "—").
"""
import csv
import json
import os
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import extract  # noqa: E402
from parser.line_model import load_line_model  # noqa: E402
from scripts.compare_systems import lenient, lenient_list, prod_fields  # noqa: E402
from scripts.field_score import gold_fields  # noqa: E402

GOLD = "data/field_gold.json"
SCALARS = ["request_number", "project", "position", "grade", "duration", "rate", "location", "contacts"]
LISTS = ["requirements", "tasks"]  # nice_to_have сливаем с requirements — у прода его нет


def load():
    posts = OrderedDict()
    for line in open("data/lines_test.jsonl", encoding="utf-8"):
        r = json.loads(line)
        posts.setdefault(r["post_id"], []).append(r)
    csv.field_size_limit(10**9)
    rows = {r["Ссылка в Telegram"]: r for r in csv.DictReader(open("applications_with_text.csv", encoding="utf-8"))}
    gold = json.load(open(GOLD, encoding="utf-8")) if os.path.exists(GOLD) else {}
    return posts, rows, gold


def cmd_show(a, b):
    posts, rows, gold = load()
    model = load_line_model()
    for n, pid in list(enumerate(posts))[int(a):int(b)]:
        text = "\n".join(r["text"] for r in posts[pid])
        ours = extract(text, model)
        prod = prod_fields(rows[pid]) if pid in rows else {}
        src = rows.get(pid, {}).get("Обработано") or "шаблон"
        print(f"\n######## {n} [{src}] {'(размечен)' if pid in gold else ''}")
        print(text[:1400])
        print("---- поле | наша | прод")
        for f in SCALARS:
            print(f"{f:14s}| {str(ours.get(f) or '—')[:60]:60s} | {str(prod.get(f) or '—')[:60]}")


def cmd_set(n, values_json):
    posts, _, gold = load()
    pid = list(posts)[int(n)]
    vals = json.loads(values_json)
    gold[pid] = {f: vals.get(f, "") for f in SCALARS}
    json.dump(gold, open(GOLD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"эталон полей: {len(gold)} постов")


def cmd_score():
    posts, rows, gold = load()
    line_gold = json.load(open("data/review_gold.json", encoding="utf-8"))
    model = load_line_model()
    st = Counter()
    for pid, g in gold.items():
        text = "\n".join(r["text"] for r in posts[pid])
        systems = {"наша": extract(text, model)}
        if pid in rows:
            systems["прод"] = prod_fields(rows[pid])
        lg = gold_fields(posts[pid], line_gold[pid]) if pid in line_gold else None
        for name, pred in systems.items():
            ok_all = True
            for f in SCALARS:
                ok = lenient(str(pred.get(f) or ""), g.get(f, ""))
                st[(name, f)] += ok
                st[(name, "ok")] += ok
                st[(name, "n")] += 1
                ok_all &= ok
            if lg is not None:
                for f in LISTS:
                    gv = lg.get(f, []) + (lg.get("nice_to_have", []) if f == "requirements" else [])
                    pv = list(pred.get(f) or []) + (list(pred.get("nice_to_have") or []) if f == "requirements" else [])
                    ok = lenient_list(pv, gv)
                    st[(name, f)] += ok
                    st[(name, "ok")] += ok
                    st[(name, "n")] += 1
                    ok_all &= ok
            st[(name, "posts")] += 1
            st[(name, "perfect")] += ok_all
    print(f"Постов в эталоне полей: {len(gold)}\n")
    print(f"{'поле':15s} {'прод':>6s} {'наша':>6s}")
    for f in SCALARS + LISTS:
        row = [st[(s, f)] / st[(s, "posts")] if st[(s, "posts")] else 0 for s in ("прод", "наша")]
        print(f"{f:15s} {row[0]:6.0%} {row[1]:6.0%}")
    for s in ("прод", "наша"):
        if st[(s, "n")]:
            print(f"\n{s}: полей верно {st[(s, 'ok')] / st[(s, 'n')]:.1%}, "
                  f"заявок без ошибок {st[(s, 'perfect')]}/{st[(s, 'posts')]}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"show": cmd_show, "set": cmd_set, "score": cmd_score}[cmd](*args)
