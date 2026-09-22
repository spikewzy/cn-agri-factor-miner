"""A finite expression tree, with no eval, imports, or generated code execution."""
import datetime as dt
import statistics
from pit import AsOf, BlockedData, IntegrityError, number, timestamp

ARITY = {'add': 2, 'sub': 2, 'mul': 2, 'div': 2, 'neg': 1, 'min': 2, 'max': 2,
         'change': 1, 'seasonal_anomaly': 1}


def validate_expression(node, fields, depth=0):
    if depth > 12 or not isinstance(node, dict):
        raise IntegrityError('Expression depth/type invalid')
    if set(node) == {'const'}:
        number(node['const'])
        return
    if set(node) == {'field'}:
        if node['field'] not in fields:
            raise IntegrityError('Undeclared field: ' + node['field'])
        return
    op = node.get('op')
    if op not in ARITY or not isinstance(node.get('args'), list) or len(node['args']) != ARITY[op]:
        raise IntegrityError('Unknown operator or arity')
    extras = {'days'} if op == 'change' else {'anchor', 'min_years', 'calendar'} if op == 'seasonal_anomaly' else set()
    if set(node) != {'op', 'args'} | extras:
        raise IntegrityError('Unexpected/missing operator parameters')
    if op == 'change' and (type(node['days']) is not int or not 1 <= node['days'] <= 366):
        raise IntegrityError('Invalid backward lag')
    if op == 'seasonal_anomaly':
        if node['anchor'] not in fields or fields[node['anchor']]['kind'] != 'realization':
            raise IntegrityError('Seasonal anchor must be a declared realized variable')
        if node['calendar'] != 'calendar_month' or type(node['min_years']) is not int or node['min_years'] < 2:
            raise IntegrityError('v1 implements calendar_month only; other calendars need review/tests')
    for child in node['args']:
        validate_expression(child, fields, depth + 1)


def compute(spec, store, at, fit_cutoff=None):
    """fit_cutoff is mandatory for fitted normalization and must come from the split plan."""
    validate_expression(spec['formula'], spec['input_fields'])
    t = timestamp(at)
    cutoff = timestamp(fit_cutoff) if fit_cutoff else None
    if cutoff and cutoff > t:
        raise IntegrityError('Fitting cutoff exceeds decision time')
    trace = []

    def ev(node, when):
        if 'const' in node:
            return number(node['const'])
        if 'field' in node:
            row = store.latest(node['field'], spec['input_fields'][node['field']], when.isoformat())
            trace.append(row)
            return number(row['value'])
        op, args = node['op'], node['args']
        if op == 'change':
            return ev(args[0], when) - ev(args[0], when - dt.timedelta(days=node['days']))
        if op == 'seasonal_anomaly':
            if cutoff is None:
                raise BlockedData(['fit_cutoff'])
            current = ev(args[0], when)
            anchor = node['anchor']
            rule = spec['input_fields'][anchor]
            current_period = store.latest(anchor, rule, when.isoformat())['period_end']
            current_date = dt.date.fromisoformat(current_period)
            # One value per observation period, then equal-weight crop/calendar years.
            rows = store.history(anchor, rule, min(cutoff, when).isoformat())
            yearly = {}
            for row in rows:
                d = dt.date.fromisoformat(row['period_end'])
                if d.year >= current_date.year or d.month != current_date.month:
                    continue
                historic_at = timestamp(row['available_at'])
                try:
                    value = ev(args[0], historic_at)
                except BlockedData:
                    continue
                yearly.setdefault(d.year, []).append(value)
            if len(yearly) < node['min_years']:
                raise BlockedData([anchor + ':seasonal_history_years'])
            return current - statistics.mean(statistics.mean(v) for v in yearly.values())
        values = [ev(a, when) for a in args]
        if op == 'div':
            if abs(values[1]) < 1e-12:
                raise BlockedData(['formula:zero_denominator'])
            out = values[0] / values[1]
        elif op == 'add': out = values[0] + values[1]
        elif op == 'sub': out = values[0] - values[1]
        elif op == 'mul': out = values[0] * values[1]
        elif op == 'neg': out = -values[0]
        elif op == 'min': out = min(values)
        elif op == 'max': out = max(values)
        else: raise IntegrityError('Operator not implemented')
        return number(out)

    value = number(ev(spec['formula'], t))
    return {'value': value, 'trace': trace,
            'verified_pit': bool(trace) and all(r['availability_basis'] == 'observed' for r in trace)}


def future_invariance(spec, records, at, fit_cutoff, computer=compute):
    """Fixed-seed metamorphic safeguard, not a general proof of absence of leakage."""
    import copy
    import random
    rng = random.Random(241)
    t = timestamp(at)
    old = [r for r in records if timestamp(r['available_at']) <= t]
    changed = copy.deepcopy(records)
    for r in changed:
        if timestamp(r['available_at']) > t:
            r['value'] = rng.uniform(1e4, 1e6)
    extra = copy.deepcopy(records[0])
    extra.update(value=987654321, revision=extra['revision'] + 999,
                 published_at=(t + dt.timedelta(days=50)).isoformat(),
                 available_at=(t + dt.timedelta(days=51)).isoformat(), event_id='future-invariance-injection')
    if extra.get('availability_basis') == 'first_seen':
        extra['first_seen_at'] = extra['available_at']
    baseline = computer(spec, AsOf(records), at, fit_cutoff)['value']
    for variant in (old, changed, records + [extra]):
        if computer(spec, AsOf(variant), at, fit_cutoff)['value'] != baseline:
            raise IntegrityError('LEAKAGE_TEST_FAILED: future records altered earlier value')
    return True
