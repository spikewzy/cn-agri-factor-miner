#!/usr/bin/env python3
"""Synthetic workflow test: approvals are SIMULATED, never human authorization."""
import argparse
import copy
from pathlib import Path
from factors import future_invariance
from pit import IntegrityError
from records import digest, write_once
from synthetic import fixture
from workflow import Run


def simulated_decision(spec, action='APPROVE'):
    return {'action': action, 'stage': 'specification', 'factor_id': spec['id'], 'spec_hash': digest(spec),
            'scope': spec['commodity_group'], 'rationale': 'SIMULATED TEST ONLY: validate workflow state transitions',
            'evidence': ['synthetic-fixture-v1'], 'reviewer': 'SIMULATED_TEST_ACTOR',
            'timestamp': '2026-09-21T00:00:00+00:00', 'version': spec['version'], 'origin': 'simulated_test'}


def demo(directory):
    directory = Path(directory)
    manifest, records, catalog, corrections, dictionary, specs = fixture()
    normal = Run(directory / 'normal')
    normal.init(manifest, records, catalog, corrections, dictionary)
    for spec in specs: normal.propose(spec)
    normal.shortlist([s['id'] for s in specs])
    paused = normal.run(specs[0]['id'])
    results = []
    for spec in specs:
        normal.review(simulated_decision(spec))
        results.append(normal.run(spec['id']))
    # A review request and a substantive parameter revision invalidate the old approval.
    original = specs[0]
    normal.review(simulated_decision(original, 'REVISE'))
    revised = copy.deepcopy(original)
    revised['version'] = 2
    revised['formula']['args'][0]['min_years'] = 3
    revised['parameters']['min_years'] = 3
    normal.revise(revised, 'SIMULATED human revision: require 3 historical years; consumes specification budget')
    revision_pause = normal.run(revised['id'])
    # Reopen from disk to demonstrate recovery without in-memory state.
    resumed = Run(directory / 'normal')
    resumed.review(simulated_decision(revised))
    resumed_result = resumed.run(revised['id'])
    missing = Run(directory / 'missing-data')
    missing.init(manifest, [r for r in records if r['field'] != 'arrivals_14d'], catalog, corrections, dictionary)
    missing.propose(specs[1]); missing.shortlist([specs[1]['id']]); missing.review(simulated_decision(specs[1]))
    blocked = missing.run(specs[1]['id'])
    leakage = Run(directory / 'leakage-failure')
    leakage.init(manifest, records, catalog, corrections, dictionary)
    leakage.propose(specs[1]); leakage.shortlist([specs[1]['id']])
    # Deliberately unsafe TEST DOUBLE accesses private storage; production expressions cannot do so.
    def unsafe_computer(spec, store, at, fit_cutoff):
        return {'value': sum(r['value'] for r in store._AsOf__records)}
    try:
        future_invariance(specs[1], records, manifest['decisions'][0]['decision_at'],
                          manifest['decisions'][0]['fit_cutoff'], computer=unsafe_computer)
        raise AssertionError('Leakage fixture should have failed')
    except IntegrityError as exc:
        leakage.fail_integrity(str(exc))
    try:
        leakage.review(simulated_decision(specs[1]))
        raise AssertionError('Integrity failure must prevent approval')
    except IntegrityError:
        leakage_status = 'LEAKAGE_TEST_FAILED; approval remains blocked'
    report = {'synthetic_only': True, 'human_approvals': 'SIMULATED ONLY; none supplied or inferred',
              'initial_pause': paused, 'normal': results, 'revision_pause': revision_pause,
              'resumed_v2': resumed_result, 'missing_data': blocked, 'leakage_failure': leakage_status,
              'version_history': [v['version'] for v in resumed.ledger.state()['proposed'][original['id']]['versions']],
              'approved_research_library': 'EMPTY; no evaluated real factors and no human acceptance'}
    assert all(r['status'] == 'NOT_EVALUATED' for r in results), results
    assert resumed_result['status'] == 'NOT_EVALUATED', resumed_result
    assert blocked['status'] == 'BLOCKED_DATA', blocked
    write_once(directory / 'demo-report.json', report)
    return report


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(json.dumps(demo(parser.parse_args().output), ensure_ascii=False, indent=2))
