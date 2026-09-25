"""uvicorn api.main:app --port 8000"""
from fastapi import FastAPI
from pydantic import BaseModel

from parser.extractor import _default_model, extract, render

app = FastAPI(title="Vacancy Parser")
model = _default_model()  # построчная модель, если обучена; иначе NER; иначе только regex
model_name = type(model).__name__ if model else None


class ParseRequest(BaseModel):
    text: str


@app.post("/parse")
def parse(req: ParseRequest):
    fields = extract(req.text, model)
    return {"fields": fields, "rendered": render(fields), "model": model_name}


@app.get("/health")
def health():
    return {"status": "ok", "model": model_name}
