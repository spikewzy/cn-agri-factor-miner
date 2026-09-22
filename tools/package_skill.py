#!/usr/bin/env python3
"""Build deterministic, flat-root skill ZIPs from one canonical implementation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

VERSION = '0.2.0'
NAME = 'cn-agri-factor-miner'
REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / '.agents/skills' / NAME
RESOURCE_DIRS = {'scripts', 'references', 'templates', 'examples', 'tests', 'agents'}
ROOT_FILES = {'SKILL.md', 'README.md'}


def workbuddy_header(text):
    if not text.startswith('---\n'):
        raise ValueError('SKILL.md must begin with YAML frontmatter')
    _, header, body = text.split('---', 2)
    def scalar(key):
        match = re.search(r'^' + key + r': (.+)$', header, re.MULTILINE)
        if not match:
            raise ValueError('Missing skill metadata: ' + key)
        return match.group(1).strip()
    if scalar('name') != NAME:
        raise ValueError('Unexpected skill name')
    description = scalar('description')
    fields = {'name': NAME, 'display_name': '中国农业基本面因子研究',
              'description': description,
              'description_zh': '研究中国农业期货基本面因子：时点数据、有限假设、安全计算、外部评估与人工审核。不用于非农业期货、股票估值或自动交易。',
              'description_en': description, 'version': VERSION, 'author': 'spikewzy'}
    return '---\n' + ''.join(k + ': ' + json.dumps(v, ensure_ascii=False) + '\n' for k, v in fields.items()) + '---' + body


def build(source, output, target):
    source, output = Path(source).resolve(), Path(output).resolve()
    if target not in ('portable', 'workbuddy'):
        raise ValueError('Unknown target')
    if output == source or source in output.parents:
        raise ValueError('Build output must be outside the skill directory')
    entries = {}
    for path in sorted(source.rglob('*')):
        rel = path.relative_to(source)
        if path.is_symlink():
            raise ValueError('Symlinks are not included in published skills: ' + str(rel))
        if not path.is_file() or any(part.startswith('.') or part == '__pycache__' for part in rel.parts) or path.suffix == '.pyc':
            continue
        if rel.as_posix() not in ROOT_FILES and rel.parts[0] not in RESOURCE_DIRS:
            continue
        # Codex UI hints are not required by the WorkBuddy importer.
        if target == 'workbuddy' and rel.parts[0] == 'agents':
            continue
        data = path.read_bytes()
        if target == 'workbuddy' and rel.as_posix() == 'SKILL.md':
            data = workbuddy_header(data.decode('utf-8')).encode('utf-8')
        entries[rel.as_posix()] = data
    for required in ('SKILL.md', 'README.md', 'scripts/cli.py', 'scripts/doctor.py', 'references/agent-compatibility.md'):
        if required not in entries:
            raise ValueError('Missing packaged resource: ' + required)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (NAME + '-' + target + '-v' + VERSION + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    manifest = {'name': NAME, 'version': VERSION, 'target': target, 'archive': archive.name,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'files': {n: hashlib.sha256(data).hexdigest() for n, data in entries.items()}}
    (output / (archive.stem + '.manifest.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=REPO / 'dist')
    parser.add_argument('--target', choices=['portable', 'workbuddy', 'all'], default='all')
    args = parser.parse_args()
    targets = ['portable', 'workbuddy'] if args.target == 'all' else [args.target]
    print(json.dumps([build(args.source, args.output, t) for t in targets], ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
