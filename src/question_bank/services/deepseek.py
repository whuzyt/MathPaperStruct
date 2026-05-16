from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from question_bank.domain.schemas import (
    DEEPSEEK_CONFIDENCE_REQUIRED_FIELDS,
    DEEPSEEK_QUESTION_REQUIRED_FIELDS,
    DEEPSEEK_QUESTION_SCHEMA,
    DEEPSEEK_QUESTION_TYPES,
)


class DeepSeekResponseError(ValueError):
    """Raised when a DeepSeek response cannot be trusted as structured data."""


class DeepSeekClientProtocol(Protocol):
    def structure_question(self, raw_markdown: str) -> dict[str, Any]:
        """Return a structured question payload for a raw question block."""


class JSONTransportProtocol(Protocol):
    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> bytes:
        """Send a JSON request and return raw response bytes."""


@dataclass(slots=True)
class UrlLibJSONTransport:
    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()


@dataclass(slots=True)
class DeepSeekHTTPClient:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout: float = 60.0
    transport: JSONTransportProtocol = field(default_factory=UrlLibJSONTransport)

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("DeepSeek API key is required.")
        self.base_url = self.base_url.rstrip("/")

    def structure_question(self, raw_markdown: str) -> dict[str, Any]:
        request_payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是数学题库结构化助手。只输出 JSON，不要输出 Markdown。"
                        "不要编造原文不存在的答案、解析或图片。"
                    ),
                },
                {
                    "role": "user",
                    "content": build_structure_prompt(raw_markdown),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            raw_response = self.transport.post_json(
                f"{self.base_url}/chat/completions",
                request_payload,
                headers,
                self.timeout,
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            raise DeepSeekResponseError(f"DeepSeek request failed: {exc}") from exc

        content = _extract_chat_content(raw_response)
        return parse_deepseek_question_response(content)


class FakeDeepSeekClient:
    """Deterministic local stand-in used by tests and development previews."""

    def structure_question(self, raw_markdown: str) -> dict[str, Any]:
        return {
            "question_type": "short_answer",
            "stem_latex": raw_markdown.strip(),
            "choices": [],
            "answer_latex": "",
            "analysis_latex": "",
            "knowledge_points": [],
            "difficulty": None,
            "confidence": {
                "structure": 1.0,
                "latex": 1.0,
                "answer": 0.0,
                "knowledge": 0.0,
            },
            "warnings": ["fake_client_output"],
        }


def parse_deepseek_question_response(response_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise DeepSeekResponseError(f"DeepSeek returned malformed JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise DeepSeekResponseError("DeepSeek response must be a JSON object.")

    missing = sorted(DEEPSEEK_QUESTION_REQUIRED_FIELDS - payload.keys())
    if missing:
        raise DeepSeekResponseError(f"DeepSeek response missing required fields: {', '.join(missing)}")

    _validate_payload_shape(payload)
    return payload


def _extract_chat_content(raw_response: bytes) -> str:
    try:
        payload = json.loads(raw_response.decode("utf-8"))
        return payload["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise DeepSeekResponseError("DeepSeek chat completion response has unexpected shape.") from exc


def build_structure_prompt(raw_markdown: str) -> str:
    return f"""
请把下面的数学题块转换为严格 JSON，字段必须包含：
question_type, stem_latex, choices, answer_latex, analysis_latex,
knowledge_points, difficulty, confidence, warnings。

JSON Schema:
{json.dumps(DEEPSEEK_QUESTION_SCHEMA, ensure_ascii=False, indent=2)}

要求：
- 保留数学公式 LaTeX。
- choices 必须是数组，每个元素包含 label 和 content_latex。
- 如果答案或解析原文不存在，返回空字符串，不要猜测。
- 如果无法确定字段，写入 warnings。
- question_type 只能从 schema enum 中选择。
- confidence 的每个值必须是 0 到 1 之间的数字。

题块：
{raw_markdown}
""".strip()


def _validate_payload_shape(payload: dict[str, Any]) -> None:
    if payload["question_type"] not in DEEPSEEK_QUESTION_TYPES:
        raise DeepSeekResponseError(f"Invalid question_type: {payload['question_type']}")

    for field_name in [
        "stem_latex",
        "answer_latex",
        "analysis_latex",
    ]:
        if not isinstance(payload[field_name], str):
            raise DeepSeekResponseError(f"{field_name} must be a string.")

    if not isinstance(payload["choices"], list):
        raise DeepSeekResponseError("choices must be an array.")
    for index, choice in enumerate(payload["choices"], start=1):
        if not isinstance(choice, dict):
            raise DeepSeekResponseError(f"choices[{index}] must be an object.")
        if not isinstance(choice.get("label"), str) or not isinstance(choice.get("content_latex"), str):
            raise DeepSeekResponseError(
                f"choices[{index}] must include string label and content_latex."
            )

    if not isinstance(payload["knowledge_points"], list) or not all(
        isinstance(item, str) for item in payload["knowledge_points"]
    ):
        raise DeepSeekResponseError("knowledge_points must be an array of strings.")

    difficulty = payload["difficulty"]
    if difficulty is not None and (
        not isinstance(difficulty, int) or difficulty < 1 or difficulty > 5
    ):
        raise DeepSeekResponseError("difficulty must be null or an integer from 1 to 5.")

    confidence = payload["confidence"]
    if not isinstance(confidence, dict):
        raise DeepSeekResponseError("confidence must be an object.")
    missing_confidence = sorted(DEEPSEEK_CONFIDENCE_REQUIRED_FIELDS - confidence.keys())
    if missing_confidence:
        raise DeepSeekResponseError(
            f"confidence missing required fields: {', '.join(missing_confidence)}"
        )
    for key in DEEPSEEK_CONFIDENCE_REQUIRED_FIELDS:
        value = confidence[key]
        if not isinstance(value, int | float) or value < 0 or value > 1:
            raise DeepSeekResponseError(f"confidence.{key} must be a number from 0 to 1.")

    if not isinstance(payload["warnings"], list) or not all(
        isinstance(item, str) for item in payload["warnings"]
    ):
        raise DeepSeekResponseError("warnings must be an array of strings.")
