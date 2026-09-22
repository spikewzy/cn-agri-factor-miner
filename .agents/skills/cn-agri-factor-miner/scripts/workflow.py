"""Bounded factor-research state machine and reproducible file artifacts."""
import copy
import datetime as dt
import json
from pathlib import Path
import adapter
from factors import compute, future_invariance, validate_expression
from pit import AsOf, BlockedData, IntegrityError, timestamp
from records import Ledger, canonical, digest, file_hash, read_json, write_once

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('id', 'version', 'commodity_group', 'economic_family', 'hypothesis', 'mechanism',
 'counterexample', 'evidence', 'expected_direction', 'target', 'horizon', 'input_fields', 'units',
 'availability_rules', 'formula', 'parameters', 'normalization', 'missing_stale_policy',
 'failure_conditions', 'closest_existing_factors', 'incremental_information', 'physical_test', 'price_derived')
FAMILIES = {'oilseeds', 'grains', 'livestock', 'eggs', 'fruit', 'sugar', 'cotton'}
ACTIONS = {'APPROVE', 'REVISE', 'REJECT', 'MERGE', 'REQUEST_EVIDENCE'}


def scope_matches(commodity_ids, registry):
    return bool(commodity_ids) and all(c in registry and registry[c].get('family') in FAMILIES
                                      and registry[c].get('market') == 'CN_FUTURES' for c in commodity_ids)


def validate_spec(spec, manifest):
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise IntegrityError('Incomplete specification: ' + ','.join(missing))
    if not spec['id'].replace('_', '').replace('-', '').isalnum() or type(spec['version']) is not int:
        raise IntegrityError('Invalid id/version')
    if spec['commodity_group'] != manifest['commodity_group'] or spec['horizon'] != manifest['evaluation_plan']['horizon_days']:
        raise IntegrityError('Group/horizon differs from frozen batch')
    if not spec['mechanism'] or not spec['counterexample'] or not spec['evidence']:
        raise IntegrityError('Mechanism, counterexample and evidence required')
    for field, rule in spec['input_fields'].items():
        for key in ('source', 'unit', 'kind', 'max_release_age_days', 'max_observation_age_days'):
            if key not in rule:
                raise IntegrityError('Missing input rule: ' + field + '.' + key)
        if rule['max_release_age_days'] < 0 or rule['max_observation_age_days'] < 0:
            raise IntegrityError('Negative freshness limit')
    validate_expression(spec['formula'], spec['input_fields'])


def code_hash():
    return digest({str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / 'scripts').glob('*.py'))})


class Run:
    def __init__(self, directory):
        self.path = Path(directory).resolve()
        if self.path == ROOT or ROOT in self.path.parents:
            raise IntegrityError('Run artifacts must be outside skill definition')
        self.ledger = Ledger(self.path / 'experiments.jsonl')

    def init(self, manifest, records, catalog, corrections, dictionary, history=None):
        if self.ledger.events():
            raise IntegrityError('Run already exists; choose a fresh directory')
        if not scope_matches(manifest['commodity_group']['members'], manifest['registry']):
            raise IntegrityError('OUT_OF_SCOPE: Chinese agricultural futures only')
        if len(manifest['commodity_group']['members']) > 1 and not manifest['commodity_group'].get('linkage'):
            raise IntegrityError('Multiple products need an explicit economic linkage')
        adapter.validate_plan(manifest['evaluation_plan'])
        if manifest.get('input_scope') != 'development_only':
            raise IntegrityError('Only development inputs are permitted')
        if not manifest.get('discovery_audit') or not manifest.get('model_prompt_versions'):
            raise IntegrityError('Record pre-idea discovery and model/prompt provenance')
        # Init can record a data gap; malformed supplied records are never silently repaired.
        AsOf(records)
        snapshots = {'manifest.json': manifest, 'predictors.json': records, 'existing_factors.json': catalog,
                     'human_corrections.json': corrections, 'data_dictionary.json': dictionary,
                     'research_memory.json': history or []}
        for name, value in snapshots.items():
            write_once(self.path / 'inputs' / name, value)
        hashes = {name: file_hash(self.path / 'inputs' / name) for name in snapshots}
        for row in manifest['decisions']:
            t, execution, fit = [timestamp(row[k]) for k in ('decision_at', 'execution_at', 'fit_cutoff')]
            if not fit < t < execution:
                raise IntegrityError('Require fitting before decision and execution after signal')
            if not row.get('trading_date') or not row.get('calendar_source'):
                raise IntegrityError('Explicit trading-date mapping and calendar source required')
            splits = manifest['evaluation_plan']['splits']
            if not any(timestamp(s['test_start']) <= t <= timestamp(s['test_end']) and fit == timestamp(s['train_end']) for s in splits):
                raise IntegrityError('Decision/fit cutoff is outside frozen walk-forward split')
        def start(s):
            s.update(manifest=manifest, hashes=hashes, code_hash=code_hash(), proposed={}, shortlist=[],
                     integrity_failures=[], limits={'hypotheses': 6, 'shortlist': 3, 'specifications': 3})
        state = self.ledger.mutate('INIT', {'discovery_audit': manifest['discovery_audit'],
            'consulted_catalog_hash': digest(catalog), 'consulted_corrections_hash': digest(corrections)}, start)
        write_once(self.path / 'data-availability.json', self.availability(state, records, dictionary))
        return state

    def availability(self, state, records, dictionary):
        out = []
        store = AsOf(records)
        first = state['manifest']['decisions'][0]['decision_at']
        for field, rule in dictionary.items():
            rows = [r for r in records if r['field'] == field]
            entry = {'field': field, 'records': len(rows), 'unit': rule['unit']}
            try:
                store.latest(field, rule, first)
                entry['status'] = 'usable' if rows and all(r['availability_basis'] == 'observed' for r in rows) else 'lacking_historical_publication_vintage'
            except BlockedData as exc:
                entry.update(status='stale' if any('stale' in x for x in exc.fields) else 'missing', missing_fields=exc.fields)
            out.append(entry)
        return {'as_of': first, 'synthetic': state['manifest']['synthetic'], 'fields': out,
                'note': 'Synthetic/reconstructed/unknown timestamps do not verify real historical PIT performance.'}

    def check_inputs(self, state):
        for name, expected in state['hashes'].items():
            if file_hash(self.path / 'inputs' / name) != expected:
                raise IntegrityError('Frozen input modified: ' + name)
        if code_hash() != state['code_hash']:
            raise IntegrityError('Code changed; start a new linked run and re-review')

    def propose(self, spec):
        def update(s):
            self.check_inputs(s)
            validate_spec(spec, s['manifest'])
            if spec['id'] in s['proposed'] or spec['version'] != 1:
                raise IntegrityError('New hypotheses require unique ids and version 1')
            if len(s['proposed']) >= s['limits']['hypotheses']:
                raise IntegrityError('BUDGET_EXHAUSTED: request explicit expansion approval')
            s['proposed'][spec['id']] = {'versions': [spec], 'status': 'PROPOSED', 'approval': None, 'evaluations': []}
        return self.ledger.mutate('PROPOSE', {'spec': spec}, update)

    def shortlist(self, ids):
        def update(s):
            self.check_inputs(s)
            union = set(s['shortlist']) | set(ids)
            if len(union) > s['limits']['shortlist']:
                raise IntegrityError('BUDGET_EXHAUSTED: shortlist cap includes previously rejected candidates')
            for ident in ids:
                item = s['proposed'][ident]
                if item['status'] != 'PROPOSED':
                    raise IntegrityError('Only new proposals can be shortlisted')
                item['status'] = 'AWAITING_SPEC_REVIEW'
            s['shortlist'] = sorted(union)
        state = self.ledger.mutate('SHORTLIST', {'ids': ids}, update)
        self.packet(state, 'logic')
        return state

    def packet(self, state=None, stage='logic'):
        state = state or self.ledger.state()
        index = len(self.ledger.events())
        lines = ['# Human review — ' + stage, '', 'Acceptance is for further research/shadow testing only.',
                 'All examples are unvalidated. Logic packet deliberately excludes performance.', '']
        for ident in state['shortlist']:
            item = state['proposed'][ident]
            spec = item['versions'][-1]
            lines.extend(['## ' + ident + ' v' + str(spec['version']), '', 'Status: ' + item['status'],
                          'Specification SHA-256: ' + digest(spec), '', '```json',
                          json.dumps(spec, ensure_ascii=False, indent=2), '```', ''])
            if stage == 'acceptance':
                lines.extend(['Validation:', '```json', json.dumps(item.get('latest_result', {'status': 'NOT_EVALUATED'}), ensure_ascii=False, indent=2), '```', ''])
        lines.extend(['Consult inputs/human_corrections.json, inputs/existing_factors.json, data-availability.json and experiments.jsonl.',
                      'Submit a decision file bound to this hash; only the human supplies approval.',
                      'REVISE and REQUEST_EVIDENCE pause computation. MERGE preserves both histories.'])
        path = self.path / ('review-%03d-%s.md' % (index, stage))
        with path.open('x', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def review(self, decision):
        required = ('action', 'stage', 'factor_id', 'spec_hash', 'scope', 'rationale', 'evidence',
                    'reviewer', 'timestamp', 'version', 'origin')
        if any(not decision.get(k) for k in required) or decision['action'] not in ACTIONS:
            raise IntegrityError('Complete explicit decision record required')
        timestamp(decision['timestamp'])
        if decision['stage'] not in ('specification', 'acceptance'):
            raise IntegrityError('Invalid review stage')
        def update(s):
            self.check_inputs(s)
            if decision['origin'] != 'human' and not (s['manifest']['synthetic'] and decision['origin'] == 'simulated_test'):
                raise IntegrityError('Only explicit human decisions may approve real research')
            item = s['proposed'][decision['factor_id']]
            spec = item['versions'][-1]
            if decision['spec_hash'] != digest(spec) or decision['version'] != spec['version'] or decision['scope'] != spec['commodity_group']:
                raise IntegrityError('Review scope/version/hash mismatch')
            if item['status'] in ('REJECTED', 'MERGED', 'ACCEPTED_RESEARCH'):
                raise IntegrityError('Terminal candidate; preserve history in a new linked batch')
            action = decision['action']
            if action == 'APPROVE':
                if decision['factor_id'] not in s['shortlist']:
                    raise IntegrityError('Approval requires shortlisting')
                if s['integrity_failures']:
                    raise IntegrityError('Humans cannot override integrity failures')
                if decision['stage'] == 'acceptance':
                    result = item.get('latest_result', {})
                    if s['manifest']['synthetic'] or not item.get('verified_pit') or result.get('status') != 'EVALUATED':
                        raise IntegrityError('Acceptance blocked: synthetic, unverified PIT, or NOT_EVALUATED')
                    if item['status'] != 'EVALUATED' or any(v['status'] != 'PASS' for v in result['diagnostics'].values()):
                        raise IntegrityError('Acceptance requires complete passing evaluation and current version')
                    item['status'] = 'ACCEPTED_RESEARCH'
                else:
                    if item['status'] != 'AWAITING_SPEC_REVIEW':
                        raise IntegrityError('Review requires a pending current specification')
                    item.update(status='SPEC_APPROVED', approval=decision)
            elif action == 'REJECT':
                item.update(status='REJECTED', approval=None)
            elif action == 'MERGE':
                target = decision.get('merge_into')
                if target not in s['proposed'] or target == decision['factor_id']:
                    raise IntegrityError('MERGE requires a distinct existing target')
                if target not in s['shortlist'] or s['proposed'][target]['status'] in ('REJECTED', 'MERGED', 'ACCEPTED_RESEARCH'):
                    raise IntegrityError('MERGE target must be an active shortlisted candidate')
                item.update(status='MERGED', approval=None, merge_into=target)
                # Combining information changes the surviving candidate and requires revision.
                s['proposed'][target].update(status='REVISION_REQUESTED', approval=None)
            else:
                item.update(status='REVISION_REQUESTED' if action == 'REVISE' else 'EVIDENCE_REQUESTED', approval=None)
            item.setdefault('reviews', []).append(decision)
        state = self.ledger.mutate('HUMAN_REVIEW', decision, update)
        if decision['stage'] == 'acceptance' and decision['action'] == 'APPROVE':
            write_once(self.path / 'approved_research' / (decision['factor_id'] + '.json'),
                       {'specification': state['proposed'][decision['factor_id']]['versions'][-1], 'human_decision': decision,
                        'purpose': 'research_and_prospective_shadow_only', 'trading_authorized': False})
        return state

    def revise(self, spec, reason):
        if not reason:
            raise IntegrityError('Revision rationale is required')
        def update(s):
            self.check_inputs(s)
            validate_spec(spec, s['manifest'])
            item = s['proposed'][spec['id']]
            if item['status'] not in ('REVISION_REQUESTED', 'EVIDENCE_REQUESTED'):
                raise IntegrityError('Explicit REVISE or REQUEST_EVIDENCE needed before amendment')
            if len(item['versions']) >= s['limits']['specifications']:
                raise IntegrityError('BUDGET_EXHAUSTED: original plus two revisions')
            if spec['version'] != item['versions'][-1]['version'] + 1:
                raise IntegrityError('Versions must be consecutive')
            item['versions'].append(spec)
            item.update(status='AWAITING_SPEC_REVIEW', approval=None, latest_result=None, verified_pit=False)
        state = self.ledger.mutate('REVISE_SPEC', {'spec': spec, 'reason': reason}, update)
        self.packet(state)
        return state

    def fail_integrity(self, message):
        return self.ledger.mutate('INTEGRITY_FAILURE', {'observed_failure': message, 'explanation': 'not inferred'},
            lambda s: s['integrity_failures'].append(message))

    def run(self, ident):
        state = self.ledger.state()
        item = state['proposed'][ident]
        if item['status'] != 'SPEC_APPROVED' or not item['approval']:
            return {'status': 'PAUSED_REVIEW', 'factor_id': ident}
        if state['integrity_failures']:
            return {'status': 'BLOCKED_INTEGRITY', 'failures': state['integrity_failures']}
        try:
            self.check_inputs(state)
            spec = item['versions'][-1]
            manifest = state['manifest']
            if not manifest['synthetic']:
                for c in manifest['commodity_group']['members']:
                    meta = manifest['registry'][c]
                    missing = [c + '.metadata.' + k for k in ('symbol', 'exchange', 'contract_multiplier', 'tick_size',
                         'delivery_quality', 'delivery_location', 'effective_from', 'effective_to',
                         'calendar_source', 'verified_at', 'primary_source', 'source_snapshot_hash') if not meta.get(k)]
                    if meta.get('verification_status') != 'verified': missing.append(c + '.metadata.verification_status')
                    if missing: raise BlockedData(missing)
                    for d in manifest['decisions']:
                        if not timestamp(meta['effective_from']) <= timestamp(d['execution_at']) <= timestamp(meta['effective_to']):
                            raise BlockedData([c + '.metadata.effective_interval'])
            records = read_json(self.path / 'inputs/predictors.json')
            store = AsOf(records)
            panel, verified = [], True
            missing = []
            for d in manifest['decisions']:
                try:
                    absent = []
                    for name, rule in spec['input_fields'].items():
                        try:
                            store.latest(name, rule, d['decision_at'])
                        except BlockedData as exc:
                            absent.extend(exc.fields)
                    if absent:
                        raise BlockedData(absent)
                    result = compute(spec, store, d['decision_at'], d['fit_cutoff'])
                    future_invariance(spec, records, d['decision_at'], d['fit_cutoff'])
                    verified = verified and result['verified_pit']
                    panel.append(dict(d, factor_id=ident, spec_version=spec['version'], spec_hash=digest(spec),
                                      value=result['value'], lineage=result['trace'], verified_pit=result['verified_pit']))
                except BlockedData as exc:
                    missing.extend(d['decision_at'] + '::' + field for field in exc.fields)
            if missing: raise BlockedData(missing)
            artifact = self.path / 'exports' / ('%s-v%d' % (ident, spec['version']))
            provenance = {'data_hashes': state['hashes'], 'code_hash': state['code_hash'], 'spec_hash': digest(spec),
                          'synthetic': manifest['synthetic'], 'verified_pit': verified,
                          'model_prompt_versions': manifest['model_prompt_versions']}
            req = adapter.request(spec, panel, manifest['evaluation_plan'], provenance,
                                  self.ledger.events(), read_json(self.path / 'inputs/existing_factors.json'))
            write_once(artifact / 'specification.json', spec)
            write_once(artifact / 'factor-panel.json', panel)
            write_once(artifact / 'evaluation-request.json', req)
            values = [r['value'] for r in panel]
            diagnostics = {'status': 'LOCAL_DIAGNOSTICS_ONLY', 'coverage': len(panel) / len(manifest['decisions']),
                'n_decisions': len(panel), 'min': min(values), 'max': max(values),
                'positive_count': sum(v > 0 for v in values), 'negative_count': sum(v < 0 for v in values),
                'output_unit': spec['units']['output'], 'verified_pit': verified,
                'unique_observation_periods': len({(r['field'], r['source'], r['period_start'], r['period_end']) for p in panel for r in p['lineage']}),
                'available_calendar_years': sorted({r['period_end'][:4] for p in panel for r in p['lineage']}),
                'crop_years': 'NOT_MAPPED: requires commodity-region marketing-year metadata',
                'outliers': 'REVIEW_REQUIRED: no data-fitted threshold outside training split',
                'freshness': 'PASS: all inputs including lagged/seasonal accesses checked',
                'units': 'input units checked; reviewer must verify expression dimensionality',
                'leakage_safeguard': 'PASS: fixed-seed future-record mutation/addition/removal; not exhaustive'}
            write_once(artifact / 'diagnostics.json', diagnostics)
            result = {'status': 'NOT_EVALUATED', 'reason': 'No external evaluator result supplied',
                      'request_hash': req['request_hash'], 'artifact': str(artifact), 'verified_pit': verified}
        except BlockedData as exc:
            result = {'status': 'BLOCKED_DATA', 'missing_fields': exc.fields}
        except IntegrityError as exc:
            self.fail_integrity(str(exc))
            return {'status': 'BLOCKED_INTEGRITY', 'reason': str(exc)}
        def finish(s):
            it = s['proposed'][ident]
            it['evaluations'].append({'version': it['versions'][-1]['version'], 'result': result})
            it.update(status=result['status'], latest_result=result, verified_pit=result.get('verified_pit', False))
        self.ledger.mutate('COMPUTE_ATTEMPT', {'factor_id': ident, 'result': result}, finish)
        return result

    def import_evaluation(self, ident, result):
        state = self.ledger.state()
        self.check_inputs(state)
        item = state['proposed'][ident]
        if state['integrity_failures'] or item['status'] != 'NOT_EVALUATED':
            raise IntegrityError('Candidate not eligible for evaluation import')
        req = read_json(Path(item['latest_result']['artifact']) / 'evaluation-request.json')
        try:
            body = {k: v for k, v in req.items() if k != 'request_hash'}
            if digest(body) != req['request_hash'] or req['request_hash'] != item['latest_result']['request_hash']:
                raise IntegrityError('Frozen evaluation request modified')
            artifact = Path(item['latest_result']['artifact'])
            if read_json(artifact / 'specification.json') != req['specification'] or read_json(artifact / 'factor-panel.json') != req['factor_panel']:
                raise IntegrityError('Frozen specification/panel modified')
            validated = adapter.import_result(result, req)
        except IntegrityError as exc:
            self.fail_integrity(str(exc))
            raise
        def update(s):
            s['proposed'][ident].update(status='EVALUATED', latest_result=validated)
        state = self.ledger.mutate('IMPORT_EXTERNAL_EVALUATION', {'factor_id': ident, 'result': result}, update)
        self.packet(state, 'acceptance')
        return state
