import unittest
from urllib.error import HTTPError

from question_bank.services.deepseek import (
    DeepSeekResponseError,
    DeepSeekHTTPClient,
    FakeDeepSeekClient,
    build_structure_prompt,
    parse_deepseek_question_response,
)


class DeepSeekAdapterTest(unittest.TestCase):
    def test_fake_client_returns_structured_question_json(self):
        client = FakeDeepSeekClient()

        payload = client.structure_question("1. 已知 $x=1$，求 $x+1$。")

        self.assertEqual(payload["question_type"], "short_answer")
        self.assertIn("$x=1$", payload["stem_latex"])
        self.assertEqual(payload["confidence"]["structure"], 1.0)

    def test_parse_rejects_malformed_json(self):
        with self.assertRaises(DeepSeekResponseError):
            parse_deepseek_question_response("{bad json")

    def test_parse_requires_question_type_and_stem(self):
        with self.assertRaises(DeepSeekResponseError):
            parse_deepseek_question_response('{"question_type": "single_choice"}')

    def test_parse_rejects_invalid_question_type(self):
        with self.assertRaises(DeepSeekResponseError):
            parse_deepseek_question_response(_payload_json(question_type="essay"))

    def test_parse_rejects_choice_without_content_latex(self):
        with self.assertRaises(DeepSeekResponseError):
            parse_deepseek_question_response(
                _payload_json(choices=[{"label": "A", "content": "$1$"}])
            )

    def test_parse_requires_confidence_keys(self):
        with self.assertRaises(DeepSeekResponseError):
            parse_deepseek_question_response(_payload_json(confidence={"structure": 1.0}))

    def test_build_structure_prompt_includes_schema_and_no_fabrication_rule(self):
        prompt = build_structure_prompt("1. 已知 $x=1$。")

        self.assertIn('"question_type"', prompt)
        self.assertIn('"single_choice"', prompt)
        self.assertIn('"content_latex"', prompt)
        self.assertIn("不要猜测", prompt)
        self.assertIn("1. 已知 $x=1$。", prompt)

    def test_http_client_posts_chat_completion_request(self):
        transport = RecordingTransport(
            response_body="""
{
  "choices": [
    {
      "message": {
        "content": "{\\"question_type\\":\\"short_answer\\",\\"stem_latex\\":\\"题干\\",\\"choices\\":[],\\"answer_latex\\":\\"\\",\\"analysis_latex\\":\\"\\",\\"knowledge_points\\":[],\\"difficulty\\":null,\\"confidence\\":{\\"structure\\":1.0,\\"latex\\":1.0,\\"answer\\":0.0,\\"knowledge\\":0.0},\\"warnings\\":[]}"
      }
    }
  ]
}
""".encode()
        )
        client = DeepSeekHTTPClient(
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            transport=transport,
        )

        payload = client.structure_question("1. 题干")

        self.assertEqual(payload["stem_latex"], "题干")
        self.assertEqual(transport.last_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(transport.last_headers["Authorization"], "Bearer sk-test")
        self.assertEqual(transport.last_json["model"], "deepseek-chat")
        self.assertIn("只输出 JSON", transport.last_json["messages"][0]["content"])
        self.assertIn('"question_type"', transport.last_json["messages"][1]["content"])

    def test_http_client_raises_for_missing_api_key(self):
        with self.assertRaises(ValueError):
            DeepSeekHTTPClient(api_key="")

    def test_http_client_wraps_http_errors(self):
        transport = RecordingTransport(error=HTTPError("url", 401, "Unauthorized", hdrs=None, fp=None))
        client = DeepSeekHTTPClient(api_key="sk-test", transport=transport)

        with self.assertRaises(DeepSeekResponseError):
            client.structure_question("1. 题干")


class RecordingTransport:
    def __init__(self, response_body: bytes = b"{}", error: Exception | None = None):
        self.response_body = response_body
        self.error = error
        self.last_url = ""
        self.last_headers = {}
        self.last_json = {}

    def post_json(self, url, payload, headers, timeout):
        self.last_url = url
        self.last_json = payload
        self.last_headers = headers
        if self.error is not None:
            raise self.error
        return self.response_body


def _payload_json(**overrides):
    payload = {
        "question_type": "single_choice",
        "stem_latex": "题干",
        "choices": [{"label": "A", "content_latex": "$1$"}],
        "answer_latex": "A",
        "analysis_latex": "",
        "knowledge_points": [],
        "difficulty": None,
        "confidence": {
            "structure": 1.0,
            "latex": 1.0,
            "answer": 1.0,
            "knowledge": 0.0,
        },
        "warnings": [],
    }
    payload.update(overrides)
    import json

    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
