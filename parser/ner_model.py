"""Инференс NER-модели. torch/transformers импортируются лениво."""
import os

DEFAULT_PATH = "model/vacancy-ner"
MAX_LEN = 512
STRIDE = 128


class NerModel:
    def __init__(self, path: str = DEFAULT_PATH):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForTokenClassification.from_pretrained(path).eval()
        self.id2label = self.model.config.id2label

    def predict(self, text: str) -> dict[str, list[str]]:
        enc = self.tokenizer(text, truncation=True, max_length=MAX_LEN, stride=STRIDE,
                             return_overflowing_tokens=True, return_offsets_mapping=True,
                             padding=True, return_tensors="pt")
        offsets = enc.pop("offset_mapping").tolist()
        enc.pop("overflow_to_sample_mapping", None)
        with self.torch.no_grad():
            pred = self.model(**enc).logits.argmax(-1).tolist()

        # Токен -> метка; при перекрытии окон берём первое предсказание.
        tags: dict[tuple[int, int], str] = {}
        for win_offsets, win_pred in zip(offsets, pred):
            for (s, e), p in zip(win_offsets, win_pred):
                if s != e:
                    tags.setdefault((s, e), self.id2label[p])

        spans: list[list] = []  # [field, start, end]
        for (s, e), tag in sorted(tags.items()):
            if tag == "O":
                continue
            prefix, field = tag.split("-", 1)
            if prefix == "I" and spans and spans[-1][0] == field:
                spans[-1][2] = e
            else:
                spans.append([field, s, e])

        result: dict[str, list[str]] = {}
        for field, s, e in spans:
            value = text[s:e].strip()
            if value:
                result.setdefault(field.lower(), []).append(value)
        return result


def load_ner(path: str = DEFAULT_PATH) -> NerModel | None:
    if not os.path.isdir(path):
        return None
    try:
        return NerModel(path)
    except ImportError:
        return None
