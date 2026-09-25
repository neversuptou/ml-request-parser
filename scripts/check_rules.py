#!/usr/bin/env python3
"""
Насколько автоматическая разметка (data/lines_test.jsonl) совпадает с ручным эталоном
(data/review_gold.json) и где расходится. Запускать после scripts/prepare_lines.py.

    python scripts/check_rules.py [сколько примеров расхождений показать]
"""
import json
import sys
from collections import Counter, OrderedDict

top = int(sys.argv[1]) if len(sys.argv) > 1 else 8
posts = OrderedDict()
for line in open("data/lines_test.jsonl", encoding="utf-8"):
    r = json.loads(line)
    posts.setdefault(r["post_id"], []).append(r)
gold = json.load(open("data/review_gold.json", encoding="utf-8"))

ok = n = 0
diff, example = Counter(), {}
for pid, labels in gold.items():
    for r, g in zip(posts[pid], labels):
        n += 1
        ok += r["label"] == g
        if r["label"] != g:
            diff[(g, r["label"])] += 1
            example.setdefault((g, r["label"]), r["text"][:70])
print(f"Постов: {len(gold)}, строк: {n}. Авто-разметка совпадает с эталоном: {ok / n:.1%}")
for (g, a), cnt in diff.most_common(top):
    print(f"{cnt:3d}  эталон={g:14s} авто={a:14s} | {example[(g, a)]}")
