"""Поправки к меткам строк после модели — структура поста, которую модель по одной строке не видит.

- подзаголовки внутри списка ("Диагностика и устранение ошибок:" под "Задачи:") — продолжение списка;
- секция-инструкция к резюме ("В резюме должны быть:", "При подаче укажите:") — не требования;
- подписанное поле ("Роль специалиста: X", "Часовой пояс: MSK") важнее догадки модели;
- строка из одних хэштегов — не позиция.
"""
import re

LIST_FIELDS = ("requirements", "tasks", "nice_to_have")

# заголовок -> поле секции (как в scripts/prepare_lines.py)
_SECTION = [
    (re.compile(r"плюс|преимуществ|желательно|ценятся|дополнительн|приветствуется|nice to have|bonus", re.I),
     "nice_to_have"),
    (re.compile(r"задачи|обязанности|предстоит|заниматься|нужно\s+делать|функционал\b|responsibilities|tasks", re.I),
     "tasks"),
    (re.compile(r"требовани|навыки|стек|ожидаем|что\s+мы\s+(?:ищем|ждем|ждём)|кого\s+ищем|важно\s+для|для\s+нас\s+важно|"
                r"must|requirements|skills", re.I), "requirements"),
]
# заголовок про подачу кандидата / условия — список под ним не про вакансию
_FOREIGN = re.compile(r"резюме|\bcv\b|при\s+подаче|укажите|указыва|следующ\w+\s+информац|приложите|чек-?лист|"
                      r"присыла|направля|отклик|мы\s+предлагаем|условия|"
                      r"этапы|процесс\s+отбора|бонусы|плюшки|offer|benefits", re.I)
# описание проекта/компании — пункты под ним не задачи и не требования
_DESC = re.compile(r"описание|о\s+проекте|о\s+компании|о\s+нас\b|about", re.I)
_BULLET_LINE = re.compile(r"^\s*(?:[-•*●–·▪]|\d{1,2}[.)])\s*")
# подпись поля в начале строки
_LABELED = [(re.compile(r"^[^\w№]*(?:\d{1,2}[.)]\s*)?(?:" + p + r")\b[^:\n]{0,40}?:\s*\S", re.I), f) for p, f in [
    (r"роль|позиция|должность|вакансия", "position"),
    (r"грейд|уровень|level|seniority", "grade"),
    (r"локация|география|гражданство|формат\s+работы|часовой\s+пояс|допустимый\s+часовой|time\s*zone|"
     r"время\s+работы|местоположение", "location"),
    (r"ставка|рейт|rate|бюджет|оплата|формат\s+оплаты|зарплата|заработная\s+плата", "rate"),
    (r"длительность|продолжительность|срок\s+(?:проекта|привлечения)", "duration"),
    (r"проект|заказчик|компания|сфера\s+деятельности", "project"),
    (r"номер\s+заявки|id\s+(?:запроса|вакансии)", "request_number"),
    # заголовок и значение в одной строке: "🔘Задачи: тестирование…", "🔘Требования: Kafka, API"
    (r"задачи|обязанности", "tasks"),
    (r"требования", "requirements"),
]]
_HASHTAGS_ONLY = re.compile(r"^\W*(?:#\w+\W*)+$")
# инструкция по подаче внутри списка: "❗Резюме отправлять через кнопку «отправить CV»"
_SUBMIT = re.compile(r"(?:резюме|\bcv\b).{0,40}(?:отправ|направ|присыл|прикреп|подава)|"
                     r"(?:отправ|направ|присыл|прикреп|подава)\w*.{0,40}(?:резюме|\bcv\b)", re.I)
_SECTION_HEADER = re.compile(
    r"^\W*(?:требовани\w*|задачи|обязанности|будет\s+плюсом|плюсом\s+будет|будет\s+преимуществом|желательно|"
    r"что\s+(?:нужно|предстоит)\s+делать|что\s+мы\s+(?:ищем|ждем|ждём|ожидаем)|что\s+для\s+нас\s+важно|кого\s+ищем|"
    r"чем\s+предстоит\s+заниматься|responsibilities|requirements|nice\s+to\s+have)\b[^:\n]{0,90}:\s*$", re.I)
# заголовок без двоеточия, строка целиком из известной фразы: "Что предстоит делать", "Кого ищем",
# "Обязательные требования", "Условия", "О компании", "Стек технологий"
_BARE_HEADER = re.compile(
    r"^\W{0,4}(?:(?:обязательные\s+|основные\s+|ключевые\s+)?требования(?:\s+к\s+\w+)?|задачи|обязанности|"
    r"(?:основные\s+)?задачи(?:\s+и\s+обязанности)?|что\s+(?:нужно|предстоит)\s+делать|чем\s+предстоит\s+заниматься|"
    r"кого\s+(?:мы\s+)?ищем|что\s+мы\s+(?:ищем|ждем|ждём|ожидаем)|будет\s+плюсом|будет\s+преимуществом|желательно|"
    r"условия|мы\s+предлагаем|что\s+мы\s+предлагаем|о\s+компании|о\s+проекте|описание\s+проекта|"
    r"стек(?:\s+технологий)?|ключевые\s+компетенции|responsibilities|requirements|nice\s+to\s+have)\W{0,4}$", re.I)
# строка, на которой список точно кончился
_END = re.compile(r"резюме|\bcv\b|направля|присыла|регистрир|отклик|@\w|https?://|t\.me/|#\w", re.I)


# заголовки одиночных полей и блоков про компанию — список перед ними точно закончился
_CLOSE = re.compile(r"проект|компани|заказчик|контакт|связь|локаци|location|формат|оплат|ставк|рейт|"
                    r"срок|длительн|график|о\s+нас|about|contact|salary|rate", re.I)


def section_of(header: str) -> str | None:
    """Поле списка под заголовком; "foreign" — инструкция к подаче; "close" — заголовок другого
    поля (список кончился); None — незнакомый заголовок (внутри списка — его подраздел)."""
    if _FOREIGN.search(header):
        return "foreign"
    if _DESC.search(header) and not re.search(r"задач|обязанност|требовани", header, re.I):
        return "desc"
    for rx, f in _SECTION:
        if rx.search(header):
            return f
    if _CLOSE.search(header):
        return "close"
    return None


# подпись без двоеточия на своей строке, значение — на следующей (.redev и др.):
#   "Гражданство" / "РФ", "Ограничение по ставке T&M (без НДС)" / "Lead/2 400 руб."
_BARE_LABEL = [(re.compile(r"^\W*(?:" + p + r")(?:\s*\([^)]*\))?\W*$", re.I), f) for p, f in [
    (r"сфера\s+деятельности(?:\s+заказчика)?|заказчик|компания|проект|описание\s+проекта", "project"),
    (r"(?:ограничение\s+по\s+)?ставк\w*(?:\s+t&m)?|рейт|бюджет", "rate"),
    (r"продолжительность(?:\s+проекта)?|длительность(?:\s+проекта)?|срок(?:\s+проекта|\s+привлечения)?", "duration"),
    (r"гражданство|локация|формат\s+работы|география", "location"),
    (r"грейд|уровень", "grade"),
    (r"контакты?", "contacts"),
    (r"период\s+актирования|форма\s+налогообложения(?:\s+подрядчика)?|занятость|загрузка", "other"),
]]


def fix_labels(lines: list[str], labels: list[str]) -> list[str]:
    out = list(labels)
    # подпись на отдельной строке -> она заголовок, следующая строка — значение этого поля
    for i, raw in enumerate(lines[:-1]):
        if _BULLET_LINE.match(raw):
            continue  # "- Ставка" в чек-листе для резюме — пункт списка, а не подпись поля
        for rx, f in _BARE_LABEL:
            if rx.match(raw) and len(raw) < 60:
                out[i] = "header"
                nxt = lines[i + 1]
                if not any(r2.match(nxt) for r2, _ in _BARE_LABEL) and not nxt.rstrip().endswith(":"):
                    out[i + 1] = f
                break
    # заголовок секции с необычным хвостом: "✔️Требования +\- (только для специалистов…):", "Что мы ищем:"
    for i, raw in enumerate(lines):
        if out[i] != "header" and (_SECTION_HEADER.match(raw) or _BARE_HEADER.match(raw) or (
                raw.rstrip().endswith(":") and len(raw) < 90 and _FOREIGN.search(raw))):
            out[i] = "header"  # в т.ч. "Обязательно указывайте следующую информацию:" — дальше чек-лист
    section = None  # поле текущего списка, "foreign" — инструкция к подаче, None — вне списка
    for i, (raw, lab) in enumerate(zip(lines, out)):
        # 1. подписанное одиночное поле надёжнее модели
        for rx, f in _LABELED:
            if rx.match(raw) and lab in ("other", "header", "position", "requirements", "tasks", *LIST_FIELDS):
                if f != lab and not (f == "project" and lab in LIST_FIELDS):
                    out[i] = lab = f
                break
        if lab == "position" and _HASHTAGS_ONLY.match(raw):
            out[i] = lab = "other"
        if lab in LIST_FIELDS and _SUBMIT.search(raw) and not re.search(r"@\w", raw):
            out[i] = lab = "junk"  # как подавать резюме — не требование (с @ — это уже контакт)

        if lab == "header":
            sec = section_of(raw)
            if sec is None and section in LIST_FIELDS:
                out[i] = section  # подзаголовок внутри списка задач — сам тоже пункт
            else:
                section = None if sec == "close" else sec
            continue

        if section == "foreign" and (lab in (*LIST_FIELDS, "other") or (_BULLET_LINE.match(raw) and lab != "contacts")):
            out[i] = "junk"  # "В резюме должны быть: ФИО, грейд", "- Ставка" из чек-листа — не поля вакансии
        elif section == "desc" and lab in LIST_FIELDS:
            out[i] = "other"  # пункты описания проекта ("1. Развитие платформы ВТБ Онлайн…") — не задачи
        elif section in ("requirements", "tasks") and lab in LIST_FIELDS and lab != section and lab != "nice_to_have":
            out[i] = section  # заголовок секции важнее метки модели ("Требования:" — значит требования)
        elif (section in LIST_FIELDS and lab == "other" and i and out[i - 1] in (section, "header")
              and not _END.search(raw)):
            out[i] = section  # пункт под подзаголовком списка (подряд за списком, не ссылка/инструкция)
        elif lab not in ("other", *LIST_FIELDS):
            section = None  # подписанное поле закрывает список
    return out
