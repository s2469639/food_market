import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from market_compass.extract import SOURCE, ExtractionError, load_key, run


def response(quote=None):
    source = json.loads(SOURCE.read_text())
    payload = {"country": "Australia", "product_scope": "sweet biscuits category",
               "signal": "스위트 비스킷 소비 추정 감소", "quotes": [quote or "Sweet biscuits, down 0.3 grams (-2.2%) to 13.6 grams per capita per day"],
               "limitations": ["소매 판매 기반 실험적 추정이며 제품별 수요가 아닙니다."],
               "specific_product_demand_confirmed": False}
    return {"model": "test-model", "choices": [{"finish_reason": "tool_calls", "message": {
        "tool_calls": [{"function": {"name": "submit_evidence", "arguments": json.dumps(payload)}}]}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}}


class ExtractionTests(unittest.TestCase):
    def test_preview_never_loads_key_or_calls_network(self):
        opener = Mock(side_effect=AssertionError("network"))
        with patch("market_compass.extract.load_key", side_effect=AssertionError("key read")):
            self.assertEqual(run(opener=opener)["network_calls"], 0)
        opener.assert_not_called()

    def test_env_loading_does_not_execute_or_override_environment(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env = Path(directory) / ".env"
            env.write_text('IGNORED=$(touch should-not-exist)\nOPENAI_API_KEY="dummy-key"\n')
            self.assertEqual(load_key(env), "dummy-key")
            os.environ["OPENAI_API_KEY"] = "environment-key"
            self.assertEqual(load_key(env), "environment-key")
            self.assertNotIn("IGNORED", os.environ)

    def test_success_cached_and_exact_source_preserved(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-key"}, clear=True):
            opener = Mock(return_value=io.StringIO(json.dumps(response())))
            first = run(execute=True, output_dir=directory, opener=opener)
            self.assertEqual(first["network_calls"], 1)
            saved = json.loads(Path(first["result_file"]).read_text())
            self.assertEqual(saved["source"], json.loads(SOURCE.read_text()))
            self.assertEqual(saved["review_status"], "needs_human_review")
            self.assertNotIn("dummy-key", Path(first["result_file"]).read_text())
            self.assertEqual(run(execute=True, output_dir=directory, opener=opener)["mode"], "cached")
            self.assertEqual(opener.call_count, 1)

    def test_invalid_quote_keeps_usage_and_blocks_repeat(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-key"}, clear=True):
            opener = Mock(return_value=io.StringIO(json.dumps(response("invented statement"))))
            with self.assertRaises(ExtractionError):
                run(execute=True, output_dir=directory, opener=opener)
            self.assertFalse(list(Path(directory).rglob('result.json')))
            state = json.loads(next(Path(directory).rglob('attempt.json')).read_text())
            self.assertEqual(state["usage"]["total_tokens"], 300)
            with self.assertRaises(ExtractionError):
                run(execute=True, output_dir=directory, opener=opener)
            self.assertEqual(opener.call_count, 1)

    def test_provider_error_is_redacted_and_not_retried(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-key"}, clear=True):
            opener = Mock(side_effect=HTTPError("url", 401, "dummy-key", {}, io.BytesIO(b"dummy-key")))
            with self.assertRaises(ExtractionError) as caught:
                run(execute=True, output_dir=directory, opener=opener)
            self.assertNotIn("dummy-key", str(caught.exception))
            self.assertEqual(opener.call_count, 1)
            self.assertNotIn("dummy-key", next(Path(directory).rglob('attempt.json')).read_text())
