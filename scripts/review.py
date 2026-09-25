#!/usr/bin/env python3
"""
Ручная проверка разметки тестовых постов и честная оценка модели.

    python scripts/review.py show 0 10          # посты 0..9: idx | авто-метка | модель | строка
    python scripts/review.py fix 3 "5:tasks,6:tasks"   # поправить метки строк поста №3
    python scripts/review.py ok 0 10            # отметить посты 0..9 проверенными (правки уже внесены)
    python scripts/review.py score              # точность модели на проверенных постах

Эталон: data/review_gold.json  {post_id: [метки строк]}
"""
import json
import os
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.lines import LINE_LABELS  # noqa: E402

PRED = "data/review_test_pred.json"
GOLD = "data/review_gold.json"
SHORT = {l: l[:8] for l in LINE_LABELS}


def posts():
    out = OrderedDict()
    for r in json.load(open(PRED, encoding="utf-8")):
        out.setdefault(r["post_id"], []).append(r)
    return out


def load_gold():
    return json.load(open(GOLD, encoding="utf-8")) if os.path.exists(GOLD) else {}


def save_gold(g):
    json.dump(g, open(GOLD, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def cmd_show(a, b):
    ps, gold = posts(), load_gold()
    for n, pid in list(enumerate(ps))[int(a):int(b)]:
        labels = gold.get(pid) or [r["label"] for r in ps[pid]]
        print(f"### {n} {'[проверен]' if pid in gold else ''}")
        for r, lab in zip(ps[pid], labels):
            mark = "*" if lab != r["pred"] else " "
            print(f"{r['idx']}|{SHORT[lab]:8s}|{mark}{SHORT[r['pred']]:8s}|{r['text'][:85]}")


def cmd_fix(n, spec):
    ps, gold = posts(), load_gold()
    pid = list(ps)[int(n)]
    labels = gold.get(pid) or [r["label"] for r in ps[pid]]
    for item in spec.split(","):
        idx, lab = item.split(":")
        full = next(l for l in LINE_LABELS if l.startswith(lab))
        for i in (range(int(idx.split("-")[0]), int(idx.split("-")[1]) + 1) if "-" in idx else [int(idx)]):
            labels[i] = full
    gold[pid] = labels
    save_gold(gold)


def cmd_ok(a, b):
    ps, gold = posts(), load_gold()
    for pid in list(ps)[int(a):int(b)]:
        gold.setdefault(pid, [r["label"] for r in ps[pid]])
    save_gold(gold)
    print(f"проверено постов: {len(gold)}")


def cmd_predict(model_path="model/lines-baseline.joblib"):
    """Предсказания текущей модели для тестовых строк -> data/review_test_pred.json."""
    import joblib
    bundle = joblib.load(model_path)
    rows = [json.loads(l) for l in open("data/lines_test.jsonl", encoding="utf-8")]
    for r, p in zip(rows, bundle["clf"].predict(bundle["features"].transform(rows))):
        r["pred"] = str(p)
    json.dump(rows, open(PRED, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"предсказано строк: {len(rows)}")


def cmd_score():
    ps, gold = posts(), load_gold()
    per = Counter()
    auto_ok = model_ok = total = 0
    for pid, labels in gold.items():
        for r, g in zip(ps[pid], labels):
            total += 1
            auto_ok += r["label"] == g
            model_ok += r["pred"] == g
            per[(g, "total")] += 1
            per[(g, "hit")] += r["pred"] == g
            per[(r["pred"], "predicted")] += 1
    print(f"Постов: {len(gold)}, строк: {total}")
    print(f"Автоматическая разметка верна: {auto_ok / total:.1%}")
    print(f"Модель верна:                  {model_ok / total:.1%}\n")
    print(f"{'поле':15s} {'полнота':>8s} {'точность':>9s} {'F1':>6s} {'строк':>6s}")
    f1s = []
    for lab in LINE_LABELS:
        t, h, p = per[(lab, "total")], per[(lab, "hit")], per[(lab, "predicted")]
        if not t:
            continue
        rec, prec = h / t, (h / p if p else 0)
        f1 = 2 * rec * prec / (rec + prec) if rec + prec else 0
        f1s.append(f1)
        print(f"{lab:15s} {rec:8.1%} {prec:9.1%} {f1:6.2f} {t:6d}")
    print(f"\nсредний F1 по полям: {sum(f1s) / len(f1s):.2f}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"show": cmd_show, "fix": cmd_fix, "ok": cmd_ok, "score": cmd_score, "predict": cmd_predict}[cmd](*args)
