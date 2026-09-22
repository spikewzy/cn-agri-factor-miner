#!/usr/bin/env python3
"""Host-neutral capability check. No market data, network, approvals or secrets."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = ('SKILL.md', 'scripts/cli.py', 'scripts/pit.py', 'scripts/factors.py',
                  'scripts/records.py', 'scripts/workflow.py', 'scripts/adapter.py',
                  'scripts/demo.py', 'scripts/synthetic.py', 'templates/decision.json',
                  'templates/specification.json', 'examples/manifest.json',
                  'examples/predictors.json', 'examples/data_dictionary.json',
                  'examples/existing_factors.json', 'examples/human_corrections.json',
                  'references/agent-compatibility.md')


def inspect_environment(run_root, skill_root=ROOT):
    skill_root = Path(skill_root).expanduser().resolve()
    run_root = Path(run_root).expanduser().resolve()
    missing = []
    if sys.version_info < (3, 9):
        missing.append('python>=3.9')
    if os.name != 'posix' or importlib.util.find_spec('fcntl') is None:
        missing.append('POSIX_file_locking: use macOS/Linux or an accessible WSL Python environment')
    for name in REQUIRED_FILES:
        if not (skill_root / name).is_file():
            missing.append('bundled_file:' + name)
    if run_root == skill_root or skill_root in run_root.parents:
        missing.append('run_root_must_be_outside_skill_directory')
    if not missing:
        try:
            run_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=run_root) as f:
                f.write(b'capability-probe')
                f.flush()
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
        except OSError as exc:
            missing.append('writable_lockable_run_root:' + str(exc))
    return {'status': 'BLOCKED_ENVIRONMENT' if missing else 'READY', 'missing_capabilities': missing,
            'skill_dir': str(skill_root), 'run_root': str(run_root),
            'python': sys.version.split()[0], 'platform': sys.platform,
            'note': 'READY verifies this local runtime only; it does not verify host skill discovery, data, human approval, or evaluation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True)
    args = parser.parse_args()
    result = inspect_environment(args.run_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
