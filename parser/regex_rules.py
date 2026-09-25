"""Regex-извлечение полей из поста с вакансией.

Работает для подписанных полей ("Проект: ...", "Грейд: ...") и списков
под заголовками секций. То, что regex не нашёл, добирает NER-модель.
"""
import re

LIST_FIELDS = ("requirements", "nice_to_have", "tasks")

# Метка в начале строки -> поле. Перед меткой могут быть эмодзи/символы.
_LABELS = {
    "request_number": r"номер\s+заявки|заявка\s*№|№\s*заявки",
    "project": r"проект|наименование\s+проекта|заказчик",
    "position": r"позиция|должность|вакансия|роль(?:\s+специалиста)?",
    "grade": r"грейд|уровень|level",
    "location": r"локация(?:\s+проживания)?|локация\s+кандидата|география",
    "duration": r"длительность(?:\s+проекта)?|срок\s+проекта",
    "rate": r"ставка|рейт|rate",
}

_SECTIONS = {
    "requirements": r"требования|обязательные\s+требования|что\s+нужно",
    "nice_to_have": r"будет\s+преимуществом|плюсом\s+будет|будет\s+плюсом|желательно",
    "tasks": r"задачи(?:\s+на\s+проекте)?|обязанности|чем\s+предстоит\s+заниматься",
}

_PREFIX = r"^[^\w№]*"  # эмодзи, ❗️, *, - и т.п. перед меткой
_BULLET = re.compile(r"^\s*(?:[*\-•–—·▪►✅✔️🔹🔸]+|\d+[.)])\s*")
_EXPERIENCE = re.compile(
    r"(?:от|не\s+менее|более|свыше)\s*\d+(?:[.,]\d+)?\s*(?:-?х|\+)?\s*(?:лет|года|год)",
    re.I,
)
_CONTACT_HINT = re.compile(r"резюме\s+можно|отправ|контакт|@\w|t\.me/|пишите", re.I)
_CONTACT_SKIP = re.compile(r"принимаем\s+до", re.I)
_TRAILING_EMOJI = re.compile(r"[^\w).,!?»\"'+%]+$")  # "+" и "%" значимы: "Middle+", "100%"


def _clean(s: str) -> str:
    return _TRAILING_EMOJI.sub("", s.strip()).strip()


def _label_value(lines: list[str], pattern: str) -> str | None:
    rx = re.compile(_PREFIX + rf"(?:{pattern})\s*[:\-–—]\s*(.+)$", re.I)
    for line in lines:
        m = rx.match(line)
        if m and m.group(1).strip():
            return _clean(m.group(1))
    return None


def _header_rx(pattern: str) -> re.Pattern:
    return re.compile(_PREFIX + rf"(?:{pattern})\s*:?\s*$", re.I)


_ALL_HEADERS = [_header_rx(p) for p in _SECTIONS.values()]


def _section_items(lines: list[str], pattern: str) -> list[str]:
    header = _header_rx(pattern)
    for i, line in enumerate(lines):
        if not header.match(line):
            continue
        items: list[str] = []
        for nxt in lines[i + 1:]:
            if any(h.match(nxt) for h in _ALL_HEADERS):
                break
            if not nxt.strip():
                if items:
                    break
                continue
            if _BULLET.match(nxt):
                item = _BULLET.sub("", nxt, count=1).strip()
                if item:
                    items.append(item)
            elif items:
                break  # обычный абзац после списка — конец секции
            else:
                items.append(nxt.strip())  # список без маркеров
        return items
    return []


def _position(lines: list[str]) -> str | None:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[^\w]+", "", s)
        s = _clean(s)
        return s or None
    return None


def _contacts(lines: list[str]) -> str | None:
    labeled = _label_value(lines, r"контакты|связь|отклик")
    if labeled:
        return labeled
    for line in lines:
        if _CONTACT_SKIP.search(line) or not _CONTACT_HINT.search(line):
            continue
        if any(re.match(_PREFIX + rf"(?:{p})\s*[:\-–—]", line, re.I) for p in _LABELS.values()):
            continue
        return _clean(line)
    return None


def extract_regex(text: str) -> dict:
    lines = (text or "").splitlines()
    result: dict = {f: _label_value(lines, p) for f, p in _LABELS.items()}
    for field, pattern in _SECTIONS.items():
        result[field] = _section_items(lines, pattern)

    if not result["position"]:
        result["position"] = _position(lines)

    result["experience"] = _experience(lines)
    result["contacts"] = _contacts(lines)
    return result


# стаж: "от 3-х лет", "5+ лет опыта", "3-5+ лет в аналитической роли", "не менее 3-х лет", "от 2–3 лет"
_EXP_NUM = r"\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+)?\s*(?:-?х)?\s*\+?"
_EXP_ANY = re.compile(rf"(?:(?:от|не\s+менее|более|свыше|минимум)\s*)?{_EXP_NUM}\s*(?:лет|года?|years?)\b", re.I)
_EXP_CONTEXT = re.compile(r"опыт|стаж|experience|\bрол[иь]\b", re.I)
_NICE_HEADER = re.compile(r"плюс|преимуществ|желательно|nice", re.I)


def _experience(lines: list[str]) -> str | None:
    """Первое упоминание стажа в строке про опыт; блок «Будет плюсом» пропускаем —
    опыт оттуда пожелание, а не требование."""
    in_nice = False
    for line in lines:
        if re.match(r"^\W*[\w\s/(),.+\\-]{2,80}:\s*$", line):  # заголовок секции
            in_nice = bool(_NICE_HEADER.search(line))
            continue
        if in_nice or _NICE_HEADER.search(line[:25]):
            continue
        m = _EXPERIENCE.search(line)
        if not m and _EXP_CONTEXT.search(line):
            m = _EXP_ANY.search(line)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


# Поля внутри чужих строк: "ID:14918_Ведущий аналитик 1С Senior в телеком",
# "Гражданство и локация РФ, срок проекта до конца года". Построчная модель даёт строке
# одно поле, остальное теряется — добираем regex по всему тексту.
# "Пауза_ID:10807" (перед ID подчёркивание), "Запрос ASAP 350926" (между словом и номером — пометка)
_EMB_REQUEST = re.compile(r"(?<![^\W_]|/)(?:id|№|запрос\w*|заявк\w*|вакансии)\s*[:#№]?\s*"
                          r"(?:(?:asap|срочн\w*|горящ\w*)\s+)?(\d{2,8})(?!\d)", re.I)
_EMB_GRADE = re.compile(r"(?<!\w)(junior|middle|senior|lead|team\s*lead|тимлид|джуниор|мидл|сеньор|синьор)"
                        r"(\s*\+|\+)?(?!\w)", re.I)
_EMB_DURATION = re.compile(
    r"(?:срок\w*(?:\s+(?:проекта|привлечения|работы))?|длительност\w*(?:\s+проекта)?|период)\s*[-:–—]?\s*"
    r"((?:до|от|на|больше|более|около)\s[^,;\n.]{2,40}|длительн\w*|долгосрочн\w*|\d+\s*(?:мес|год|лет)[^,;\n]{0,20})",
    re.I)


def extract_embedded(text: str) -> dict:
    """Номер заявки, грейд и срок, где бы в тексте они ни стояли (для заполнения пустых полей)."""
    out = {}
    text = text or ""
    m = _EMB_REQUEST.search(text)
    if m:
        out["request_number"] = m.group(1)
    grades = []
    for g in _EMB_GRADE.finditer(text[:1500]):  # грейд ищем в шапке, не в тексте требований
        val = re.sub(r"\s+", " ", g.group(0)).strip()
        val = val[0].upper() + val[1:]
        if val.lower() not in {x.lower() for x in grades}:
            grades.append(val)
    if not grades:  # "Старший инженер…", "🎇Ведущий аналитик 1с" — грейд словом в заголовке вакансии
        head = "\n".join(l for l in text.splitlines() if l.strip())
        m = re.search(r"(?<!\w)(старш|ведущ|главн|младш)\w*", "\n".join(head.splitlines()[:3]), re.I)
        if m:
            grades.append(m.group(0)[0].upper() + m.group(0)[1:].lower())
    if grades:
        out["grade"] = "/".join(grades[:3])
    m = _EMB_DURATION.search(text)
    if m:
        out["duration"] = m.group(1).strip()
    m = _EMB_APPLY_URL.search(text)
    if m:
        out["contacts"] = m.group(1).rstrip(".,)")  # отклик через сайт/форму: "Регистрируйтесь на https://…"
    elif (m := _EMB_APPLY_DM.search(text)):
        out["contacts"] = "личные сообщения"  # "присылайте CV в личные сообщения" — контакт без @
    return out


_EMB_APPLY_DM = re.compile(r"(?:присылайте|пишите|направляйте|отправляйте|пишите\s+мне)[^\n]{0,60}?"
                           r"(?:личн\w*\s+сообщени\w*|\bлс\b|личку|директ)", re.I)


_EMB_APPLY_URL = re.compile(r"(?:регистрир|отклик|заполн\w*\s+(?:гугл\s*)?форм|анкет|подать\s+кандидат)"
                            r"[^\n]{0,80}?(https?://\S+)", re.I)
