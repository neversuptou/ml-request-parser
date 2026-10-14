# Развёртывание и внедрение вместо DeepSeek

## 1. Сервис разбора (ml-request-parser)

Веса моделей в git и в образ не входят — их копируют на сервер отдельно:

```bash
# с машины, где обучалась модель
scp -r model/lines-rubert model/lines-baseline.joblib user@server:/opt/model-for-parsing-requests/model/
```

На сервере:

```bash
cd /opt && git clone https://git.evapps.ru/userbot-application/model-for-parsing-requests.git
cd model-for-parsing-requests            # model/ уже лежит рядом (шаг выше)
docker compose up -d --build
curl -s localhost:8010/health   # {"status":"ok","model":"BertLineModel",...}
```

- Порт снаружи — `PARSER_PORT` (по умолчанию 8010; 8000 занят ml-hr-rec-service).
- Память: ~1 ГБ в работе (2 воркера), лимит 2 ГБ. Разбор поста — ~0.1–0.5 с на CPU.
- Быстрая запасная модель: `LINE_MODEL_PATH=/app/model/lines-baseline.joblib` (~50 МБ памяти, точность ниже).
- `status=degraded` в /health — весов не нашлось, сервис работает на одних правилах. Проверить том `./model`.

## 2. Юзербот (tg_application)

В `.environment` юзербота:

```
PARSER_MODEL_URL=http://<хост>:8010
PARSER_MODEL_MODE=shadow
```

Если юзербот в docker, а сервис на том же хосте — `http://host.docker.internal:8010`
(в Linux добавить `extra_hosts: ["host.docker.internal:host-gateway"]`) или общая docker-сеть
и `http://ml-request-parser:8010`.

Режимы `PARSER_MODEL_MODE`:

| режим   | что происходит |
|---------|----------------|
| off     | как раньше, только DeepSeek |
| shadow  | заявки разбирает DeepSeek, модель пишет в лог расхождения (`SHADOW: ...`) |
| primary | модель первой; DeepSeek только для дайджестов/коротких/без позиции |
| model   | только модель, DeepSeek не вызывается. Сервис недоступен → шаблон канала |

Заявки от модели в БД — `parsed_by='model'`.

## 3. Порядок включения

1. `shadow` на 1–2 дня: `grep SHADOW` в логах юзербота, смотреть, в каких полях расхождения.
2. `primary` — DeepSeek остаётся страховкой для сложных постов, расход падает в разы.
3. `model` — полный отказ от DeepSeek. Ключ DeepSeek можно не удалять: генерация
   вопросов о рейте (rate_inquiry) использует свой ключ и от режима не зависит.

## 4. Откат

`PARSER_MODEL_MODE=off` и пересоздать контейнер юзербота. Сервис модели можно не останавливать.

## 5. Обновление модели

Дообучить (см. GUIDE.md), скопировать новую `model/lines-rubert` на сервер,
`docker compose restart request-parser`. Образ пересобирать не нужно.
