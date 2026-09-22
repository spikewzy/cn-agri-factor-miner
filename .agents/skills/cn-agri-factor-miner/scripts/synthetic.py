"""Fixed-seed, entirely synthetic soybean-complex fixture; no market observations."""
import copy
import datetime as dt
import random
from records import write_once


def field(name): return {'field': name}
def const(value): return {'const': value}
def op(name, *args, **kwargs): return dict(op=name, args=list(args), **kwargs)


def fixture():
    rng = random.Random(241)
    group = {'id': 'soybean_complex', 'members': ['soybean_meal', 'soybean_oil'],
             'linkage': 'Joint outputs from imported soybean crushing; distinct demand and stocks'}
    units = {'meal_stock': 'tonne', 'meal_disappearance': 'tonne/week', 'oil_stock': 'tonne',
             'oil_disappearance': 'tonne/week', 'raw_stock': 'tonne', 'arrivals_14d': 'tonne',
             'planned_crush_14d': 'tonne', 'crush_margin': 'CNY/tonne_feedstock'}
    dictionary = {f: {'source': 'SYNTHETIC', 'unit': unit,
                     'kind': 'forecast' if f in ('arrivals_14d', 'planned_crush_14d') else 'realization',
                     'max_release_age_days': 10, 'max_observation_age_days': 14,
                     **({'target_days': 14} if f in ('arrivals_14d', 'planned_crush_14d') else {})} for f, unit in units.items()}
    dates = [dt.date(year, month, 3) for year in (2022, 2023, 2024) for month in range(1, 13)]
    dates += [dt.date(2024, 12, 20) + dt.timedelta(days=7 * i) for i in range(8)]
    records = []
    for d in sorted(set(dates)):
        vals = {'meal_stock': 800 + rng.random() * 200, 'meal_disappearance': 220 + rng.random() * 20,
                'oil_stock': 450 + rng.random() * 100, 'oil_disappearance': 90 + rng.random() * 10,
                'raw_stock': 1800 + rng.random() * 400, 'arrivals_14d': 900 + rng.random() * 300,
                'planned_crush_14d': 1300 + rng.random() * 100, 'crush_margin': -30 + rng.random() * 100}
        for f, value in vals.items():
            forecast = dictionary[f]['kind'] == 'forecast'
            records.append({'field': f, 'period_start': (d + dt.timedelta(days=1) if forecast else d - dt.timedelta(days=7)).isoformat(),
                            'period_end': (d + dt.timedelta(days=14) if forecast else d - dt.timedelta(days=1)).isoformat(),
                            'published_at': d.isoformat() + 'T08:00:00+08:00', 'available_at': d.isoformat() + 'T08:30:00+08:00',
                            'source': 'SYNTHETIC', 'revision': 0, 'kind': dictionary[f]['kind'], 'unit': units[f],
                            'value': round(value, 4), 'availability_basis': 'synthetic',
                            'event_id': 'synthetic-' + f + '-' + d.isoformat()})
    # Genuine revised release in the synthetic timeline; old vintage remains archived.
    r = copy.deepcopy(next(r for r in records if r['field'] == 'meal_stock' and r['published_at'].startswith('2025-01-03')))
    r.update(revision=1, value=r['value'] + 30, published_at='2025-01-04T08:00:00+08:00', available_at='2025-01-04T08:30:00+08:00', event_id='synthetic-meal-stock-revision')
    records.append(r)
    decisions = [{'decision_at': (dt.date(2025, 1, 3) + dt.timedelta(days=7*i)).isoformat() + 'T15:30:00+08:00',
                  'execution_at': (dt.date(2025, 1, 6) + dt.timedelta(days=7*i)).isoformat() + 'T09:01:00+08:00',
                  'trading_date': (dt.date(2025, 1, 6) + dt.timedelta(days=7*i)).isoformat(),
                  'calendar_source': 'SYNTHETIC schedule; NOT an exchange calendar',
                  'fit_cutoff': '2024-12-31T23:59:59+08:00'} for i in range(3)]
    manifest = {'schema_version': 1, 'synthetic': True, 'input_scope': 'development_only',
                'commodity_group': group, 'decisions': decisions,
                'registry': {c: {'market': 'CN_FUTURES', 'family': 'oilseeds', 'exchange': 'DCE',
                    'symbol_hint_unverified': symbol, 'verification_status': 'SYNTHETIC_ONLY'} for c, symbol in [('soybean_meal', 'M'), ('soybean_oil', 'Y')]},
                'discovery_audit': 'Empty workspace inspected: no licensed data, dictionaries, existing factors, corrections or external evaluator. Synthetic fixture only.',
                'model_prompt_versions': {'model': 'none:deterministic_fixture', 'prompt': 'synthetic-v1',
                    'retrospective_llm': False, 'source_extraction_version': 'not_applicable'},
                'evaluation_plan': {'baseline_model': 'fixed linear ridge on baseline factors, fixed alpha=1; train-only standardization',
                    'model_version': 'research-contract-v1', 'horizon_days': 14, 'decision_frequency': 'weekly',
                    'splits': [{'train_start': '2022-01-01T00:00:00+08:00', 'train_end': '2024-12-31T23:59:59+08:00',
                                'test_start': '2025-01-01T00:00:00+08:00', 'test_end': '2025-01-31T23:59:59+08:00'}],
                    'overlap_policy': 'Purge labels crossing split boundary; use date-block bootstrap >=14 calendar days, report sensitivity; weekly overlapping labels are not iid.',
                    'label_policy': 'External real-contract labels; outcome_end and observable_at <= training cutoff; physical endpoints also use released vintages.',
                    'execution_policy': 'External calendar verifies night-session trading date, holidays and next eligible execution strictly after signal; no same-close fills.',
                    'holdout_policy': 'external_custodian_only', 'small_sample_policy': 'Report uncertainty by crop year and insufficient data; no significance-based acceptance after selection.',
                    'perturbations': 'Predeclare freshness 7/10 days and meal cap 3.5/4 weeks; each tested variation consumes one of three specifications, no free grid search.',
                    'cross_sectional_ic': 'disabled'}}
    coverage = op('div', field('meal_stock'), field('meal_disappearance'))
    seasonal = op('seasonal_anomaly', coverage, anchor='meal_stock', min_years=2, calendar='calendar_month')
    arrival_balance = op('div', op('sub', op('add', field('arrivals_14d'), field('raw_stock')), field('planned_crush_14d')), field('planned_crush_14d'))
    raw_gate = op('min', const(1), op('div', field('raw_stock'), field('planned_crush_14d')))
    meal_gate = op('div', const(1), op('add', const(1), op('div', coverage, const(4))))
    oil_gate = op('div', const(1), op('add', const(1), op('div', op('div', field('oil_stock'), field('oil_disappearance')), const(6))))
    crush_gate = op('mul', op('change', field('crush_margin'), days=7), op('mul', raw_gate, op('min', meal_gate, oil_gate)))
    definitions = [
        ('inventory_coverage', 'inventory_tightness', op('neg', seasonal), ['meal_stock', 'meal_disappearance'],
         'Seasonally unusual meal inventory coverage may precede meal supply tightness.',
         'Fewer weeks of same-sample inventory relative to disappearance can constrain near-term deliveries.',
         'Stock coverage falls because sample firms exit, feed demand collapses, or inventories move downstream; no genuine tightness.',
         'positive value -> higher meal return, conditional and unvalidated', 'week',
         'Compare next released meal stock/disappearance and delivery shortfalls; distinguish survey coverage changes.',
         {'seasonal_calendar': 'calendar_month illustrative only; China/Lunar New Year alignment requires reviewed operator', 'min_years': 2}),
        ('arrival_balance', 'feedstock_balance', op('neg', arrival_balance), ['arrivals_14d', 'raw_stock', 'planned_crush_14d'],
         'Dated, locally available soybean-arrival forecasts versus stocks and planned crush may predict feedstock bottlenecks.',
         'A two-week feedstock balance changes feasible crushing before joint product replenishment.',
         'Vessels arrive but customs/quality clearance delays usability; processors cancel crush plans; demand falls faster than output.',
         'positive value -> constrained crushing and potentially higher meal/oil returns, separately tested', 'ratio',
         'Compare forecast same-window cleared arrivals with realized cleared arrivals and actual crush; this is a balance, not a surprise.',
         {'forecast_target_days': 14}),
        ('crush_constraints', 'processing_supply_response', op('neg', crush_gate),
         ['crush_margin', 'raw_stock', 'planned_crush_14d', 'meal_stock', 'meal_disappearance', 'oil_stock', 'oil_disappearance'],
         'Improving crush margins may increase output only when feedstock and both product storage/demand conditions allow it.',
         'A margin-change signal is gated by raw availability and the tighter of distinct meal/oil inventory constraints.',
         'Margins reflect a meal/oil demand shock or unhedgeable quotes; maintenance, logistics or absent buyers prevent more crush.',
         'positive value -> weaker near-term output response and potentially higher returns; verify separately for meal/oil', 'CNY/tonne_feedstock',
         'Test subsequent actual crush and separate meal/oil stocks, conditioning on maintenance and contemporaneous demand.',
         {'change_days': 7, 'meal_coverage_scale_weeks': 4, 'oil_coverage_scale_weeks': 6})]
    specs = []
    for ident, family, formula, fields, hyp, mechanism, counter, direction, output_unit, physical, params in definitions:
        specs.append({'id': ident, 'version': 1, 'commodity_group': group, 'economic_family': family,
            'hypothesis': hyp, 'mechanism': mechanism, 'counterexample': counter,
            'evidence': [{'kind': 'illustration', 'source': 'synthetic-v1', 'excerpt': 'No empirical evidence supplied. Mechanism is an unvalidated research hypothesis.',
                          'supports': 'economic motivation only', 'contradicts': counter, 'publication_time': None,
                          'extraction_version': 'synthetic-v1', 'event_id': 'hypothesis-' + ident}],
            'expected_direction': direction, 'target': {'return': 'external 14-day real-contract return; meal only for coverage, separate meal/oil for others',
                'physical': physical}, 'horizon': 14, 'input_fields': {f: dictionary[f] for f in fields},
            'units': {'inputs': {f: units[f] for f in fields}, 'output': output_unit},
            'availability_rules': 'Latest eligible source vintage; exact next-14-day forecast targets; observed publications required for verified PIT.',
            'formula': formula, 'parameters': params,
            'normalization': 'Training-cutoff eligible prior calendar-month years, equal year weighting' if ident == 'inventory_coverage' else 'No fitted normalization',
            'missing_stale_policy': 'BLOCKED_DATA; no backfill; bounded forward use only after release',
            'failure_conditions': [counter, 'Unknown vintages, unit/sample/location mismatch, overlap in inventory coverage'],
            'closest_existing_factors': ['baseline_coverage'] if ident == 'inventory_coverage' else ['baseline_feedstock_balance'] if ident == 'arrival_balance' else ['baseline_margin_change'],
            'incremental_information': 'Seasonal context' if ident == 'inventory_coverage' else 'Dated forecast versus physical processing plan' if ident == 'arrival_balance' else 'Availability and separate joint-output constraints',
            'physical_test': physical, 'price_derived': ['crush_margin'] if ident == 'crush_constraints' else []})
    catalog = [{'id': 'baseline_coverage', 'status': 'documented_reproducible_unvalidated', 'formula': coverage,
                'mechanism': 'Inventory/disappearance state', 'family': 'inventory_tightness'},
               {'id': 'baseline_feedstock_balance', 'status': 'documented_reproducible_unvalidated',
                'formula': op('sub', field('raw_stock'), field('planned_crush_14d')), 'mechanism': 'Stock minus planned use', 'family': 'feedstock_balance'},
               {'id': 'baseline_margin_change', 'status': 'documented_reproducible_unvalidated',
                'formula': op('change', field('crush_margin'), days=7), 'mechanism': 'Processing incentive', 'family': 'processing_supply_response'}]
    return manifest, records, catalog, [], dictionary, specs


def export(directory):
    from pathlib import Path
    manifest, records, catalog, corrections, dictionary, specs = fixture()
    for name, value in [('manifest', manifest), ('predictors', records), ('existing_factors', catalog),
                        ('human_corrections', corrections), ('data_dictionary', dictionary), ('specifications', specs)]:
        write_once(Path(directory) / (name + '.json'), value)
