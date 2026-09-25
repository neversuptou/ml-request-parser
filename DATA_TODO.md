# Что нужно сделать: получить исходные тексты заявок

Цель — тексты постов для заявок, разобранных **шаблоном** (их поля — дословные куски
текста, лучшая разметка для обучения). В CSV-выгрузке админки текстов нет.

Сначала шаг 1. Если текстов мало — шаг 2.

---

## Шаг 1. Выгрузка из БД (колонка `source_text`)

### 1.1 Проверить, сколько текстов уже есть

```sql
SELECT coalesce(parsed_by, '(шаблон)') AS parsed_by,
       count(*)                                  AS всего,
       count(*) FILTER (WHERE source_text <> '') AS с_текстом
FROM template_application
GROUP BY 1;
```

### 1.2 Выгрузить (если с_текстом — сотни и больше)

Имена колонок совпадают с CSV админки, импорт их понимает как есть.

```sql
\copy (
  SELECT a.application_number   AS "Номер заявки",
         a.project_title        AS "Наименование проекта",
         a.position             AS "Позиция",
         a.level                AS "Уровень",
         a.experience           AS "Опыт работы",
         a.project_duration     AS "Длительность проекта",
         a.rate                 AS "Рейт",
         a.requirements         AS "Требования",
         a.tasks                AS "Выполняемы задачи на проекте",
         a.location             AS "Локация проживания",
         a.contact_details      AS "Контакты",
         coalesce(a.parsed_by, '') AS "Обработано",
         t.title                AS "template__title",
         a.tg_link_on_message   AS "Ссылка в Telegram",
         a.source_text          AS "source_text"
  FROM template_application a
  JOIN template_template t ON t.id = a.template_id
  WHERE a.source_text <> ''
) TO 'applications_with_text.csv' WITH (FORMAT csv, HEADER, ENCODING 'UTF8');
```

Файл `applications_with_text.csv` положить в `model ai decrypt/`, написать мне.

---

## Шаг 2. Скачать тексты из Telegram по ссылкам

Нужно, если в БД текстов мало (старые заявки до миграции `0034`).

⚠ Лучше **не с аккаунта, на котором работает парсинг** (`@evapps_requests` и др.):
массовое чтение истории может дать FloodWait / ограничения, а на этом аккаунте весь парсинг.
Подойдёт любой аккаунт, который состоит в тех же каналах. Скрипт сам ждёт при FloodWait
и делает паузу 1.5 с между пачками по 100 сообщений.

Объём: только шаблонные, не больше 1500 с канала → ~20–25 тыс. сообщений, ~250 запросов, ~10–20 мин.

```bash
cd "D:\Работа\Рабочие проекты\model ai decrypt"
pip install telethon

set TG_API_ID=<api_id с my.telegram.org>
set TG_API_HASH=<api_hash>

python scripts/fetch_tg_texts.py "D:/Download browser/zapros_za_20.06.2016-24.09.2026.csv" --only-template --per-chat 1500 --session "D:/Работа/Рабочие проекты/AI Auto/tg-userbot-export/userbot_session"
```

- Первый запуск с новой сессией спросит телефон и код из Telegram — это нормально.
- Прервать можно в любой момент (Ctrl+C); повторный запуск докачает остальное.
- Каналы, где аккаунт не состоит, будут пропущены — в логе строка `пропуск ...`.
- Результат: `data/tg_texts.jsonl`. Написать мне.

---

## Дальше (делаю я)

```bash
python scripts/import_template_csv.py <csv>     # тексты + шаблонные поля -> построчная разметка
```

Потом: проверка/правка черновой разметки (я), обучение построчной модели, сравнение с NER.
