import os
import unittest
from unittest.mock import patch

from question_bank.config import Settings


class SettingsTest(unittest.TestCase):
    def test_loads_defaults(self):
        settings = Settings.from_env({})

        self.assertEqual(settings.deepseek_base_url, "https://api.deepseek.com")
        self.assertEqual(settings.deepseek_model, "deepseek-chat")
        self.assertEqual(settings.mineru_command, "mineru")
        self.assertEqual(settings.minio_endpoint, "http://localhost:9000")
        self.assertEqual(settings.minio_access_key, "questionbank")
        self.assertEqual(settings.minio_secret_key, "questionbank123")
        self.assertIsNone(settings.deepseek_api_key)

    def test_loads_environment_values(self):
        env = {
            "DEEPSEEK_API_KEY": "sk-test",
            "DEEPSEEK_BASE_URL": "https://example.test",
            "DEEPSEEK_MODEL": "deepseek-reasoner",
            "MINERU_COMMAND": "magic-pdf",
            "MINIO_ENDPOINT": "http://minio.test:9000",
            "MINIO_ACCESS_KEY": "access",
            "MINIO_SECRET_KEY": "secret",
        }

        settings = Settings.from_env(env)

        self.assertEqual(settings.deepseek_api_key, "sk-test")
        self.assertEqual(settings.deepseek_base_url, "https://example.test")
        self.assertEqual(settings.deepseek_model, "deepseek-reasoner")
        self.assertEqual(settings.mineru_command, "magic-pdf")
        self.assertEqual(settings.minio_endpoint, "http://minio.test:9000")
        self.assertEqual(settings.minio_access_key, "access")
        self.assertEqual(settings.minio_secret_key, "secret")

    def test_loads_from_process_environment(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-process"}, clear=False):
            settings = Settings.load()

        self.assertEqual(settings.deepseek_api_key, "sk-process")

    def test_enable_layout_ownership_defaults_to_false(self):
        settings = Settings.from_env({})
        self.assertFalse(settings.enable_layout_ownership)

    def test_enable_layout_ownership_true(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            with self.subTest(value=value):
                settings = Settings.from_env({"ENABLE_LAYOUT_OWNERSHIP": value})
                self.assertTrue(settings.enable_layout_ownership)


if __name__ == "__main__":
    unittest.main()
