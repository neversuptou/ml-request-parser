#!/usr/bin/env python3
"""
Построчный классификатор на DistilBERT: вход — пара (заголовок секции, строка), выход — поле.

Строки короткие (max_length 96), поэтому учится намного быстрее NER по окнам 512.

Вход:  data/lines_{train,val,test}.jsonl  (scripts/prepare_lines.py)
Выход: model/lines-bert/ (+ model_info.json)

    python scripts/train_lines_bert.py --epochs 2
"""
import argparse
import json
import os
import sys

import numpy as np
import torch
from sklearn.metrics import classification_report, f1_score
from transformers import (AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding,
                          Trainer, TrainingArguments)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.lines import LINE_LABELS  # noqa: E402

MODEL_NAME = "distilbert-base-multilingual-cased"
OUT_DIR = "model/lines-bert"
MAX_LEN = 96


def pos_hint(idx: int) -> str:
    return f"[{min(idx, 5)}]"  # номер строки в посте: первая строка почти всегда позиция


class LinesDataset(torch.utils.data.Dataset):
    def __init__(self, path, tokenizer, label2id):
        rows = [json.loads(l) for l in open(path, encoding="utf-8")]
        self.enc = tokenizer([f"{pos_hint(r['idx'])} {r['prev']}" for r in rows],
                             [r["text"] for r in rows], truncation="only_second", max_length=MAX_LEN)
        self.labels = [label2id[r["label"]] for r in rows]

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        item = {k: v[i] for k, v in self.enc.items()}
        item["labels"] = self.labels[i]
        return item


def keep_awake():
    """Windows: не уходить в сон по простою, пока жив процесс (как видеоплеер). Настройки не меняет."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--base", default=MODEL_NAME,
                    help="базовая модель (distilbert..., cointegrated/rubert-tiny2) или папка для дообучения")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--resume", action="store_true", help="продолжить с последнего чекпоинта после обрыва")
    args = ap.parse_args()
    keep_awake()
    ckpt_dir = args.out.rstrip("/") + "_checkpoints"

    label2id = {l: i for i, l in enumerate(LINE_LABELS)}
    id2label = {i: l for l, i in label2id.items()}
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=len(LINE_LABELS), id2label=id2label, label2id=label2id)

    train, val, test = (LinesDataset(f"data/lines_{s}.jsonl", tokenizer, label2id) for s in ("train", "val", "test"))
    print(f"строк: train {len(train)}, val {len(val)}, test {len(test)}")

    def compute_metrics(p):
        pred = np.argmax(p.predictions, axis=-1)
        return {"macro_f1": f1_score(p.label_ids, pred, average="macro"),
                "accuracy": float((pred == p.label_ids).mean())}

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=ckpt_dir,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            per_device_train_batch_size=args.bs,
            per_device_eval_batch_size=64,
            # чекпоинт каждые 800 шагов: обрыв (сон, перезагрузка) теряет максимум 800 шагов
            eval_strategy="steps",
            eval_steps=800,
            save_strategy="steps",
            save_steps=800,
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="macro_f1",
            weight_decay=0.01,
            warmup_ratio=0.05,
            logging_steps=200,
            report_to=[],
        ),
        train_dataset=train,
        eval_dataset=val,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
    )
    has_ckpt = os.path.isdir(ckpt_dir) and any(d.startswith("checkpoint-") for d in os.listdir(ckpt_dir))
    trainer.train(resume_from_checkpoint=bool(args.resume and has_ckpt))

    val_metrics = trainer.evaluate(val)
    out = trainer.predict(test)
    pred = np.argmax(out.predictions, axis=-1)
    names = [id2label[i] for i in range(len(LINE_LABELS))]
    print(classification_report(out.label_ids, pred, labels=list(range(len(names))), target_names=names,
                                digits=3, zero_division=0))
    report = classification_report(out.label_ids, pred, labels=list(range(len(names))), target_names=names,
                                   output_dict=True, zero_division=0)

    os.makedirs(args.out, exist_ok=True)
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    info = {
        "model_name": args.base, "version": "v1", "labels": LINE_LABELS,
        "max_length": MAX_LEN, "train_size": len(train),
        "val_macro_f1": round(val_metrics["eval_macro_f1"], 4),
        "test_macro_f1": round(report["macro avg"]["f1-score"], 4),
        "test_accuracy": round(report["accuracy"], 4),
        "per_field_f1": {n: round(report[n]["f1-score"], 4) for n in names},
    }
    json.dump(info, open(os.path.join(args.out, "model_info.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Сохранено в {args.out}: test macro F1={info['test_macro_f1']} accuracy={info['test_accuracy']}")


if __name__ == "__main__":
    main()
