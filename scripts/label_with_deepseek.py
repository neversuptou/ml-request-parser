#!/usr/bin/env python3
"""
Шаг 1. Разметка постов DeepSeek-учителем (разово).

Вход:  data/raw/*.txt   (посты разделены строкой "---")
       data/raw/*.jsonl ({"text": ...})
Выход: data/labeled.jsonl  {"id", "text", "fields"}

Повторный запуск продолжает с места остановки.

    python scripts/label_with_deepseek.py [--limit 100]
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser.extractor import FIELDS  # noqa: E402

RAW_DIR = "data/raw"
OUT_FILE = "data/labeled.jsonl"

PROMPT = """Ты извлекаешь поля из поста с вакансией. Верни JSON с ключами:
request_number, project, position, grade, experience, duration, rate,
requirements, nice_to_have, tasks, location, contacts.

Правила:
- Значения КОПИРУЙ ИЗ ТЕКСТА ДОСЛОВНО, символ в символ. Не перефразируй, не исправляй опечатки.
- Если поля в тексте нет — null (для списков — []).
- requirements, nice_to_have, tasks — списки, один пункт = один элемент, без маркера (*, -, •).
- position — название должности. grade — Junior/Middle/Senior/Lead и т.п.
- experience — только фраза про стаж, например "от 2х лет".
- rate — ставка/рейт. contacts — как откликнуться.
- nice_to_have — пункты "Будет преимуществом"/"Плюсом будет".

Текст:
"""


def load_env():
    if os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def read_posts() -> list[str]:
    posts = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.txt"))):
        chunks = open(path, encoding="utf-8").read().split("\n---\n")
        posts += [c.strip() for c in chunks if c.strip()]
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                text = json.loads(line).get("text", "").strip()
                if text:
                    posts.append(text)
    return posts


def post_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def label(client, text: str) -> dict:
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": PROMPT + text}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(r.choices[0].message.content)
            return {f: data.get(f) for f in FIELDS}
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  retry {attempt + 1}: {e}")
            time.sleep(2 ** (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    load_env()
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")

    done = set()
    if os.path.exists(OUT_FILE):
        done = {json.loads(l)["id"] for l in open(OUT_FILE, encoding="utf-8") if l.strip()}

    todo = [p for p in read_posts() if post_id(p) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Уже размечено: {len(done)}, к разметке: {len(todo)}")

    with open(OUT_FILE, "a", encoding="utf-8") as out:
        for i, text in enumerate(todo, 1):
            try:
                fields = label(client, text)
            except Exception as e:
                print(f"[{i}/{len(todo)}] ошибка: {e}")
                continue
            out.write(json.dumps({"id": post_id(text), "text": text, "fields": fields},
                                 ensure_ascii=False) + "\n")
            out.flush()
            print(f"[{i}/{len(todo)}] {fields.get('position')}")


if __name__ == "__main__":
    main()
