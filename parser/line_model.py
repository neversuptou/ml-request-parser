"""Построчная модель: каждая строка поста -> поле, затем сборка значений полей.

predict() кроме полей возвращает служебные ключи:
  "extra"      — строки «не поле», в которых есть смысл (условия, загрузка, старт…), для блока
                 «Дополнительная информация», чтобы текст не терялся молча;
  "_uncertain" — строки, где модель не уверена (вероятность ниже LOW_CONFIDENCE).
"""
import os
import re

from parser.line_post import fix_labels
from parser.lines import split_lines

DEFAULT_PATH = "model/lines-baseline.joblib"
BERT_PATH = "model/lines-rubert"
LIST_FIELDS = {"requirements", "nice_to_have", "tasks"}
# несколько строк одного одиночного поля склеиваем: "Локация: РФ" + "Формат: удалённо"
JOIN_FIELDS = {"location", "rate", "contacts", "duration", "project"}
LOW_CONFIDENCE = 0.6

_BULLET = re.compile(r"^\s*(?:[*\-•–—·▪►●✅✔️🔹🔸]+|\d{1,2}[.)])\s*")
_LABEL = re.compile(r"^[^\w№]*(?:\d{1,2}[.)]\s*)?[\w\s/()-]{2,45}?\s*[:–—]\s*")
_POS_PREFIX = re.compile(r"^(?:[^\w]*(?:пауза|срочно)\W*)?(?:id|№|запрос)?\s*[:#№]?\s*\d{2,8}\s*[_.:)\-–—]?\s*", re.I)
_EDGE = re.compile(r"^[^\w@#№(«\"+]+|[^\w).,!?»\"'%+]+$")
_POS_INTRO = re.compile(r"^(?:мы\s+)?(?:в\s+поиск(?:е|ах)|ищем|требуется|требуются|нужен|нужна|открыта\s+вакансия|"
                        r"(?:новая\s+)?вакансия\s*[-–—:]|срочно\s+ищем|"
                        r"we\s+are\s+looking\s+for(?:\s+an?)?|looking\s+for(?:\s+an?)?|hiring)\s*[:\-–—]?\s*"
                        r"(?:\d+\s+)?", re.I)
# строки other, которые в «Дополнительную информацию» не берём: навигация, реклама канала,
# инструкции по оформлению резюме, хэштеги
_JUNK = re.compile(r"резюме|\bcv\b|регистрир|подписыв|закрепл|актуальн\w*\s+запрос|навигация|подробнее|"
                   r"#\w|https?://|t\.me/|фио|дата\s+рождения|чек-?лист|\+/-|\+-|статус:", re.I)


_GRADE_WORDS = (r"(?:junior|middle|senior|lead|team\s*lead|тимлид|мидл|сеньор|синьор|джуниор)\+?"
                r"(?:\s*/\s*(?:junior|middle|senior|lead|team\s*lead)\+?)*")
# грейд только в начале или в конце названия: "Senior/Lead Архитектор", "Системный аналитик Middle"
_POS_GRADE = re.compile(rf"^{_GRADE_WORDS}\s+|(?:\s+от)?[\s/]+{_GRADE_WORDS}$", re.I)
_morph = None


def to_nominative(phrase: str) -> str:
    """Главное существительное и прилагательные перед ним — в именительный; хвост как есть.
    "Технического писателя" -> "Технический писатель", "Руководителя проектов" -> "Руководитель проектов".
    Без pymorphy3 возвращает как есть."""
    global _morph
    if _morph is None:
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
        except ImportError:
            _morph = False
    if not _morph:
        return phrase
    words = phrase.split()
    parses = [_morph.parse(w)[0] for w in words]
    # главное слово — первое существительное; уже в именительном ("Диктор для озвучки") — не трогаем
    head = next((i for i, p in enumerate(parses) if "NOUN" in p.tag), None)
    if head is None or parses[head].tag.case not in ("gent", "accs"):
        return phrase
    noun = parses[head].inflect({"nomn", "sing"}) or parses[head].inflect({"nomn"})
    if not noun:
        return phrase
    gender = parses[head].tag.gender or "masc"
    out = list(words)
    out[head] = noun.word
    for i in range(head):  # прилагательные перед существительным — в тот же род
        p = parses[i]
        if {"ADJF"} & set(p.tag.grammemes) or "PRTF" in p.tag:
            adj = p.inflect({"nomn", "sing", gender})
            if adj:
                out[i] = adj.word
    for i in range(head + 1):  # вернуть заглавные буквы / латиницу как в исходнике
        if words[i][:1].isupper():
            out[i] = out[i][:1].upper() + out[i][1:]
        if re.search(r"[A-Za-z]", words[i]):
            out[i] = words[i]
    return " ".join(out)


def _clean(s: str) -> str:
    return _EDGE.sub("", s).strip()


def _value(raw: str, field: str) -> str:
    s = raw.strip()
    if field in LIST_FIELDS:
        s = _BULLET.sub("", s, count=1)
        s = re.sub(r"^\W*(?:задачи|обязанности|требования)\w*\s*:\s*", "", s, flags=re.I)  # "🔘Задачи: …"
        return _clean(s)
    m = _LABEL.match(s)
    if m and len(s) > m.end():  # "Ставка: 2200" -> "2200"
        if field == "position" and ":" not in m.group(0) and ROLE_WORD.search(s[:m.end()]):
            s = s[:m.end()].rstrip(" :–—-")  # "QA Manual (Senior) – 2 позиции - 1.000": роль слева от тире
        else:
            s = s[m.end():]
    if field == "position":
        # "ID:14918_Аналитик ...", "❌ПАУЗА_ID:15096_...", "ID 3736.Java developer" -> без номера
        s = _POS_PREFIX.sub("", _clean(s))
        # "Мы в поиске Архитектора", "Ищем 1 Senior Архитектор", "ТРЕБУЕТСЯ 2 Frontend" -> суть
        intro = _POS_INTRO.match(s)
        s = _POS_INTRO.sub("", s)
        # грейд — отдельное поле: "Senior/Lead Архитектор" -> "Архитектор"
        s = _POS_GRADE.sub("", s).strip(" /,-–—")
        if intro:
            s = to_nominative(s)  # "Технического писателя" -> "Технический писатель"
    if field == "request_number":
        s = s.strip("()[] ")
    return _clean(s)


class LineModel:
    """Быстрая модель: TF-IDF + логистическая регрессия (model/lines-baseline.joblib)."""

    def __init__(self, path: str = DEFAULT_PATH):
        import joblib
        bundle = joblib.load(path)
        self.features, self.clf = bundle["features"], bundle["clf"]

    def _predict_lines(self, lines) -> tuple[list[str], list[float]]:
        rows = [{"idx": i, "prev": ln.context, "prev_text": lines[i - 1].raw if i else "", "text": ln.raw}
                for i, ln in enumerate(lines)]
        proba = self.clf.predict_proba(self.features.transform(rows))
        best = proba.argmax(axis=1)
        return [str(self.clf.classes_[b]) for b in best], [float(p[b]) for p, b in zip(proba, best)]

    def label_lines(self, text: str) -> list[tuple[str, str, float]]:
        """[(строка, поле, уверенность)] — с поправками структуры поста (parser/line_post.py)."""
        lines = split_lines(text)
        if not lines:
            return []
        labels, conf = self._predict_lines(lines)
        labels = fix_labels([ln.raw for ln in lines], labels)
        return [(ln.raw, lab, c) for ln, lab, c in zip(lines, labels, conf)]

    def predict(self, text: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for raw, lab, conf in self.label_lines(text):
            if conf < LOW_CONFIDENCE and lab != "header":
                out.setdefault("_uncertain", []).append(raw)
            if lab in ("header", "junk"):  # junk — инструкции к подаче резюме (parser/line_post.py)
                continue
            if lab == "other":
                v = _clean(raw)
                if len(v) > 3 and not _JUNK.search(raw):
                    out.setdefault("extra", []).append(v)
                continue
            v = _value(raw, lab)
            if v:
                out.setdefault(lab, []).append(v)
        # значения, которые модель поставила в поле, но по форме не подходят
        for f, bad in _NOT_A_VALUE.items():
            if f in out:
                keep = [v for v in out[f] if not bad(v)]
                if keep:
                    out[f] = keep
                else:
                    del out[f]
        if "position" not in out:
            pos = _position_from_lines(text)
            if pos:
                out["position"] = [pos]
        for f in JOIN_FIELDS & out.keys():
            out[f] = ["; ".join(out[f])]
        return out


def _position_from_lines(text: str) -> str | None:
    """Первая строка в начале поста, где видно роль ("👉Vue.js разработчик", "Аналитик 1С")."""
    for ln in split_lines(text)[:12]:
        raw = ln.raw
        if len(raw) > 140 or raw.rstrip().endswith(":") or re.match(r"^\W*(?:[-•*–]|\d+[.)])\s", raw):
            continue  # пункты списков и заголовки секций — не название позиции
        v = _value(raw, "position")
        if v and ROLE_WORD.search(v) and not _bad_position(v) and not _LABEL_ANY.match(raw):
            return v
    return None


# строка с подписью другого поля ("Грейд: Senior", "Локация: РФ") — не позиция
_LABEL_ANY = re.compile(r"^[^\w№]*(?:грейд|уровень|локац|ставк|рейт|срок|длительн|проект|заказчик|опыт|формат|"
                        r"гражданство|контакт|оплат|загрузк|старт)\w*\s*[:\-–—]", re.I)


_URL_ONLY = re.compile(r"^\W*(?:https?://|t\.me/)\S+\W*$", re.I)
_NOT_POSITION = re.compile(r"срочно|asap|поиск\s+\d|горящ|добрый\s+день|привет|коллеги|всем\s+(?:привет|добр)|"
                           r"актуальн|бенч|закрыт|пауза\W*$|^\W*статус|запросы\W*$", re.I)
# по названию роли видно, кто нужен: "Срочно ищем Senior DevOps Engineer" — позиция верная, несмотря на «срочно»
ROLE_WORD = re.compile(
    r"разработчик|программист|developer|engineer|инженер|аналитик|analyst|архитектор|architect|тестировщик|"
    r"\bqa\b|devops|\bsre\b|\bdba\b|администратор|admin|консультант|consultant|дизайнер|designer|менеджер|manager|"
    r"\bpm\b|\bpo\b|owner|lead\b|тимлид|писател|writer|специалист|specialist|scientist|scrum|рекрутер|recruiter|"
    r"маркетолог|верстальщик|\bseo\b|\b1[сc]\b|\bsap\b|java|python|golang|\bgo\b|react|angular|\bvue\b|frontend|"
    r"backend|full-?stack|\bios\b|android|\.net|c#|\bphp\b|\bml\b|\bai\b|data|\bbi\b|dwh|\betl\b|rust|kotlin|swift|"
    r"flutter|node|typescript|secops|mlops|руководител|эксперт|expert|диктор|оператор", re.I)


def _bad_position(v: str) -> bool:
    if _URL_ONLY.match(v) or not re.search(r"[A-Za-zА-Яа-я]{2}", v):
        return True
    if v.count("#") >= 2 or re.match(r"^\W*\d+\s+позици", v, re.I) or v.strip(" .,!").lower() in ("мы", "ищем"):
        return True  # "fulltime #vacancy #mlsecops", "2 позиции - 1.000", "Мы"
    # «срочно / всем привет / актуальные запросы» — мусор, только если роли в строке не видно
    return bool(_NOT_POSITION.search(v)) and not ROLE_WORD.search(v)


_NOT_A_VALUE = {
    # "❗️СРОЧНО. ПОИСК 1-2 ДНЯ", "Всем добрый день!", ссылка на заявку — не название позиции
    "position": _bad_position,
    # "Уровень английского языка - Intermediate" — язык, а не грейд
    "grade": lambda v: bool(re.search(r"английск|english|язык|b1|b2|c1|intermediate|upper|advanced", v, re.I)),
    # "ЗАКРЫТ", "АКТУАЛЬНЫЙ БЕНЧ" — статус, а не номер заявки
    "request_number": lambda v: not re.search(r"\d", v),
    # контакт без @, ссылки, почты, телефона и слов про чат/личку — не контакт (пункт задач, описание)
    "contacts": lambda v: not re.search(r"@\w|https?://|t\.me/|\.ru\b|\.com\b|\.io\b|forms\.gle|\+7|\d{3}[\s-]?\d{3}|"
                                        r"чат|личн|лс\b|директ|почт|e-?mail|телефон|hh\.ru|сайт", v, re.I),
    # "21092608А" — код заявки, а не ставка
    "rate": lambda v: bool(re.fullmatch(r"\W*\d{6,}[A-Za-zА-Яа-я]?\W*", v)),
}


class BertLineModel(LineModel):
    """Та же сборка полей, но метки строк даёт дообученный трансформер (rubert-tiny2 / DistilBERT)."""

    def __init__(self, path: str = BERT_PATH):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).eval()
        self.id2label = self.model.config.id2label

    def _predict_lines(self, lines) -> tuple[list[str], list[float]]:
        # вход как при обучении (scripts/train_lines_bert.py): "[номер строки] заголовок секции" + строка
        first = [f"[{min(i, 5)}] {ln.context}" for i, ln in enumerate(lines)]
        enc = self.tokenizer(first, [ln.raw for ln in lines], truncation="only_second", max_length=96,
                             padding=True, return_tensors="pt")
        with self.torch.no_grad():
            proba = self.model(**enc).logits.softmax(-1)
        conf, best = proba.max(-1)
        return [self.id2label[int(b)] for b in best], conf.tolist()


def load_line_model(path: str | None = None) -> LineModel | None:
    """Порядок: явный путь; env LINE_MODEL_PATH; иначе нейросеть (model/lines-rubert), иначе быстрая модель."""
    path = path or os.environ.get("LINE_MODEL_PATH")
    candidates = [path] if path else [BERT_PATH, DEFAULT_PATH]
    for p in candidates:
        if not p or not os.path.exists(p):
            continue
        try:
            return BertLineModel(p) if os.path.isdir(p) else LineModel(p)
        except Exception:
            continue
    return None
