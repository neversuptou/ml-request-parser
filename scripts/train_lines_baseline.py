#!/usr/bin/env python3
"""
Быстрый построчный классификатор: TF-IDF (символьные n-граммы) + логистическая регрессия.
Учится за минуту на CPU. Признаки: сама строка, заголовок секции над ней, позиция в посте.

Выход: model/lines-baseline.joblib

    python scripts/train_lines_baseline.py
"""
import json
import os
import sys

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.line_features import LineFeatures  # noqa: E402

OUT = "model/lines-baseline.joblib"


def load(split):
    return [json.loads(l) for l in open(f"data/lines_{split}.jsonl", encoding="utf-8")]


def main():
    train, val, test = load("train"), load("val"), load("test")
    feats = LineFeatures().fit(train)
    clf = LogisticRegression(max_iter=2000, C=5, class_weight="balanced")
    clf.fit(feats.transform(train), [r["label"] for r in train])

    for name, rows in (("val", val), ("test", test)):
        pred = clf.predict(feats.transform(rows))
        print(f"\n=== {name} ===")
        print(classification_report([r["label"] for r in rows], pred, digits=3, zero_division=0))

    os.makedirs("model", exist_ok=True)
    joblib.dump({"features": feats, "clf": clf}, OUT)
    print("Сохранено:", OUT)


if __name__ == "__main__":
    main()
