from __future__ import annotations

from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - lets core unit tests run before dependency install.
    FastAPI = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment,misc]

from question_bank.services.deepseek import FakeDeepSeekClient


if FastAPI is not None:

    class StructurePreviewRequest(BaseModel):
        raw_markdown: str

else:

    class StructurePreviewRequest:  # type: ignore[no-redef]
        def __init__(self, raw_markdown: str):
            self.raw_markdown = raw_markdown


def create_app() -> Any:
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Run `pip install -e .` before starting the API.")

    app = FastAPI(title="Question Bank Pipeline", version="0.1.0")
    deepseek_client = FakeDeepSeekClient()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/questions/structure-preview")
    def structure_preview(request: StructurePreviewRequest) -> dict[str, Any]:
        return deepseek_client.structure_question(request.raw_markdown)

    return app

