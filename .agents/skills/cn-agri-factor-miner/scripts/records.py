"""Append-only, hash-chained local records. Not an adversarial security boundary."""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
from pit import IntegrityError


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_once(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read(f):
        f.seek(0)
        events, prev = [], '0' * 64
        for line in f:
            try:
                event = json.loads(line)
                h = event.pop('hash')
                if event['prev'] != prev or event['seq'] != len(events) or digest(event) != h:
                    raise IntegrityError('Ledger hash chain invalid')
                event['hash'] = h
            except (KeyError, ValueError) as exc:
                raise IntegrityError('Corrupt/truncated ledger') from exc
            events.append(event)
            prev = h
        return events

    def events(self):
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            return self._read(f)

    def state(self):
        events = self.events()
        return copy.deepcopy(events[-1]['state']) if events else {}

    def mutate(self, action, payload, fn):
        with self.path.open('a+', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            events = self._read(f)
            state = copy.deepcopy(events[-1]['state']) if events else {}
            fn(state)
            event = {'seq': len(events), 'prev': events[-1]['hash'] if events else '0' * 64,
                     'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                     'action': action, 'payload': payload, 'state': state}
            event['hash'] = digest(event)
            f.seek(0, 2)
            f.write(canonical(event) + '\n')
            f.flush()
            os.fsync(f.fileno())
            return state


def research_memory(directories):
    """Read prior local run histories without erasing failed or rejected trials."""
    summaries = []
    for directory in directories:
        path = Path(directory).resolve() / 'experiments.jsonl'
        ledger = Ledger(path)
        events = ledger.events()
        if not events:
            raise IntegrityError('Requested research history is empty: ' + str(path))
        state = events[-1]['state']
        summaries.append({'source_ledger': str(path), 'source_hash': file_hash(path),
                          'commodity_group': state['manifest']['commodity_group'],
                          'proposed': state['proposed'], 'integrity_failures': state['integrity_failures'],
                          'observed_events': [{'action': e['action'], 'payload': e['payload'],
                                               'recorded_at': e['recorded_at']} for e in events],
                          'failure_explanations': 'Only explicit evidence/rationale in decisions; not inferred'})
    return summaries
