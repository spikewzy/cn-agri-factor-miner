"""File hand-off only. No backtester, remote calls, portfolio or returns engine."""
from pit import IntegrityError, timestamp, number
from records import digest

DIAGNOSTICS = ['coverage_staleness_units_outliers_sign_crop_years',
 'per_commodity_time_series_ic_rank_ic_uncertainty',
 'crop_year_regime_parameter_stability_serial_dependence',
 'fixed_model_incremental_oos_family_ablation',
 'formula_mechanism_exposure_redundancy', 'selection_uncertainty_all_attempts',
 'intermediate_physical_prediction_where_measurable']


def validate_plan(plan):
    required = ['baseline_model', 'model_version', 'horizon_days', 'decision_frequency', 'splits',
                'overlap_policy', 'label_policy', 'execution_policy', 'holdout_policy',
                'small_sample_policy', 'perturbations', 'cross_sectional_ic']
    if any(k not in plan for k in required):
        raise IntegrityError('Incomplete fixed evaluation plan')
    if plan['horizon_days'] <= 0 or plan['decision_frequency'] != 'weekly':
        raise IntegrityError('Unsupported decision frequency/horizon')
    if plan['holdout_policy'] != 'external_custodian_only':
        raise IntegrityError('Final holdout must remain outside exploratory inputs')
    if plan['cross_sectional_ic'] != 'disabled':
        raise IntegrityError('v1 supports per-commodity time-series evaluation only')
    if not plan['splits']:
        raise IntegrityError('Chronological splits required')
    prior = None
    for split in plan['splits']:
        a, b, c, d = [timestamp(split[k]) for k in ('train_start', 'train_end', 'test_start', 'test_end')]
        if not a < b < c < d or (prior and c <= prior):
            raise IntegrityError('Splits must be chronological with disjoint test windows')
        prior = d


def request(spec, panel, plan, provenance, attempts, existing_factors):
    validate_plan(plan)
    body = {'schema_version': 1, 'purpose': 'development_external_evaluation',
            'specification': spec, 'factor_panel': panel, 'plan': plan,
            'provenance': provenance, 'attempt_ledger': attempts, 'existing_factors': existing_factors,
            'required_diagnostics': DIAGNOSTICS,
            'requirements': {'fit_inside_each_training_split': True,
                'labels_observable_before_train_cutoff': True,
                'real_contract_aware_labels': True, 'continuous_splice_returns_forbidden': True,
                'contracts_not_independent_commodities': True,
                'return_performance_requires_roll_cost_execution_assumptions': True,
                'final_holdout_not_returned_to_exploratory_agent': True}}
    body['request_hash'] = digest(body)
    return body


def import_result(result, req):
    if result['request_hash'] != req['request_hash']:
        raise IntegrityError('Evaluator response does not match frozen request')
    if result.get('assessment_scope') != 'development_only':
        raise IntegrityError('Do not import final holdout results into exploratory run')
    if result.get('status') != 'EVALUATED':
        raise IntegrityError('Only completed external evaluations can be imported')
    for k in ('evaluator_id', 'evaluator_version', 'evaluated_at', 'diagnostics', 'integrity_checks'):
        if not result.get(k):
            raise IntegrityError('Missing evaluator field: ' + k)
    timestamp(result['evaluated_at'])
    checks = result['integrity_checks']
    for k in ('point_in_time', 'observable_labels', 'training_only_fits', 'real_contract_labels', 'overlap_handled'):
        if checks.get(k) is not True:
            raise IntegrityError('External integrity check failed: ' + k)
    if set(DIAGNOSTICS) - set(result['diagnostics']):
        raise IntegrityError('Missing requested diagnostics')
    for name, diagnostic in result['diagnostics'].items():
        if not isinstance(diagnostic, dict) or diagnostic.get('status') not in ('PASS', 'FAIL', 'INSUFFICIENT_DATA') or not diagnostic.get('evidence'):
            raise IntegrityError('Each diagnostic needs status and evidence: ' + name)
    if result.get('trading_performance'):
        if any(not result.get(k) for k in ('roll_assumptions', 'cost_assumptions', 'execution_assumptions')):
            raise IntegrityError('Trading performance lacks roll/cost/execution assumptions')
    return result
