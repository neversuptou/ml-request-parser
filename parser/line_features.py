"""Признаки для построчного классификатора (вынесено из скрипта, чтобы joblib мог загрузить модель)."""
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer


def pos_tokens(rows):
    # позиция строки в посте — словами, чтобы шла тем же TF-IDF: первая строка почти всегда позиция
    return [f"idx{min(r['idx'], 5)}" for r in rows]


class LineFeatures:
    def __init__(self):
        self.text = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3,
                                    max_features=200_000, sublinear_tf=True, lowercase=True)
        # заголовок секции над строкой ("Будет плюсом:", "Задачи:")
        self.ctx = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                                   max_features=30_000, lowercase=True)
        # предыдущая строка: пункт списка обычно продолжает соседний
        self.prev_line = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                                         max_features=50_000, sublinear_tf=True, lowercase=True)
        self.pos = TfidfVectorizer(token_pattern=r"\S+")

    def fit(self, rows):
        self.text.fit([r["text"] for r in rows])
        self.ctx.fit([r["prev"] or "_" for r in rows])
        self.prev_line.fit([r.get("prev_text") or "_" for r in rows])
        self.pos.fit(pos_tokens(rows))
        return self

    def transform(self, rows):
        return hstack([
            self.text.transform([r["text"] for r in rows]),
            self.ctx.transform([r["prev"] or "_" for r in rows]),
            self.prev_line.transform([r.get("prev_text") or "_" for r in rows]),
            self.pos.transform(pos_tokens(rows)),
        ]).tocsr()
