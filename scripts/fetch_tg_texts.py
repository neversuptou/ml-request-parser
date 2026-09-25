#!/usr/bin/env python3
"""
Скачивание исходных текстов заявок из Telegram по ссылкам из выгрузки админки.

Читает CSV выгрузки (колонка "Ссылка в Telegram"), качает сообщения пачками
по 100 и пишет data/tg_texts.jsonl  {"link", "text"}. Можно прерывать —
повторный запуск докачивает только недостающее.

Аккаунт должен состоять во всех каналах (приватные ссылки t.me/c/...).

    set TG_API_ID=...            (my.telegram.org)
    set TG_API_HASH=...
    python scripts/fetch_tg_texts.py "D:/Download browser/zapros_....csv" --session path/to/userbot_session

Флаги:
    --per-chat 1500   не больше N сообщений с одного канала (bitrix_work — 15k однотипных)
    --only-template   только заявки, разобранные шаблоном (их поля — дословные куски текста)
"""
import argparse
import asyncio
import csv
import json
import os
import random
import re
from collections import defaultdict

from telethon import TelegramClient
from telethon.errors import FloodWaitError

OUT_FILE = "data/tg_texts.jsonl"
BATCH = 100
PAUSE = 1.5  # секунд между пачками — бережём аккаунт от лимитов
_LINK = re.compile(r"https?://t\.me/(c/(\d+)|([\w_]+))/(\d+)")


def read_links(csv_path: str, only_template: bool, per_chat: int) -> dict[str, list[tuple[int, str]]]:
    csv.field_size_limit(10**9)
    by_chat = defaultdict(list)
    for row in csv.DictReader(open(csv_path, encoding="utf-8")):
        if only_template and row.get("Обработано", "") not in ("", "template"):
            continue
        link = row["Ссылка в Telegram"].strip()
        m = _LINK.match(link)
        if not m:
            continue
        chat = f"-100{m.group(2)}" if m.group(2) else m.group(3)
        by_chat[chat].append((int(m.group(4)), link))
    rnd = random.Random(42)
    for chat, items in by_chat.items():
        items = sorted(set(items))
        if per_chat and len(items) > per_chat:
            items = sorted(rnd.sample(items, per_chat))
        by_chat[chat] = items
    return by_chat


async def resolve(client, chat: str, dialogs: dict):
    if chat.startswith("-100"):
        return dialogs.get(int(chat)) or dialogs.get(int(chat[4:]))
    try:
        return await client.get_entity(chat)
    except Exception as e:
        print(f"  не найден канал {chat}: {e}")
        return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--session", default="userbot_session")
    ap.add_argument("--per-chat", type=int, default=1500)
    ap.add_argument("--only-template", action="store_true")
    args = ap.parse_args()

    done = set()
    if os.path.exists(OUT_FILE):
        done = {json.loads(l)["link"] for l in open(OUT_FILE, encoding="utf-8") if l.strip()}

    by_chat = read_links(args.csv, args.only_template, args.per_chat)
    total = sum(len(v) for v in by_chat.values())
    print(f"Каналов: {len(by_chat)}, ссылок: {total}, уже скачано: {len(done)}")

    api_id, api_hash = int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]
    async with TelegramClient(args.session, api_id, api_hash) as client:
        dialogs = {}
        async for d in client.iter_dialogs():
            dialogs[d.id] = d.entity
            dialogs[getattr(d.entity, "id", d.id)] = d.entity

        with open(OUT_FILE, "a", encoding="utf-8") as out:
            for chat, items in by_chat.items():
                todo = [(mid, link) for mid, link in items if link not in done]
                if not todo:
                    continue
                entity = await resolve(client, chat, dialogs)
                if entity is None:
                    print(f"пропуск {chat}: аккаунт не состоит в канале ({len(todo)} ссылок)")
                    continue
                print(f"{chat}: {len(todo)}")
                for i in range(0, len(todo), BATCH):
                    batch = todo[i:i + BATCH]
                    while True:
                        try:
                            msgs = await client.get_messages(entity, ids=[mid for mid, _ in batch])
                            break
                        except FloodWaitError as e:
                            print(f"  FloodWait {e.seconds} с — ждём")
                            await asyncio.sleep(e.seconds + 5)
                    for (mid, link), msg in zip(batch, msgs):
                        text = (msg.message or "") if msg else ""  # message = текст или подпись к медиа
                        out.write(json.dumps({"link": link, "text": text}, ensure_ascii=False) + "\n")
                    out.flush()
                    await asyncio.sleep(PAUSE)
    print("Готово:", OUT_FILE)


if __name__ == "__main__":
    asyncio.run(main())
