import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_skill', REPO / 'tools/package_skill.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
SOURCE = Path(os.environ.get('AGRI_TEST_SKILL_SOURCE', str(package.SOURCE)))


class PackagingTests(unittest.TestCase):
    def test_flat_root_metadata_and_identical_code(self):
        with tempfile.TemporaryDirectory() as temp:
            outputs = {target: package.build(SOURCE, temp, target) for target in ('portable', 'workbuddy')}
            with zipfile.ZipFile(Path(temp) / outputs['portable']['archive']) as generic, zipfile.ZipFile(Path(temp) / outputs['workbuddy']['archive']) as buddy:
                for z in (generic, buddy):
                    self.assertIn('SKILL.md', z.namelist())
                    self.assertIn('scripts/doctor.py', z.namelist())
                    self.assertFalse(any('.agents/' in n or '__pycache__' in n or n.startswith('runs/') for n in z.namelist()))
                g = generic.read('SKILL.md').decode('utf-8').split('---', 2)
                b = buddy.read('SKILL.md').decode('utf-8').split('---', 2)
                self.assertEqual(g[2], b[2])
                fields = {line.split(': ', 1)[0]: json.loads(line.split(': ', 1)[1]) for line in b[1].splitlines() if ': ' in line}
                for name in ('name', 'description', 'description_zh', 'description_en', 'version', 'author'):
                    self.assertTrue(fields[name])
                self.assertEqual(fields['version'], package.VERSION)
                for name in buddy.namelist():
                    if name != 'SKILL.md': self.assertEqual(generic.read(name), buddy.read(name))
                self.assertNotIn('agents/openai.yaml', buddy.namelist())

    def test_deterministic_archive_and_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            a = package.build(SOURCE, Path(temp) / 'a', 'workbuddy')
            b = package.build(SOURCE, Path(temp) / 'b', 'workbuddy')
            self.assertEqual(a, b)
            archive = Path(temp) / 'a' / a['archive']
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), a['sha256'])
            with zipfile.ZipFile(archive) as z:
                for name, sha in a['files'].items(): self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), sha)

    def test_relocated_packages_run_tests_demo_and_review_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            elsewhere = root / 'different cwd'; elsewhere.mkdir()
            for target in ('portable', 'workbuddy'):
                manifest = package.build(SOURCE, root / 'bundles', target)
                dest = root / ('中文 安装 ' + target)
                with zipfile.ZipFile(root / 'bundles' / manifest['archive']) as z: z.extractall(dest)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
                def command(args):
                    proc = subprocess.run([sys.executable] + [str(x) for x in args], cwd=elsewhere, env=env,
                                          capture_output=True, text=True, timeout=60)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    return proc
                run = root / ('研究 输出 ' + target)
                self.assertEqual(json.loads(command([dest / 'scripts/doctor.py', '--run-root', run]).stdout)['status'], 'READY')
                tests = command(['-m', 'unittest', 'discover', '-s', dest / 'tests', '-v'])
                self.assertIn('OK', tests.stderr)
                report = json.loads(command([dest / 'scripts/demo.py', '--output', run / 'demo']).stdout)
                self.assertEqual(report['initial_pause']['status'], 'PAUSED_REVIEW')
                self.assertTrue(all(r['status'] == 'NOT_EVALUATED' for r in report['normal']))
                self.assertEqual(report['version_history'], [1, 2])

    def test_no_symlinks_or_output_inside_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns('__pycache__'))
            (source / 'scripts/external.py').symlink_to('/etc/hosts')
            with self.assertRaisesRegex(ValueError, 'Symlinks'):
                package.build(source, Path(temp) / 'output', 'portable')
            with self.assertRaisesRegex(ValueError, 'outside'):
                package.build(SOURCE, SOURCE / 'dist', 'portable')


if __name__ == '__main__': unittest.main()
