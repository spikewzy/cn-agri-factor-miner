import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from doctor import inspect_environment, ROOT
from records import write_once, read_json


class EnvironmentTests(unittest.TestCase):
    def test_external_run_directory_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            result = inspect_environment(Path(temp) / '中文 output')
            self.assertEqual(result['status'], 'READY')
            self.assertEqual(result['missing_capabilities'], [])

    def test_reject_output_inside_skill(self):
        target = ROOT / 'forbidden-output'
        result = inspect_environment(target)
        self.assertEqual(result['status'], 'BLOCKED_ENVIRONMENT')
        self.assertFalse(target.exists())

    def test_missing_resources_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            result = inspect_environment(Path(temp) / 'output', Path(temp) / 'empty-skill')
            self.assertIn('bundled_file:SKILL.md', result['missing_capabilities'])
            self.assertFalse((Path(temp) / 'output').exists())

    def test_missing_posix_lock_stops_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'output'
            with patch('doctor.importlib.util.find_spec', return_value=None):
                result = inspect_environment(target)
            self.assertEqual(result['status'], 'BLOCKED_ENVIRONMENT')
            self.assertTrue(any('POSIX_file_locking' in k for k in result['missing_capabilities']))
            self.assertFalse(target.exists())

    def test_chinese_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / '中文 审核.json'
            value = {'审核人': '合成测试人员', 'scope': '豆粕/豆油', 'origin': 'simulated_test'}
            write_once(target, value)
            self.assertEqual(read_json(target), value)
            self.assertIn('审核人', target.read_bytes().decode('utf-8'))


if __name__ == '__main__': unittest.main()
