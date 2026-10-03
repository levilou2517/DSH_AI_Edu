import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / 'services/shiban_cli.py'


class MaterialCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='test-material-cli-')
        self.env = {**os.environ, 'SHIBAN_ROOT': self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, text=None):
        return subprocess.run(['python3', str(CLI), *args], input=text,
                              capture_output=True, text=True, env=self.env)

    def test_schema_and_invalid_json(self):
        result = self.run_cli('asset', 'compose', '--spec-schema')
        self.assertEqual(result.returncode, 0)
        self.assertIn('sections', json.loads(result.stdout)['required'])
        result = self.run_cli('asset', 'compose', '--spec-stdin', text='{bad')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_raw_large_stdin(self):
        text = '证据' * 100000
        result = self.run_cli('raw', 'save', '--name', 'test.txt', '--stdin', text=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['bytes'], len(text.encode()))
        self.assertEqual(self.run_cli('raw', 'save', '--name', 'test.txt', '--stdin', text=text).returncode, 2)

    def test_compose_file_and_stdin(self):
        source = Path(self.tmp.name) / 'atom.html'
        source.write_text('<html><body><p>Test</p></body></html>')
        self.assertEqual(self.run_cli('asset', 'add', '--id', 'a', '--kind', 'html', '--title', 'A', '--file', str(source)).returncode, 0)
        spec = {'page_id': 'p', 'title': 'P', 'sections': [{'asset': 'a'}]}
        result = self.run_cli('asset', 'compose', '--spec-stdin', text=json.dumps(spec))
        self.assertEqual(result.returncode, 0, result.stderr)
        spec_file = Path(self.tmp.name) / 'spec.json'
        spec_file.write_text(json.dumps(spec))
        result = self.run_cli('asset', 'compose', '--spec-file', str(spec_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['existed'])


if __name__ == '__main__':
    unittest.main()
