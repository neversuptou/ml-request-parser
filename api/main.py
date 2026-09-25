"""HTTP-сервис разбора заявок.

    uvicorn api.main:app --host 0.0.0.0 --port 8010

POST /parse {"text": "..."} ->
    fields          — поля в формате Application прода (application_number, project_title, position,
                      level, experience, project_duration, rate, requirements, tasks, location,
                      contact_details); значения — строка или null
    extra_information — строки поста, не попавшие в поля (без мусора)
    post_kind       — null | "not_vacancy" | "digest" | "short"
    check           — причины открыть заявку в оригинале ("⚠️ Проверить вручную")
    needs_fallback  — разбор ненадёжен (дайджест / короткий пост / нет позиции)
    rendered        — итоговый текст «Найден запрос»
GET /health       — статус и какая модель загружена
"""
import os
import time

from fastapi import FastAPI
from pydantic import BaseModel

from parser.extractor import _default_model, extract, render, to_prod_fields

VERSION = os.environ.get("SERVICE_VERSION", "1.0.0")

app = FastAPI(title="ml-request-parser", version=VERSION)
model = _default_model()
model_name = type(model).__name__ if model else None


class ParseRequest(BaseModel):
    text: str


class ParseResponse(BaseModel):
    fields: dict[str, str | None]
    extra_information: str | None
    post_kind: str | None
    check: list[str]
    needs_fallback: bool
    rendered: str
    model: str | None
    version: str
    elapsed_ms: int


@app.post("/parse", response_model=ParseResponse)
def parse(req: ParseRequest) -> ParseResponse:
    started = time.perf_counter()
    f = extract(req.text, model)
    prod = to_prod_fields(f)
    kind = f.get("post_kind")
    return ParseResponse(
        fields=prod,
        extra_information="\n".join(f.get("extra") or []) or None,
        post_kind=kind,
        check=list(f.get("check") or []),
        needs_fallback=kind in ("digest", "short") or not prod["position"],
        rendered=render(f),
        model=model_name,
        version=VERSION,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


@app.get("/health")
def health():
    return {"status": "ok" if model is not None else "degraded", "model": model_name, "version": VERSION}
