"""Point-in-time predictor store. Labels deliberately have a separate API."""
import copy
import datetime as dt
import math


class IntegrityError(ValueError):
    pass


class BlockedData(ValueError):
    def __init__(self, fields):
        self.fields = sorted(set(fields))
        super().__init__('BLOCKED_DATA: ' + ', '.join(self.fields))


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise IntegrityError('Timezone-aware timestamp required: ' + value)
    return result


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise IntegrityError('Expected finite numeric value')
    return float(value)


class AsOf:
    def __init__(self, records):
        self.__records = copy.deepcopy(records)
        seen = {}
        for r in self.__records:
            required = ('field', 'period_start', 'period_end', 'available_at',
                        'source', 'revision', 'kind', 'unit', 'value', 'availability_basis', 'event_id')
            missing = [k for k in required if k not in r or r[k] is None or r[k] == '']
            if missing:
                raise BlockedData([r.get('field', '?') + '.' + k for k in missing])
            avail = timestamp(r['available_at'])
            if r['availability_basis'] == 'first_seen':
                if timestamp(r.get('first_seen_at', '')) != avail or not r.get('raw_sha256') or not r.get('receipt_id'):
                    raise IntegrityError('First-seen data requires capture time and raw source receipt')
                pub = timestamp(r['published_at']) if r.get('published_at') else avail
            else:
                if not r.get('published_at'): raise BlockedData([r['field'] + '.published_at'])
                pub = timestamp(r['published_at'])
            if pub > avail:
                raise IntegrityError('Availability precedes publication')
            start, end = dt.date.fromisoformat(r['period_start']), dt.date.fromisoformat(r['period_end'])
            if start > end or r['kind'] not in ('forecast', 'realization'):
                raise IntegrityError('Invalid period/kind')
            if r['kind'] == 'realization' and end > pub.date():
                raise IntegrityError('Realization published before outcome period ended')
            if r['availability_basis'] not in ('observed', 'reconstructed', 'unknown', 'synthetic', 'first_seen'):
                raise IntegrityError('Invalid availability provenance')
            if not isinstance(r['revision'], int) or r['revision'] < 0:
                raise IntegrityError('Revision must be a nonnegative integer')
            number(r['value'])
            if r.get('text_derived'):
                for key in ('source_excerpt', 'source_url', 'extraction_version', 'model_version',
                            'prompt_hash', 'archived_input_hash', 'retrospective_llm'):
                    if key not in r:
                        raise BlockedData([r['field'] + '.text.' + key])
            key = (r['field'], r['source'], r['period_start'], r['period_end'], r['kind'], r['revision'])
            if key in seen and seen[key] != r:
                raise IntegrityError('Conflicting records for one vintage')
            seen[key] = r
        # Exact reposts are one event, not independent observations.
        self.__records = list(seen.values())

    def history(self, field, rule, at):
        t = timestamp(at)
        eligible = {}
        for r in self.__records:
            if r['field'] != field or r['source'] != rule['source'] or r['kind'] != rule['kind']:
                continue
            if (r.get('published_at') and timestamp(r['published_at']) > t) or timestamp(r['available_at']) > t:
                continue
            if r['kind'] == 'realization' and dt.date.fromisoformat(r['period_end']) > t.date():
                continue
            if r['unit'] != rule['unit']:
                raise IntegrityError('Unit mismatch for ' + field)
            key = (r['period_start'], r['period_end'], r['source'], r['kind'])
            old = eligible.get(key)
            # Revision order is source-provided; tied revisions are validated at ingest.
            if old is None or r['revision'] > old['revision']:
                eligible[key] = r
        return copy.deepcopy(sorted(eligible.values(), key=lambda r: (r['period_end'], r['available_at'])))

    def latest(self, field, rule, at):
        t = timestamp(at)
        rows = self.history(field, rule, at)
        if rule['kind'] == 'forecast':
            days = rule.get('target_days')
            if not days:
                raise IntegrityError('Forecast input needs an exact target_days window')
            start, end = (t.date() + dt.timedelta(days=1)).isoformat(), (t.date() + dt.timedelta(days=days)).isoformat()
            rows = [r for r in rows if r['period_start'] == start and r['period_end'] == end]
        if not rows:
            raise BlockedData([field + ':eligible_vintage'])
        r = max(rows, key=lambda x: (x['period_end'], timestamp(x['available_at']), x['revision']))
        if (t - timestamp(r['available_at'])).total_seconds() > rule['max_release_age_days'] * 86400:
            raise BlockedData([field + ':stale_release'])
        if r['kind'] == 'realization' and (t.date() - dt.date.fromisoformat(r['period_end'])).days > rule['max_observation_age_days']:
            raise BlockedData([field + ':stale_observation'])
        return r


def observable_labels(records, train_at):
    """Evaluator-side utility; never given to the predictor formula interpreter."""
    t = timestamp(train_at)
    result = []
    for r in records:
        if timestamp(r['outcome_end']) > timestamp(r['observable_at']):
            raise IntegrityError('Label observability before outcome')
        if timestamp(r['observable_at']) <= t and timestamp(r['outcome_end']) <= t:
            result.append(copy.deepcopy(r))
    return result


def deduplicate_events(events):
    """Canonical event IDs must be assigned by a reviewed source-ingestion process.

    Reposts share an event ID. A revised forecast has a distinct revision and is
    retained. Conflicting values for the same event/variable/vintage are blocked.
    """
    unique = {}
    for event in events:
        key = tuple(event[k] for k in ('event_id', 'field', 'period_start', 'period_end', 'revision'))
        old = unique.get(key)
        if old and (old['value'], old['unit'], old['kind']) != (event['value'], event['unit'], event['kind']):
            raise IntegrityError('Conflicting extracted values for one canonical event')
        if old is None or timestamp(event.get('published_at') or event['available_at']) < timestamp(old.get('published_at') or old['available_at']):
            unique[key] = copy.deepcopy(event)
    return list(unique.values())
