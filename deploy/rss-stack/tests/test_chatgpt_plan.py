import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("chatgpt_plan", Path(__file__).parents[1] / "chatgpt_plan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


def events(*records):
    return ["data: " + json.dumps(record) for record in records]


class ChatGPTPlanTests(unittest.TestCase):
    def test_partial_translation_is_rejected_on_failure_disconnect_and_incomplete(self):
        first = {"type": "response.output_text.delta", "delta": "半篇译文"}
        for terminal in (None, "response.failed", "response.incomplete", "error"):
            with self.subTest(terminal=terminal):
                stream = events(first)
                if terminal:
                    stream.extend(events({"type": terminal}))
                with self.assertRaises(RuntimeError):
                    plan.consume_events(stream)

    def test_completed_translation_retains_unicode_and_usage(self):
        text, usage = plan.consume_events(events(
            {"type": "response.output_text.delta", "delta": "完整"},
            {"type": "response.output_text.delta", "delta": "译文<img src='x'>"},
            {"type": "response.completed", "response": {"usage": {"total_tokens": 12}}},
        ))
        self.assertEqual(text, "完整译文<img src='x'>")
        self.assertEqual(usage["total_tokens"], 12)

    def test_completed_empty_translation_is_rejected(self):
        with self.assertRaises(RuntimeError):
            plan.consume_events(events({"type": "response.completed"}))

    def test_deadline_does_not_return_buffered_partial_output(self):
        with self.assertRaises(RuntimeError):
            plan.consume_events(events({"type": "response.output_text.delta", "delta": "partial"},
                                       {"type": "response.completed"}), deadline=time.monotonic() - 1)

    def test_system_prompt_uses_instructions_and_only_luna_is_allowed(self):
        body = plan.request_body([{"role": "system", "content": "保留所有图片"},
                                  {"role": "user", "content": "Translate this"}])
        self.assertEqual(body["instructions"], "保留所有图片")
        self.assertEqual(body["input"], [{"role": "user", "content": "Translate this"}])
        self.assertIs(body["store"], False)
        self.assertIs(body["stream"], True)
        self.assertNotIn("temperature", body)
        self.assertNotIn("max_output_tokens", body)
        with self.assertRaises(ValueError):
            plan.request_body([{"role": "user", "content": "x"}], "other-model")

    def test_identity_alone_does_not_grant_plan_usage(self):
        with self.assertRaises(RuntimeError):
            plan.credential_record({"scope": "openid email", "access_token": "test"}, "test-client",
                                   "test-host", {"sub": "test-user", "iss": "https://auth.openai.com"})

    def test_rotating_refresh_token_and_permissions_are_saved_together(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            original = {"client_id": "test-client", "refresh_token": "old-test-refresh",
                        "access_token": "old-test-access", "expires_at": 0, "scopes": [plan.PLAN_SCOPE]}
            plan.save_private(path, original)
            response = Mock()
            response.json.return_value = {"refresh_token": "new-test-refresh", "access_token": "new-test-access",
                                          "expires_in": 3600, "scope": plan.PLAN_SCOPE}
            with patch.object(plan.requests, "post", return_value=response) as post:
                self.assertEqual(plan.access_token(path), "new-test-access")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["refresh_token"], "new-test-refresh")
            self.assertGreater(saved["expires_at"], time.time())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(post.call_args.kwargs["data"]["client_id"], "test-client")
            self.assertNotIn("scope", post.call_args.kwargs["data"])


if __name__ == "__main__":
    unittest.main()
