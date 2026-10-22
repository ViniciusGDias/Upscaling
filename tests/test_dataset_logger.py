"""
tests/test_dataset_logger.py - Testes unitários para o subsistema de log permanente de IA.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dataset_logger
import director_ai


class TestDatasetLogger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_append_record_creates_valid_jsonl(self):
        rec_id = dataset_logger.append_record(
            "test_task",
            {"prompt": "hello", "response": "world"},
            directory=self.log_dir,
        )
        self.assertIsNotNone(rec_id)
        log_file = self.log_dir / "test_task.jsonl"
        self.assertTrue(log_file.exists())

        with open(log_file, "r", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["record_id"], rec_id)
        self.assertEqual(lines[0]["prompt"], "hello")
        self.assertEqual(lines[0]["schema"], dataset_logger.SCHEMA_VERSION)

    def test_text_fingerprint_stability(self):
        fp1 = dataset_logger.text_fingerprint("episodio de teste 01")
        fp2 = dataset_logger.text_fingerprint("episodio de teste 01")
        fp3 = dataset_logger.text_fingerprint("outro texto")
        self.assertEqual(fp1, fp2)
        self.assertNotEqual(fp1, fp3)
        self.assertEqual(len(fp1), 16)

    def test_logger_fail_safe_on_invalid_dir(self):
        # Passing an existing file as directory causes NotADirectoryError / PermissionError
        dummy_file = self.log_dir / "regular_file.txt"
        dummy_file.write_text("not a directory", encoding="utf-8")
        rec_id = dataset_logger.append_record("test", {"dummy": 1}, directory=dummy_file)
        self.assertIsNone(rec_id)

    def test_director_sample_logging(self):
        rec_id = dataset_logger.log_director_sample(
            prompt="Prompt test",
            response='{"candidates": []}',
            provider_info={"provider": "gemini", "model": "gemini-2.5-flash"},
            params={"call": "test_call", "mode": "top3"},
            n_candidates=0,
        )
        self.assertIsNotNone(rec_id)


if __name__ == "__main__":
    unittest.main()
