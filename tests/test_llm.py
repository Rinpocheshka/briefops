import io
import json
import unittest
from unittest.mock import patch

from app import analyze
from llm import NVIDIA_MODEL, complete_json


class ProviderTests(unittest.TestCase):
    def response(self, result):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode())

    @patch.dict("os.environ", {"BRIEFOPS_LLM_PROVIDER": "nvidia", "NVIDIA_API_KEY": "test-only"}, clear=True)
    def test_nvidia_request_and_validated_fields(self):
        with patch("urllib.request.urlopen", return_value=self.response({"service": "automation", "summary": "Передача заявок в CRM", "urgent": False, "budget": 1, "contact": "fake@example.com"})) as call:
            result, warning = analyze("Бюджет 150 тыс. demo@example.com", use_llm=True)
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(body["model"], NVIDIA_MODEL)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(result["engine"], "llm")
        self.assertEqual(result["provider"], "nvidia")
        self.assertEqual(result["budget"], 150000)
        self.assertEqual(result["contact"], "demo@example.com")
        self.assertFalse(warning)
        self.assertNotIn("test-only", json.dumps(result))

    @patch.dict("os.environ", {"BRIEFOPS_LLM_PROVIDER": "nvidia", "NVIDIA_API_KEY": "test-only"}, clear=True)
    def test_bad_schema_falls_back(self):
        for invalid in ([1], {"service": "bad", "summary": "x", "urgent": False}, {"service": "website", "summary": "x", "urgent": "yes"}):
            with self.subTest(invalid=invalid), patch("urllib.request.urlopen", return_value=self.response(invalid)):
                result, warning = analyze("Сайт. 120 тыс. real@example.com", use_llm=True)
                self.assertEqual(result["engine"], "rules")
                self.assertEqual(result["budget"], 120000)
                self.assertTrue(warning)

    @patch.dict("os.environ", {"BRIEFOPS_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "test-only", "OPENROUTER_MODEL": "test-model"}, clear=True)
    def test_openrouter_adapter_remains_available(self):
        with patch("urllib.request.urlopen", return_value=self.response({"service": "bot", "summary": "Бот", "urgent": True})) as call:
            result, metadata = complete_json("JSON", "Нужен бот")
        self.assertEqual(call.call_args.args[0].full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertNotIn("chat_template_kwargs", json.loads(call.call_args.args[0].data))
        self.assertEqual(metadata["provider"], "openrouter")

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-only"}, clear=True)
    def test_rules_mode_never_calls_provider(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            result, warning = analyze("Нужен сайт", use_llm=False)
        self.assertEqual(result["engine"], "rules")
