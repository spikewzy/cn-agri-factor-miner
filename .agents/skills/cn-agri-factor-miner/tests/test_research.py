import copy
import datetime as dt
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import adapter
from demo import demo, simulated_decision
from factors import compute, future_invariance, validate_expression
from pit import AsOf, BlockedData, IntegrityError, deduplicate_events, observable_labels, timestamp
from records import Ledger, digest, read_json, research_memory
from synthetic import fixture
from workflow import ROOT, Run, scope_matches


class PITTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.data, _, _, self.dictionary, self.specs = fixture()
        self.at = self.manifest['decisions'][0]['decision_at']
        self.fit = self.manifest['decisions'][0]['fit_cutoff']

    def test_latest_available_revision_keeps_old_vintage(self):
        store = AsOf(self.data)
        a = store.latest('meal_stock', self.dictionary['meal_stock'], self.at)
        b = store.latest('meal_stock', self.dictionary['meal_stock'], '2025-01-05T12:00:00+08:00')
        self.assertEqual(a['revision'], 0)
        self.assertEqual(b['revision'], 1)
        self.assertEqual(b['value'] - a['value'], 30)

    def test_future_target_forecast_allowed_but_realization_not(self):
        store = AsOf(self.data)
        forecast = store.latest('arrivals_14d', self.dictionary['arrivals_14d'], self.at)
        self.assertGreater(forecast['period_end'], '2025-01-03')
        later = copy.deepcopy(forecast)
        later.update(kind='realization', published_at='2025-01-20T08:00:00+08:00', available_at='2025-01-20T09:00:00+08:00')
        rows = AsOf(self.data + [later]).history('arrivals_14d', dict(self.dictionary['arrivals_14d'], kind='realization'), self.at)
        self.assertEqual(rows, [])

    def test_forecast_must_match_target_period(self):
        with self.assertRaises(BlockedData):
            AsOf(self.data).latest('arrivals_14d', self.dictionary['arrivals_14d'], '2025-01-05T12:00:00+08:00')

    def test_future_mutation_addition_removal_all_examples_fixed_seed(self):
        for spec in self.specs:
            self.assertTrue(future_invariance(spec, self.data, self.at, self.fit))

    def test_negative_control_catches_unrestricted_future_reads(self):
        def bad(spec, store, at, fit):
            return {'value': sum(r['value'] for r in store._AsOf__records)}
        with self.assertRaisesRegex(IntegrityError, 'LEAKAGE_TEST_FAILED'):
            future_invariance(self.specs[0], self.data, self.at, self.fit, bad)

    def test_seasonal_fit_cutoff_and_unique_releases(self):
        spec = self.specs[0]
        value = compute(spec, AsOf(self.data), self.at, self.fit)['value']
        self.assertEqual(value, compute(spec, AsOf(self.data + self.data), self.at, self.fit)['value'])
        # A later revision to a historical January is unavailable at the training cutoff.
        changed = copy.deepcopy(next(r for r in self.data if r['field'] == 'meal_stock' and r['period_end'] == '2023-01-02'))
        changed.update(revision=8, value=99999, published_at='2025-01-02T08:00:00+08:00', available_at='2025-01-02T09:00:00+08:00')
        self.assertEqual(value, compute(spec, AsOf(self.data + [changed]), self.at, self.fit)['value'])
        with self.assertRaisesRegex(BlockedData, 'seasonal_history_years'):
            compute(spec, AsOf(self.data), self.at, '2022-12-31T23:59:59+08:00')
        with self.assertRaises(IntegrityError):
            compute(spec, AsOf(self.data), self.at, '2026-01-01T00:00:00+08:00')

    def test_seasonal_does_not_count_monthly_forward_fills_as_years(self):
        data = [r for r in self.data if not r['period_end'].startswith('2022') and not r['period_end'].startswith('2023')]
        with self.assertRaisesRegex(BlockedData, 'seasonal_history_years'):
            compute(self.specs[0], AsOf(data), self.at, self.fit)

    def test_immature_labels_and_timezone_equivalence(self):
        labels = [{'value': 0.1, 'outcome_end': '2025-01-17T15:00:00+08:00', 'observable_at': '2025-01-17T15:05:00+08:00'}]
        self.assertEqual(observable_labels(labels, self.at), [])
        self.assertEqual(observable_labels(labels, '2025-01-17T07:04:59+00:00'), [])
        self.assertEqual(observable_labels(labels, '2025-01-17T07:05:00+00:00'), labels)
        labels[0]['observable_at'] = '2025-01-16T15:00:00+08:00'
        with self.assertRaises(IntegrityError): observable_labels(labels, self.at)

    def test_unknown_and_reconstructed_provenance_never_verified(self):
        for basis in ('unknown', 'reconstructed', 'synthetic'):
            data = [dict(r, availability_basis=basis) for r in self.data]
            self.assertFalse(compute(self.specs[1], AsOf(data), self.at, self.fit)['verified_pit'])
        observed = [dict(r, availability_basis='observed') for r in self.data]
        self.assertTrue(compute(self.specs[1], AsOf(observed), self.at, self.fit)['verified_pit'])

    def test_no_backfill_and_staleness(self):
        with self.assertRaises(BlockedData):
            AsOf(self.data).latest('meal_stock', self.dictionary['meal_stock'], '2021-01-01T00:00:00+08:00')
        with self.assertRaisesRegex(BlockedData, 'stale'):
            AsOf(self.data).latest('meal_stock', self.dictionary['meal_stock'], '2025-03-01T00:00:00+08:00')

    def test_time_units_numeric_and_vintage_integrity(self):
        for change in ({'published_at': '2025-01-03T08:00:00'}, {'value': float('nan')}, {'available_at': '2020-01-01T00:00:00+08:00'}):
            with self.assertRaises(IntegrityError): AsOf([dict(self.data[0], **change)])
        with self.assertRaises(IntegrityError): AsOf([self.data[0], dict(self.data[0], value=999)])
        with self.assertRaisesRegex(IntegrityError, 'Unit mismatch'):
            AsOf(self.data).latest('meal_stock', dict(self.dictionary['meal_stock'], unit='kg'), self.at)
        with self.assertRaisesRegex(BlockedData, 'published_at'):
            row = dict(self.data[0]); del row['published_at']; AsOf([row])

    def test_expression_allowlist_and_zero_denominator(self):
        for expression in ({'op': '__import__', 'args': []}, {'field': '__class__'},
                           {'op': 'change', 'args': [{'const': 1}], 'days': -1}, {'const': '1+1'}):
            with self.assertRaises(IntegrityError): validate_expression(expression, self.dictionary)
        spec = copy.deepcopy(self.specs[1]); spec['formula'] = {'op': 'div', 'args': [{'const': 1}, {'const': 0}]}
        with self.assertRaisesRegex(BlockedData, 'zero_denominator'): compute(spec, AsOf(self.data), self.at, self.fit)

    def test_text_event_dedup_and_provenance(self):
        row = dict(self.data[0]); repost = dict(row, source='REPOST', published_at='2026-01-01T00:00:00+08:00')
        self.assertEqual(len(deduplicate_events([repost, row])), 1)
        revised = dict(row, revision=1, value=row['value'] + 1)
        self.assertEqual(len(deduplicate_events([row, revised])), 2)
        with self.assertRaises(IntegrityError): deduplicate_events([row, dict(row, value=9999)])
        with self.assertRaisesRegex(BlockedData, 'source_excerpt'): AsOf([dict(row, text_derived=True)])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest, self.data, self.catalog, self.corrections, self.dictionary, self.specs = fixture()
        self.run = Run(self.root / 'run')
        self.run.init(self.manifest, self.data, self.catalog, self.corrections, self.dictionary)

    def tearDown(self): self.temp.cleanup()

    def ready(self, index=1):
        spec = self.specs[index]
        self.run.propose(spec); self.run.shortlist([spec['id']]); self.run.review(simulated_decision(spec))
        return spec

    def test_normal_not_evaluated_and_frozen_exports(self):
        spec = self.ready()
        result = self.run.run(spec['id'])
        self.assertEqual(result['status'], 'NOT_EVALUATED')
        self.assertNotIn('ic', result)
        panel = read_json(Path(result['artifact']) / 'factor-panel.json')
        self.assertEqual(len(panel), 3)
        self.assertTrue(all(timestamp(r['execution_at']) > timestamp(r['decision_at']) for r in panel))
        req = read_json(Path(result['artifact']) / 'evaluation-request.json')
        self.assertEqual(req['specification'], spec)
        self.assertTrue(req['requirements']['fit_inside_each_training_split'])

    def test_missing_all_fields_exact_block(self):
        empty = Run(self.root / 'empty'); empty.init(self.manifest, [], self.catalog, [], self.dictionary)
        spec = self.specs[1]; empty.propose(spec); empty.shortlist([spec['id']]); empty.review(simulated_decision(spec))
        result = empty.run(spec['id'])
        self.assertEqual(result['status'], 'BLOCKED_DATA')
        for field in spec['input_fields']:
            self.assertTrue(any(field + ':eligible_vintage' in x for x in result['missing_fields']))

    def test_pause_revise_resume_and_old_hash_invalidated(self):
        spec = self.specs[1]; self.run.propose(spec); self.run.shortlist([spec['id']])
        self.assertEqual(self.run.run(spec['id'])['status'], 'PAUSED_REVIEW')
        self.run.review(simulated_decision(spec, 'REVISE'))
        revised = copy.deepcopy(spec); revised['version'] = 2; revised['parameters']['reviewed'] = True
        self.run.revise(revised, 'performance-driven human revision must count')
        with self.assertRaisesRegex(IntegrityError, 'mismatch'): self.run.review(simulated_decision(spec))
        reopened = Run(self.root / 'run')
        self.assertIsNone(reopened.ledger.state()['proposed'][spec['id']]['approval'])
        reopened.review(simulated_decision(revised))
        self.assertEqual(reopened.run(spec['id'])['status'], 'NOT_EVALUATED')
        self.assertEqual(len(reopened.ledger.state()['proposed'][spec['id']]['versions']), 2)

    def test_budget_proposals_includes_rejections(self):
        for i in range(6):
            spec = copy.deepcopy(self.specs[1]); spec['id'] = 'h' + str(i)
            self.run.propose(spec); self.run.review(simulated_decision(spec, 'REJECT'))
        spec['id'] = 'h7'
        with self.assertRaisesRegex(IntegrityError, 'BUDGET_EXHAUSTED'): self.run.propose(spec)
        self.assertEqual(len(self.run.ledger.state()['proposed']), 6)

    def test_shortlist_cap_cannot_be_recycled(self):
        for i in range(4):
            spec = copy.deepcopy(self.specs[1]); spec['id'] = 'h' + str(i)
            self.run.propose(spec)
        self.run.shortlist(['h0', 'h1', 'h2'])
        spec['id'] = 'h0'; self.run.review(simulated_decision(spec, 'REJECT'))
        with self.assertRaisesRegex(IntegrityError, 'BUDGET_EXHAUSTED'): self.run.shortlist(['h3'])

    def test_revision_budget_original_plus_two(self):
        spec = self.ready()
        for version in (2, 3):
            self.run.review(simulated_decision(spec, 'REVISE'))
            spec = copy.deepcopy(spec); spec['version'] = version
            self.run.revise(spec, 'explicit human parameter revision')
            self.run.review(simulated_decision(spec))
        self.run.review(simulated_decision(spec, 'REVISE'))
        spec = copy.deepcopy(spec); spec['version'] = 4
        with self.assertRaisesRegex(IntegrityError, 'BUDGET_EXHAUSTED'): self.run.revise(spec, 'fourth attempt')

    def test_request_evidence_and_merge_preserve_histories(self):
        for spec in self.specs[:2]: self.run.propose(spec)
        self.run.shortlist([s['id'] for s in self.specs[:2]])
        self.run.review(simulated_decision(self.specs[0], 'REQUEST_EVIDENCE'))
        self.assertEqual(self.run.run(self.specs[0]['id'])['status'], 'PAUSED_REVIEW')
        decision = simulated_decision(self.specs[0], 'MERGE'); decision['merge_into'] = self.specs[1]['id']
        self.run.review(decision)
        state = self.run.ledger.state()
        self.assertEqual(state['proposed'][self.specs[0]['id']]['status'], 'MERGED')
        self.assertEqual(state['proposed'][self.specs[1]['id']]['status'], 'REVISION_REQUESTED')
        self.assertEqual(len(state['proposed']), 2)

    def test_integrity_failure_cannot_be_human_overridden(self):
        spec = self.ready(); self.run.fail_integrity('LEAKAGE_TEST_FAILED: test injection')
        self.assertEqual(self.run.run(spec['id'])['status'], 'BLOCKED_INTEGRITY')
        self.run.review(simulated_decision(spec, 'REVISE'))
        revised = copy.deepcopy(spec); revised['version'] = 2; self.run.revise(revised, 'does not erase failure')
        with self.assertRaisesRegex(IntegrityError, 'cannot override'): self.run.review(simulated_decision(revised))

    def test_merge_cannot_revive_rejected_or_unshortlisted_target(self):
        for spec in self.specs[:2]: self.run.propose(spec)
        self.run.shortlist([self.specs[0]['id']])
        decision = simulated_decision(self.specs[0], 'MERGE'); decision['merge_into'] = self.specs[1]['id']
        with self.assertRaisesRegex(IntegrityError, 'active shortlisted'): self.run.review(decision)
        self.run.shortlist([self.specs[1]['id']])
        self.run.review(simulated_decision(self.specs[1], 'REJECT'))
        with self.assertRaisesRegex(IntegrityError, 'active shortlisted'): self.run.review(decision)
        self.assertEqual(self.run.ledger.state()['proposed'][self.specs[1]['id']]['status'], 'REJECTED')

    def test_frozen_inputs_tamper_and_ledger_tamper(self):
        spec = self.ready()
        (self.run.path / 'inputs/predictors.json').write_text('[]')
        self.assertEqual(self.run.run(spec['id'])['status'], 'BLOCKED_INTEGRITY')
        ledger = self.run.path / 'experiments.jsonl'
        text = ledger.read_text(); ledger.write_text(text.replace('PROPOSE', 'CHANGED', 1))
        with self.assertRaises(IntegrityError): self.run.ledger.events()

    def test_acceptance_needs_evaluation_human_and_real_pit(self):
        spec = self.ready(); self.run.run(spec['id'])
        d = simulated_decision(spec); d['stage'] = 'acceptance'
        with self.assertRaisesRegex(IntegrityError, 'Acceptance blocked'): self.run.review(d)
        with self.assertRaises(IntegrityError): self.run.review(dict(d, origin='agent'))
        self.assertFalse((self.run.path / 'approved_research').exists())

    def test_real_metadata_block(self):
        manifest = copy.deepcopy(self.manifest); manifest['synthetic'] = False
        run = Run(self.root / 'real'); run.init(manifest, self.data, self.catalog, [], self.dictionary)
        spec = self.specs[1]; run.propose(spec); run.shortlist([spec['id']])
        with self.assertRaises(IntegrityError): run.review(simulated_decision(spec))
        # Test fixture for user-origin record, never an actual approval.
        d = dict(simulated_decision(spec), origin='human', reviewer='UNIT_TEST_HUMAN_RECORD')
        run.review(d)
        result = run.run(spec['id'])
        self.assertEqual(result['status'], 'BLOCKED_DATA')
        self.assertIn('soybean_meal.metadata.verification_status', result['missing_fields'])

    def test_scope_agricultural_configurable_and_nonag_rejected(self):
        registry = self.manifest['registry']
        self.assertTrue(scope_matches(['soybean_meal', 'soybean_oil'], registry))
        for ids in (['gold'], ['copper'], ['crude_oil'], ['bitcoin'], ['equities'], ['soybean_meal', 'iron_ore']):
            self.assertFalse(scope_matches(ids, registry))
        custom = {'cotton': {'market': 'CN_FUTURES', 'family': 'cotton'}}
        self.assertTrue(scope_matches(['cotton'], custom))
        self.assertFalse(scope_matches(['wheat'], {'wheat': {'market': 'US_FUTURES', 'family': 'grains'}}))

    def test_horizon_and_execution_changes_blocked(self):
        spec = copy.deepcopy(self.specs[1]); spec['horizon'] = 7
        with self.assertRaises(IntegrityError): self.run.propose(spec)
        manifest = copy.deepcopy(self.manifest); manifest['decisions'][0]['execution_at'] = manifest['decisions'][0]['decision_at']
        with self.assertRaises(IntegrityError): Run(self.root / 'samebar').init(manifest, self.data, self.catalog, [], self.dictionary)
        with self.assertRaises(IntegrityError): Run(ROOT / 'bad-run')

    def test_final_holdout_inputs_and_import_rejected(self):
        manifest = copy.deepcopy(self.manifest); manifest['input_scope'] = 'final_holdout'
        with self.assertRaises(IntegrityError): Run(self.root / 'holdout').init(manifest, self.data, self.catalog, [], self.dictionary)
        plan = copy.deepcopy(self.manifest['evaluation_plan']); plan['holdout_policy'] = 'agent_can_read'
        with self.assertRaises(IntegrityError): adapter.validate_plan(plan)

    def test_adapter_rejects_mismatch_failures_holdout_and_tampered_exports(self):
        spec = self.ready(); result = self.run.run(spec['id'])
        req = read_json(Path(result['artifact']) / 'evaluation-request.json')
        response = {'request_hash': req['request_hash'], 'status': 'EVALUATED', 'assessment_scope': 'development_only',
            'evaluator_id': 'TEST_DOUBLE', 'evaluator_version': 'test-v1', 'evaluated_at': '2026-09-21T00:00:00+00:00',
            'integrity_checks': {k: True for k in ('point_in_time', 'observable_labels', 'training_only_fits', 'real_contract_labels', 'overlap_handled')},
            'diagnostics': {k: {'status': 'INSUFFICIENT_DATA', 'evidence': 'TEST DOUBLE ONLY; no actual performance'} for k in adapter.DIAGNOSTICS}}
        self.assertEqual(adapter.import_result(response, req), response)
        with self.assertRaises(IntegrityError): adapter.import_result(dict(response, request_hash='wrong'), req)
        with self.assertRaises(IntegrityError): adapter.import_result(dict(response, assessment_scope='final_holdout'), req)
        bad = copy.deepcopy(response); bad['integrity_checks']['point_in_time'] = False
        with self.assertRaises(IntegrityError): adapter.import_result(bad, req)
        with self.assertRaises(IntegrityError): adapter.import_result(dict(response, trading_performance={'return': 1}), req)
        (Path(result['artifact']) / 'factor-panel.json').write_text('[]')
        with self.assertRaisesRegex(IntegrityError, 'modified'): self.run.import_evaluation(spec['id'], response)
        self.assertTrue(self.run.ledger.state()['integrity_failures'])

    def test_end_to_end_demo_reopens_version_history(self):
        report = demo(self.root / 'demo')
        self.assertEqual(report['version_history'], [1, 2])
        self.assertEqual(report['initial_pause']['status'], 'PAUSED_REVIEW')
        self.assertEqual(report['resumed_v2']['status'], 'NOT_EVALUATED')
        self.assertIn('LEAKAGE_TEST_FAILED', report['leakage_failure'])

    def test_prior_research_memory_retains_rejections_and_corrections(self):
        spec = self.ready()
        self.run.review(simulated_decision(spec, 'REJECT'))
        history = research_memory([self.run.path])
        self.assertEqual(history[0]['proposed'][spec['id']]['status'], 'REJECTED')
        self.assertEqual(history[0]['proposed'][spec['id']]['reviews'][-1]['action'], 'REJECT')
        follow = Run(self.root / 'follow')
        follow.init(self.manifest, self.data, self.catalog, [], self.dictionary, history=history)
        self.assertEqual(read_json(follow.path / 'inputs/research_memory.json'), history)
        self.assertIn('research_memory.json', follow.ledger.state()['hashes'])

    def test_cli_initialize_propose_shortlist_pause(self):
        import subprocess
        command = [sys.executable, str(ROOT / 'scripts/cli.py'), '--run', str(self.root / 'cli')]
        for args in (['init', '--inputs', str(ROOT / 'examples')],
                     ['propose', '--spec', str(ROOT / 'examples/spec-inventory_coverage.json')],
                     ['shortlist', 'inventory_coverage']):
            proc = subprocess.run(command + args, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            json.loads(proc.stdout)
        proc = subprocess.run(command + ['compute', 'inventory_coverage'], capture_output=True, text=True)
        self.assertEqual(json.loads(proc.stdout)['status'], 'PAUSED_REVIEW')

    def test_external_development_import_and_acceptance_packet(self):
        spec = self.ready(); result = self.run.run(spec['id'])
        response = {'request_hash': result['request_hash'], 'status': 'EVALUATED', 'assessment_scope': 'development_only',
            'evaluator_id': 'SYNTHETIC_TEST_DOUBLE', 'evaluator_version': 'test-v1', 'evaluated_at': '2026-09-21T00:00:00+00:00',
            'integrity_checks': {k: True for k in ('point_in_time', 'observable_labels', 'training_only_fits', 'real_contract_labels', 'overlap_handled')},
            'diagnostics': {k: {'status': 'INSUFFICIENT_DATA', 'evidence': 'Synthetic protocol test only; no real evaluation'} for k in adapter.DIAGNOSTICS}}
        state = self.run.import_evaluation(spec['id'], response)
        self.assertEqual(state['proposed'][spec['id']]['status'], 'EVALUATED')
        self.assertEqual(len(list(self.run.path.glob('review-*-acceptance.md'))), 1)
        decision = dict(simulated_decision(spec), stage='acceptance')
        with self.assertRaises(IntegrityError): self.run.review(decision)


if __name__ == '__main__': unittest.main()
