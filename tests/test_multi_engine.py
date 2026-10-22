"""
tests/test_multi_engine.py - Testes unitários para a seleção multi-motor (Gemini, Ollama, Qwen, Kimi).
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings_manager
import director_ai


class TestMultiEngine(unittest.TestCase):
    def test_settings_manager_engine_options(self):
        self.assertTrue(len(settings_manager.AVAILABLE_DIRECTOR_ENGINES) >= 4)
        engine_codes = [c for c, _ in settings_manager.AVAILABLE_DIRECTOR_ENGINES]
        self.assertIn("gemini", engine_codes)
        self.assertIn("ollama_local", engine_codes)
        self.assertIn("qwen_max", engine_codes)
        self.assertIn("kimi", engine_codes)

    def test_settings_manager_ollama_models(self):
        model_codes = [c for c, _ in settings_manager.AVAILABLE_OLLAMA_MODELS]
        self.assertIn("qwen2.5:7b", model_codes)

    def test_ollama_connection_status(self):
        ok, msg = settings_manager.test_ollama_connection("qwen2.5:7b")
        # Ollama daemon was started and model downloaded
        self.assertTrue(ok)
        self.assertIn("Ollama", msg)

    def test_save_and_load_director_engine(self):
        import tempfile
        # Use isolated temp file to NEVER touch project .env
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".env") as tf:
            temp_env_path = Path(tf.name)
            tf.write("GEMINI_API_KEY=test_key\n")

        original_env_path = settings_manager.ENV_PATH
        try:
            settings_manager.ENV_PATH = temp_env_path
            settings_manager.save_app_settings(
                gemini_keys_text="test_key_1,test_key_2",
                gemini_model="gemini-3.8-flash",
                director_engine="ollama_local",
                director_local_model="qwen2.5:7b",
                env_file_path=temp_env_path,
            )
            loaded = settings_manager.load_app_settings(env_file_path=temp_env_path) if "env_file_path" in settings_manager.load_app_settings.__code__.co_varnames else settings_manager.load_app_settings()
            self.assertEqual(loaded.get("director_engine"), "ollama_local")
            self.assertEqual(loaded.get("director_local_model"), "qwen2.5:7b")

            settings_manager.save_app_settings(
                gemini_keys_text="test_key_1",
                gemini_model="gemini-3.8-flash",
                director_engine="gemini",
                director_local_model="qwen2.5:7b",
                env_file_path=temp_env_path,
            )
            loaded_default = settings_manager.load_app_settings(env_file_path=temp_env_path) if "env_file_path" in settings_manager.load_app_settings.__code__.co_varnames else settings_manager.load_app_settings()
            self.assertEqual(loaded_default.get("director_engine"), "gemini")
        finally:
            settings_manager.ENV_PATH = original_env_path
            if temp_env_path.exists():
                temp_env_path.unlink()


if __name__ == "__main__":
    unittest.main()
