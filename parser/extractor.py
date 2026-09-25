"""Сборка полей: regex (подписанные поля) + модель (остальное и списки) и рендер."""
import re

from parser.line_model import _POS_GRADE, _value
from parser.regex_rules import LIST_FIELDS, extract_embedded, extract_regex

FIELDS = [
    "request_number", "project", "position", "grade", "experience", "duration",
    "rate", "requirements", "nice_to_have", "tasks", "location", "contacts",
]

# regex угадывает эти поля эвристикой (позиция = первая строка, контакты = первая строка с "@"),
# модель — надёжнее; к тому же модель склеивает все строки поля ("РФ; Удалённо; UTC+3")
MODEL_FIRST = {"position", "contacts", "location"}
# сколько строк с низкой уверенностью модели ставят пометку «проверить вручную»
UNCERTAIN_LINES = 3

_NOT_LOADED = object()
_model_cache = _NOT_LOADED


def _default_model():
    """Построчная модель, если обучена; иначе NER; иначе None (только regex)."""
    global _model_cache
    if _model_cache is _NOT_LOADED:
        _model_cache = None
        try:
            from parser.line_model import load_line_model
            _model_cache = load_line_model()
            if _model_cache is None:
                from parser.ner_model import load_ner
                _model_cache = load_ner()
        except Exception:
            _model_cache = None
    return _model_cache


def extract(text: str, ner=_NOT_LOADED) -> dict:
    """ner: объект с predict(text)->dict[field, list[str]], None — только regex.

    Одиночные поля: regex приоритетнее (подпись "Ставка:" надёжнее модели).
    Списки: модель приоритетнее — она видит пункты и без заголовка секции.
    """
    fields = extract_regex(text)
    fields["extra"], fields["check"] = [], []
    if ner is _NOT_LOADED:
        ner = _default_model()
    uncertain = []
    if ner is not None:
        preds = ner.predict(text)
        fields["extra"] = list(preds.get("extra") or [])
        uncertain = preds.get("_uncertain") or []
        for f in FIELDS:
            values = preds.get(f) or []
            if not values:
                continue
            if f in LIST_FIELDS:
                if len(values) >= len(fields.get(f) or []):
                    fields[f] = list(values)
            elif f in MODEL_FIRST or not fields.get(f):
                fields[f] = values[0]
    _split_position(fields)
    # поля, спрятанные внутри других строк ("ID:14918_... Senior ...") — только в пустые
    for f, v in extract_embedded(text).items():
        if not fields.get(f):
            fields[f] = v
    fields["check"] = _check_reasons(fields, uncertain, text)
    return fields


# "System Analyst 1С senior в телеком (сотовая связь)" -> позиция + проект "телеком (сотовая связь)"
# не "в поиске ML инженера" и не "с уклоном в бизнес-анализ" — это не место работы
_POS_WHERE = re.compile(r"(?<!уклоном)(?<!опытом)(?<!фокусом)(?<!знанием)(?<!погружением)"
                        r"\s+в\s+(?!поиск)(?:команду\s+|компанию\s+|проект\s+)?(?!штат|офис|команде\b)(.{3,60})$", re.I)
# "Java разработчик/Senior на аутстаф", "Разработчик SQL на 1/40 в штат заказчика" -> без условий найма
_POS_TERMS = re.compile(r"\s+(?:на\s+(?:аутстаф\w*|аутсорс\w*|outstaff|1/\d+|проект\b)|в\s+штат).*$", re.I)


def _split_position(fields: dict) -> None:
    pos = fields.get("position") or ""
    if not pos:
        return
    pos = _value(pos, "position") or pos  # "Мы в поиске ML инженера" -> "ML инженер" (вступление, падеж)
    pos = _POS_TERMS.sub("", pos)
    m = _POS_WHERE.search(pos)
    if m:
        if not fields.get("project"):
            fields["project"] = m.group(1).strip(" .,")
        pos = pos[:m.start()]
    fields["position"] = _POS_GRADE.sub("", pos).strip(" /,-–—") or fields["position"]


# предложение специалистов/услуг, а не вакансия: "Актуальный бенч", "на нашем бенче появился", "ищу партнёров"
_NOT_VACANCY = re.compile(r"бенч\b|бенче\b|доступн\w+\s+для\s+брони|свободн\w+\s+специалист|"
                          r"если\s+(?:кому-то|вам)\s+нуж|ищу\s+партн[её]р|предлага\w+\s+(?:свои\s+)?услуг|#available|#резюме",
                          re.I)
# дайджест: несколько вакансий одним постом ("🔹(Заявка 4338622) Lead QA SAP, грейд: senior/lead" ×13)
_DIGEST_ITEM = re.compile(r"(?:заявк\w*|id|№|запрос)\s*[:#№]?\s*\d{3,}", re.I)


# короткая строка-должность: "🔥Devops инженер - проект Финансовый сектор (Senior)", "Аналитик 1С"
_ROLE_LINE = re.compile(r"^\W*[\w .+#/()-]{0,40}?(?:разработчик|аналитик|инженер|developer|engineer|analyst|"
                        r"дизайнер|designer|тестировщик|qa\b|devops|архитектор|писатель|консультант|"
                        r"администратор|менеджер|manager|lead\b|тимлид)[\w .+#/(),-]{0,70}$", re.I)
_DIGEST_HINT = re.compile(r"актуальн\w+\s+(?:вакансии|вакансиями|запрос\w*)|срочные\s+запросы|дайджест|"
                          r"подборк\w+\s+вакансий|наши\s+вакансии|^[—–-]{4,}", re.I | re.M)


# пункт списка требований/задач, а не должность: "- Опыт работы разработчиком…", "• Знание…"
_NOT_ROLE_LINE = re.compile(r"^\s*(?:[-•*–·]|\d+[.)])\s|опыт|знани|умени|навык|работ[аы]\s+с|взаимодейств|"
                            r"команд|ищем|требуется|нужен|мы\s", re.I)


def _is_role_list(text: str) -> bool:
    """Несколько строк-должностей подряд по посту: 3+, или 2+ при явном «актуальные вакансии»/разделителе."""
    roles = [ln for ln in text.splitlines() if 3 < len(ln.strip()) < 110 and _ROLE_LINE.match(ln.strip())
             and ":" not in ln  # "Роль специалиста: X", "Грейд: Senior" — подписи, не пункты дайджеста
             and not _NOT_ROLE_LINE.search(ln)]
    return len(roles) >= 4 or (len(roles) >= 2 and bool(_DIGEST_HINT.search(text)))


def classify_post(text: str) -> str | None:
    """Особые посты, которые построчная модель разбирает плохо: 'не вакансия', 'дайджест', 'одна фраза'."""
    head = (text or "")[:600]
    if _NOT_VACANCY.search(head):
        return "похоже, не вакансия (бенч / предложение специалистов или услуг)"
    if len(_DIGEST_ITEM.findall(text or "")) >= 3 or _is_role_list(text or ""):
        return "дайджест: несколько вакансий в одном посте"
    meaningful = [ln for ln in (text or "").splitlines() if len(re.sub(r"\W", "", ln)) > 3]
    if len(meaningful) <= 3:
        return "короткий пост без структуры (одна-две фразы)"
    return None


def _check_reasons(fields: dict, uncertain: list[str], text: str = "") -> list[str]:
    """Почему заявку стоит открыть в оригинале. Пусто — разбор выглядит надёжным."""
    reasons = []
    kind = classify_post(text)
    if kind:
        reasons.append(kind)
    if not fields.get("position"):
        reasons.append("не найдена позиция")
    if not fields.get("requirements") and not fields.get("tasks") and not kind:
        reasons.append("не найдены ни требования, ни задачи")
    if len(uncertain) >= UNCERTAIN_LINES:
        reasons.append(f"модель не уверена в {len(uncertain)} строках")
    return reasons


def _v(x) -> str:
    return x if x else "—"


def _lines(items: list[str]) -> str:
    return "\n".join(items) if items else "—"


def render(f: dict) -> str:
    out = [
        "Найден запрос",
        "",
        f"Номер заявки: {_v(f.get('request_number'))}",
        f"Наименование проекта: {_v(f.get('project'))}",
        f"Позиция: {_v(f.get('position'))}",
        f"Уровень: {_v(f.get('grade'))}",
        f"Опыт работы: {_v(f.get('experience'))}",
        f"Длительность проекта: {_v(f.get('duration'))}",
        f"Рейт: {_v(f.get('rate'))}",
        f"Требования: {_lines(f.get('requirements') or [])}",
    ]
    if f.get("nice_to_have"):
        out.append("Будет преимуществом:")
        out.extend(f["nice_to_have"])
    out += [
        f"Выполняемы задачи на проекте: {_lines(f.get('tasks') or [])}",
        f"Локация проживания: {_v(f.get('location'))}",
        f"Контакты: {_v(f.get('contacts'))}",
    ]
    if f.get("extra"):
        out.append("Дополнительная информация:")
        out.extend(f["extra"])
    if f.get("check"):
        out.append(f"⚠️ Проверить вручную: {'; '.join(f['check'])}")
    return "\n".join(out)
