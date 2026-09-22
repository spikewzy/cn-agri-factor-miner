#!/usr/bin/env python3
"""All external actions are file-based; the agent must not invent human decisions."""
import argparse
import json
from pathlib import Path
from pit import BlockedData, IntegrityError
from records import read_json, research_memory
from workflow import Run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('init'); q.add_argument('--inputs', required=True); q.add_argument('--history', nargs='*', default=[])
    q = sub.add_parser('propose'); q.add_argument('--spec', required=True)
    q = sub.add_parser('shortlist'); q.add_argument('ids', nargs='+')
    q = sub.add_parser('review'); q.add_argument('--decision', required=True)
    q = sub.add_parser('revise'); q.add_argument('--spec', required=True); q.add_argument('--reason', required=True)
    q = sub.add_parser('compute'); q.add_argument('factor_id')
    q = sub.add_parser('import-evaluation'); q.add_argument('factor_id'); q.add_argument('--result', required=True)
    q = sub.add_parser('packet'); q.add_argument('--stage', choices=['logic', 'acceptance'], default='logic')
    sub.add_parser('status')
    args = p.parse_args()
    run = Run(args.run)
    try:
        if args.command == 'init':
            root = Path(args.inputs)
            result = run.init(*[read_json(root / (name + '.json')) for name in
                ('manifest', 'predictors', 'existing_factors', 'human_corrections', 'data_dictionary')],
                history=research_memory(args.history))
        elif args.command == 'propose': result = run.propose(read_json(args.spec))
        elif args.command == 'shortlist': result = run.shortlist(args.ids)
        elif args.command == 'review': result = run.review(read_json(args.decision))
        elif args.command == 'revise': result = run.revise(read_json(args.spec), args.reason)
        elif args.command == 'compute': result = run.run(args.factor_id)
        elif args.command == 'import-evaluation': result = run.import_evaluation(args.factor_id, read_json(args.result))
        elif args.command == 'packet': result = {'packet': str(run.packet(stage=args.stage))}
        else: result = run.ledger.state()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (IntegrityError, BlockedData, KeyError, FileExistsError) as exc:
        print(json.dumps({'status': 'BLOCKED_DATA' if isinstance(exc, BlockedData) else 'ERROR',
                          'error': str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
