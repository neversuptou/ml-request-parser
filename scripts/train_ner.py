#!/usr/bin/env python3
"""
Шаг 3. Дообучение DistilBERT на NER-разметку.

Вход:  data/ner_{train,val,test}.jsonl, data/labels.json
Выход: model/vacancy-ner/ (+ model_info.json)

    python scripts/train_ner.py --epochs 5
"""
import argparse
import json
import os

import numpy as np
import torch
from seqeval.metrics import classification_report, f1_score
from transformers import (AutoModelForTokenClassification, AutoTokenizer,
                          DataCollatorForTokenClassification, Trainer, TrainingArguments)

MODEL_NAME = "distilbert-base-multilingual-cased"
OUT_DIR = "model/vacancy-ner"


class JsonlDataset(torch.utils.data.Dataset):
    def __init__(self, path):
        self.rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--base", default=MODEL_NAME,
                    help="с чего учить: базовая модель или уже обученная (model/vacancy-ner) для дообучения")
    args = ap.parse_args()

    labels = json.load(open("data/labels.json", encoding="utf-8"))
    id2label = dict(enumerate(labels))
    label2id = {l: i for i, l in id2label.items()}

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForTokenClassification.from_pretrained(
        args.base, num_labels=len(labels), id2label=id2label, label2id=label2id)

    train, val, test = (JsonlDataset(f"data/ner_{s}.jsonl") for s in ("train", "val", "test"))

    def to_tags(pred_ids, gold_ids):
        pred, gold = [], []
        for p_row, g_row in zip(pred_ids, gold_ids):
            keep = [(p, g) for p, g in zip(p_row, g_row) if g != -100]
            pred.append([id2label[p] for p, _ in keep])
            gold.append([id2label[g] for _, g in keep])
        return pred, gold

    def compute_metrics(p):
        pred, gold = to_tags(np.argmax(p.predictions, axis=-1), p.label_ids)
        return {"f1": f1_score(gold, pred)}

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir="model/_checkpoints",
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            per_device_train_batch_size=args.bs,
            per_device_eval_batch_size=args.bs,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=1,
            load_best_model_at_end=True,
            metric_for_best_model="f1",
            weight_decay=0.01,
            report_to=[],
        ),
        train_dataset=train,
        eval_dataset=val,
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()

    val_f1 = trainer.evaluate(val)["eval_f1"]
    out = trainer.predict(test)
    pred, gold = to_tags(np.argmax(out.predictions, axis=-1), out.label_ids)
    report = classification_report(gold, pred, output_dict=True)
    print(classification_report(gold, pred))

    os.makedirs(OUT_DIR, exist_ok=True)
    trainer.save_model(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    info = {
        "model_name": MODEL_NAME,
        "base": args.base,
        "version": "v1",
        "labels": labels,
        "train_size": len(train),
        "val_f1": round(val_f1, 4),
        "test_f1": round(f1_score(gold, pred), 4),
        "per_field_f1": {k.lower(): round(v["f1-score"], 4)
                         for k, v in report.items() if k.isupper()},
    }
    json.dump(info, open(os.path.join(OUT_DIR, "model_info.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Сохранено в {OUT_DIR}: val_f1={info['val_f1']} test_f1={info['test_f1']}")


if __name__ == "__main__":
    main()
