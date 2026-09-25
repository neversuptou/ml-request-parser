#!/usr/bin/env python3
"""
Ручная оценка «модель vs DeepSeek» против исходного текста поста.

По каждой заявке и каждому полю ставится вердикт: кто заполнил верно.
  b — оба верно, m — только модель, d — только DeepSeek, n — оба неверно.

    python scripts/judge.py show 0 5          # исходный текст + поля модели и DeepSeek
    python scripts/judge.py set 3 "bbmbbbdbbnb"   # 11 символов — по полям в порядке FIELDS
    python scripts/judge.py score             # общий скор и по полям

Файлы: модель — zapros_za_23.09.2026-24.09.2026_model.xlsx, DeepSeek — исходная выгрузка админки,
исходные тексты — parsed_zapros_23-24.09.2026.xlsx (колонка «Исходный текст»).
Вердикты: data/judge_23-24.json
"""
import json
import os
import sys

import openpyxl

MODEL_XLSX = "zapros_za_23.09.2026-24.09.2026_model.xlsx"
DS_XLSX = "D:/Download browser/zapros_za_23.09.2026-24.09.2026 (1).xlsx"
TEXT_XLSX = "parsed_zapros_23-24.09.2026.xlsx"
OUT = os.environ.get("JUDGE_OUT", "data/judge_23-24.json")
FIELDS = ["Номер заявки", "Наименование проекта", "Позиция", "Уровень", "Опыт работы", "Длительность проекта",
          "Рейт", "Требования", "Выполняемы задачи на проекте", "Локация проживания", "Контакты"]
RATE_STATUS = {"не удалось выяснить", "ожидаем ответа"}  # ставит сервис уточнения рейта, а не разбор


def rows(path):
    data = list(openpyxl.load_workbook(path, read_only=True).active.iter_rows(values_only=True))
    return [str(h) for h in data[0]], data[1:]


def load():
    if os.environ.get("JUDGE_ITEMS"):  # готовый набор [{link, text, model{}, ds{}}] — напр. data/fresh_items.json
        return json.load(open(os.environ["JUDGE_ITEMS"], encoding="utf-8"))
    mh, model = rows(MODEL_XLSX)
    dh, ds = rows(DS_XLSX)
    th, texts = rows(TEXT_XLSX)
    link = mh.index("Ссылка в Telegram")
    ds_by = {r[dh.index("Ссылка в Telegram")]: r for r in ds}
    text_by = {r[0]: r[th.index("Исходный текст")] for r in texts}
    items = []
    for r in model:
        d = ds_by[r[link]]
        items.append({
            "link": r[link],
            "text": text_by.get(r[link]) or "",
            "model": {f: str(r[mh.index(f)] or "") for f in FIELDS},
            "ds": {f: str(d[dh.index(f)] or "") for f in FIELDS},
        })
    return items


def cmd_show(a, b):
    for n, it in list(enumerate(load()))[int(a):int(b)]:
        print(f"\n################ {n}  {it['link']}")
        print(it["text"])
        print("---------------- поле | МОДЕЛЬ | DEEPSEEK")
        for i, f in enumerate(FIELDS):
            m, d = it["model"][f].replace("\n", " ⏎ "), it["ds"][f].replace("\n", " ⏎ ")
            print(f"[{i}] {f}\n    М: {m[:300]}\n    D: {d[:300]}")


def cmd_set(n, verdicts):
    assert len(verdicts) == len(FIELDS) and set(verdicts) <= set("bmdn"), verdicts
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    data[load()[int(n)]["link"]] = verdicts
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"оценено заявок: {len(data)}")


def cmd_score():
    data = json.load(open(OUT, encoding="utf-8"))
    n = len(data)
    m_ok = {f: 0 for f in FIELDS}
    d_ok = {f: 0 for f in FIELDS}
    m_perfect = d_perfect = 0
    for v in data.values():
        for f, c in zip(FIELDS, v):
            m_ok[f] += c in "bm"
            d_ok[f] += c in "bd"
        m_perfect += all(c in "bm" for c in v)
        d_perfect += all(c in "bd" for c in v)
    tot = n * len(FIELDS)
    mt, dt = sum(m_ok.values()), sum(d_ok.values())
    print(f"Заявок оценено: {n}\n")
    print(f"{'поле':30s} {'модель':>8s} {'DeepSeek':>9s}")
    for f in FIELDS:
        print(f"{f:30s} {m_ok[f]:4d}/{n:<3d} {d_ok[f]:5d}/{n}")
    print(f"\n{'ОБЩИЙ СКОР (полей верно)':30s} {mt / tot:8.1%} {dt / tot:9.1%}   ({mt} vs {dt} из {tot})")
    print(f"{'заявок без единой ошибки':30s} {m_perfect:4d}/{n:<3d} {d_perfect:5d}/{n}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"show": cmd_show, "set": cmd_set, "score": cmd_score}[cmd](*args)
