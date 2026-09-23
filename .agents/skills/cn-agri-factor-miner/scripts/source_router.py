#!/usr/bin/env python3
"""User-first data sources, host MCP handoff, and daily-price discovery requests."""
import argparse
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import uuid

from acquire import (archive, date_value, now, numeric, receipts, safe_config, table, workspace, mapped_records, warehouse_records)
from providers import NoRedirect, ProviderError, choice, public_url, tushare
from records import canonical, digest, read_json, write_once
from sources import PROFILES, commodity


def config(root, path=None):
    location = Path(path or os.environ.get('CN_AGRI_SOURCES') or root/'data-sources.json').expanduser()
    obj = read_json(location) if location.exists() else {'schema_version': 1, 'sources': []}
    if (path or os.environ.get('CN_AGRI_SOURCES')) and not location.exists():
        raise ValueError('Explicit data-source configuration does not exist')
    safe_config(obj)
    if obj.get('schema_version') != 1 or not isinstance(obj.get('sources'), list):
        raise ValueError('Expected data-source schema_version=1 and sources array')
    if len(obj['sources']) > 40: raise ValueError('At most 40 configured sources; narrow scope')
    ids = set()
    for source in obj['sources']:
        ident = source.get('id', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', ident) or ident in ids:
            raise ValueError('Source ids must be unique simple identifiers')
        ids.add(ident)
        if source.get('enabled', True):
            if source.get('provider') not in ('http', 'mcp', 'tushare', 'choice'):
                raise ValueError('Source provider must be http, mcp, tushare or choice')
            if not source.get('capability') or not source.get('evidence') or str(source['evidence']).startswith('REPLACE_'):
                raise ValueError('Enabled sources need capability and endpoint/field evidence')
            if source['provider'] == 'mcp' and (source.get('read_only') is not True or
                not source.get('server') or not source.get('tool') or not isinstance(source.get('arguments'), dict)):
                raise ValueError('MCP requires read_only=true and discovered server/tool/arguments')
    return obj


def expand(value, context):
    # Only named scalar substitutions, not Python format expressions or executable code.
    if isinstance(value, str):
        def replace(match):
            key = match.group(1)
            if key not in context: raise ValueError('Unknown source placeholder: ' + key)
            return str(context[key])
        return re.sub(r'\{([a-z_]+)\}', replace, value)
    if isinstance(value, list): return [expand(x, context) for x in value]
    if isinstance(value, dict): return {k: expand(v, context) for k, v in value.items()}
    return value


def request_need(product, capability, start, end, contract=''):
    product = commodity(product)
    start, end = date_value(start), date_value(end)
    if start > end: raise ValueError('start must be <= end')
    name, symbol, exchange = PROFILES[product][:3]
    return {'commodity': product, 'name': name, 'symbol': symbol, 'exchange': exchange,
            'capability': capability, 'start': start, 'end': end,
            'start_date': start.replace('-', ''), 'end_date': end.replace('-', ''),
            'contract': contract.upper(), 'contract_code': contract.upper().split('.')[0]}


def assert_no_secrets(data, sources):
    """Never archive a response that echoes a configured credential."""
    for source in sources:
        env = source.get('auth', {}).get('env')
        secret = os.environ.get(env, '') if env else ''
        if secret and any(v.encode() in data for v in (secret, urllib.parse.quote(secret, safe=''),
                                                       json.dumps(secret)[1:-1])):
            raise ProviderError('BLOCKED_SECRET_ECHO', 'Provider response contains a configured credential; response not saved')


def http(source, transport=None):
    request = source['request']
    url = public_url(request['url'])
    params, body = dict(request.get('params', {})), dict(request.get('json', {}))
    method = request.get('method', 'GET').upper()
    if method not in ('GET', 'POST') or source.get('read_only') is not True:
        raise ValueError('Custom requests require read_only=true and GET/POST')
    if method == 'GET' and body: raise ValueError('GET request cannot have a JSON body')
    headers = {'Accept': 'application/json', 'User-Agent': 'cn-agri-factor-miner/0.4'}
    # Secret-bearing custom headers must come exclusively from auth.env.
    for key, value in request.get('headers', {}).items():
        if key.lower() not in ('accept', 'user-agent'): raise ValueError('Use auth.env for authentication headers')
        headers[key] = value
    auth = source.get('auth')
    if auth:
        if set(auth) - {'env', 'in', 'name', 'prefix'} or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', auth.get('env', '')):
            raise ValueError('auth stores an environment variable name, never a literal key')
        secret = os.environ.get(auth['env'])
        if not secret: raise ProviderError('BLOCKED_AUTH', 'Configured credential environment variable is absent')
        value = auth.get('prefix', '') + secret
        place = auth['in']
        if place == 'header': headers[auth['name']] = value
        elif place == 'query': params[auth['name']] = value
        elif place == 'body' and method == 'POST': body[auth['name']] = value
        else: raise ValueError('auth.in must be header, query, or POST body')
    if params: url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    payload = json.dumps(body).encode() if method == 'POST' else None
    if payload is not None: headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        if transport: data = transport(req)
        else:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=25) as response:
                data = response.read(20000001)
        if len(data) > 20000000: raise ProviderError('BLOCKED_SIZE', 'Response exceeds 20 MB')
        assert_no_secrets(data, [source])
        return data
    except ProviderError: raise
    except Exception as exc:
        raise ProviderError('BLOCKED_NETWORK', type(exc).__name__ + '; check endpoint/network/authorization') from None


def decode(data, spec):
    fmt = spec.get('format', 'json')
    text = data.decode('utf-8-sig')
    if fmt == 'csv': rows = list(csv.DictReader(io.StringIO(text)))
    else:
        if fmt == 'jsonp':
            # Parse the JSON payload only. Never execute provider JavaScript.
            text = re.sub(r'\A\s*(?:/\*.*?\*/\s*)*', '', text, flags=re.S)
            match = re.fullmatch(r'\s*(?:var\s+)?[\w.$]+\s*=\s*\((.*)\);?\s*', text, re.S)
            if not match: raise ValueError('Unsupported JSONP envelope')
            text = match.group(1)
        elif fmt != 'json': raise ValueError('Expected json, csv or assignment JSONP')
        rows = json.loads(text)
        for key in spec.get('rows_path', []): rows = rows[key]
        if rows is None: rows = []
        columns = spec.get('columns')
        if columns and rows and isinstance(rows[0], list):
            if any(len(row) != len(columns) for row in rows): raise ValueError('Row width mismatch')
            rows = [dict(zip(columns, row)) for row in rows]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Expected an array of row objects; verify response.rows_path')
    limit = spec.get('row_limit')
    if limit is not None and (type(limit) is not int or limit <= 0): raise ValueError('row_limit must be positive')
    if limit and len(rows) >= limit:
        raise ProviderError('BLOCKED_PAGINATION', 'Response reached declared row limit; narrow dates or use a host pagination adapter')
    return rows


def daily_rows(rows, source, need):
    spec = source['daily']
    columns = spec['columns']
    series = spec['series_type']
    if series not in ('actual_contract', 'continuous'): raise ValueError('Explicit daily series_type required')
    contract = need['contract']
    if not contract: raise ValueError('Choose a verified contract or explicitly identified continuous series')
    symbol = need['symbol']
    if series == 'actual_contract' and not re.fullmatch(re.escape(symbol) + r'\d{3,4}(?:\.[A-Z]+)?', contract):
        raise ValueError('Actual contract must have a delivery month; continuous symbols cannot be treated as contracts')
    if not spec.get('price_unit') or not spec.get('adjustment'):
        raise ValueError('Daily price_unit and adjustment must be explicit (unknown is allowed only for context)')
    result = {}
    for row in rows:
        day = date_value(row[columns['date']])
        if not need['start'] <= day <= need['end']: continue
        if columns.get('contract') and str(row[columns['contract']]).upper() != spec.get('contract_value', contract).upper():
            raise ValueError('Daily contract differs from requested contract')
        item = {'date': day, 'contract': contract}
        for field in ('open', 'high', 'low', 'close'):
            item[field] = numeric(row[columns[field]])
        if item['low'] > min(item['open'], item['close']) or item['high'] < max(item['open'], item['close']) or item['low'] > item['high']:
            raise ValueError('Invalid daily OHLC ordering')
        for field in ('settle', 'volume', 'open_interest', 'amount'):
            value = row.get(columns.get(field, ''))
            item[field] = None if value in (None, '') else numeric(value)
            if field in ('volume', 'open_interest', 'amount') and item[field] is not None and item[field] < 0:
                raise ValueError('Negative activity measure')
        if day in result and result[day] != item: raise ValueError('Conflicting bars for the same date')
        result[day] = item
    return [result[k] for k in sorted(result)]


def mcp_result(root, task):
    key = digest(task)
    pending = root/'mcp'/(key + '.json')
    if not pending.exists():
        write_once(pending, {'id': key, 'task': task, 'created_at': now(),
                            'instruction': 'Host must discover and call this connected read-only tool, then resolve-mcp with real row JSON or a factual failure. Do not install a server or fabricate a call.'})
    resolved = root/'mcp'/(key + '.result.json')
    if not resolved.exists(): return {'status': 'PAUSED_MCP', 'handoff': str(pending), 'request_id': key}
    result = read_json(resolved)
    if result['status'] != 'SUCCESS': raise ProviderError(result['status'], 'Host recorded MCP source unavailable/empty/failed')
    receipt = next(r for r in receipts(root) if r['id'] == result['receipt_id'])
    if receipt['request_hash'] != key: raise ValueError('MCP receipt/request mismatch')
    return receipt


def resolve_mcp(root, ident, status, filename=None, call_evidence=None):
    if not re.fullmatch('[a-f0-9]{64}', ident): raise ValueError('Invalid MCP request id')
    task = read_json(root/'mcp'/(ident + '.json'))['task']
    if digest(task) != ident: raise ValueError('MCP request changed')
    if status not in ('SUCCESS', 'EMPTY', 'BLOCKED_TOOL', 'BLOCKED_AUTH', 'BLOCKED_NETWORK', 'BLOCKED_PROVIDER'):
        raise ValueError('Unsupported MCP resolution status')
    if (root/'mcp'/(ident + '.result.json')).exists(): raise ValueError('MCP request already resolved; use a new work directory for a new snapshot')
    if not call_evidence: raise ValueError('Record the actual tool call reference, or tool-discovery failure evidence')
    result = {'request_id': ident, 'status': status, 'resolved_at': now(), 'call_evidence': call_evidence}
    if status == 'SUCCESS':
        data = Path(filename).read_bytes()
        assert_no_secrets(data, [task])
        rows = decode(data, {})
        if not rows: result['status'] = 'EMPTY'
        else:
            receipt = archive(root, task, data, 'application/json', metadata={'transport': 'host_mcp', 'call_evidence': call_evidence})
            result['receipt_id'] = receipt['id']
    write_once(root/'mcp'/(ident + '.result.json'), result)
    return result


def route(root, need, settings, builtin=None, refresh=False):
    candidates = [expand(s, need) for s in settings['sources'] if s.get('enabled', True)
                  and s['capability'] == need['capability']
                  and (not s.get('commodities') or need['commodity'] in s['commodities'])]
    if builtin and settings.get('allow_builtin', True): candidates.append(builtin)
    prior = {r['request_hash']: r for r in receipts(root)}
    attempts = []
    def report(status, **extra):
        result = dict(status=status, need=need, attempts=attempts, **extra)
        write_once(root/'routing'/(uuid.uuid4().hex+'.json'), result)
        return result
    for source in candidates:
        task = dict(source, need=need, commodity=need['commodity'])
        try:
            safe_config(task)
            receipt = None if refresh and source['provider'] != 'mcp' else prior.get(digest(task))
            status = 'CACHED' if receipt else 'FETCHED'
            if not receipt:
                provider = source['provider']
                if provider == 'mcp':
                    receipt = mcp_result(root, task)
                    if receipt.get('status') == 'PAUSED_MCP':
                        attempts.append({'source': source['id'], 'status': 'PAUSED_MCP'})
                        return report('PAUSED_MCP', handoff=receipt['handoff'], request_id=receipt['request_id'])
                else:
                    if provider == 'http':
                        data = http(source)
                        receipt = archive(root, task, data, 'application/octet-stream', metadata={'transport': 'http', 'response': source.get('response', {})})
                    else:
                        if provider == 'tushare': rows = tushare(source)
                        elif provider == 'choice':
                            with contextlib.redirect_stdout(sys.stderr): rows = choice(source)
                        else: raise ValueError('Unsupported provider')
                        receipt = archive(root, task, canonical(rows).encode(), 'application/json')
            raw = (root/receipt['raw']['path']).read_bytes()
            rows = decode(raw, source.get('response', {}) if source['provider'] == 'http' else {})
            if need['capability'] == 'daily':
                rows = daily_rows(rows, source, need)
            if not rows:
                attempts.append({'source': source['id'], 'status': 'EMPTY', 'receipt_id': receipt['id']}); continue
            # HTTP envelopes stay archived; a row-array receipt enables existing normalizers.
            if source['provider'] == 'http' and need['capability'] != 'daily':
                receipt = archive(root, dict(task, parent_receipt=receipt['id']), canonical(rows).encode(), 'application/json',
                                  receipt['retrieved_at'], {'derived_from': receipt['raw']['sha256']})
            if need['capability'] != 'daily':
                if source.get('mapping'):
                    checked = mapped_records(root, receipt, source['mapping'])
                    if checked['status'] == 'BLOCKED_SCHEMA' or not checked['records']:
                        raise ValueError('Custom mapping does not produce usable numeric records')
                elif source.get('api') == 'fut_wsr':
                    checked = warehouse_records(root, receipt)
                    if checked['status'] == 'BLOCKED_SCHEMA' or not checked['records']:
                        raise ValueError('Warehouse schema invalid')
                elif need['capability'] != 'contracts':
                    raise ValueError('Custom fundamental sources require an explicit table mapping')
            attempts.append({'source': source['id'], 'status': status, 'rows': len(rows), 'receipt_id': receipt['id']})
            extra = {'source': source['id'], 'receipt_id': receipt['id'], 'rows': len(rows)}
            if need['capability'] == 'daily':
                document = {'source': source['id'], 'need': need, 'semantics': source['daily'], 'receipt_id': receipt['id'],
                            'raw_sha256': receipt['raw']['sha256'], 'first_seen_at': receipt['retrieved_at'],
                            'historical_backtest_ready': False, 'calendar_coverage': 'UNVERIFIED',
                            'usage': 'market_context; keep separate from fundamental predictors and evaluator labels', 'bars': rows}
                path = root/'market'/(digest(document)+'.json')
                if not path.exists(): write_once(path, document)
                extra['daily_file'] = str(path)
            return report(status, **extra)
        except ProviderError as exc:
            attempts.append({'source': source['id'], 'status': exc.status, 'detail': exc.detail})
        except (ImportError, AttributeError):
            attempts.append({'source': source['id'], 'status': 'BLOCKED_ENVIRONMENT', 'detail': 'Provider SDK unavailable or incompatible'})
        except (ValueError, KeyError, TypeError, UnicodeError, IndexError):
            attempts.append({'source': source['id'], 'status': 'BLOCKED_SCHEMA', 'detail': 'Verify source request, response shape and field semantics'})
    if need['capability'] == 'daily':
        return report('DISCOVER_DAILY_SOURCE', discovery={
            'queries': [need['name']+' '+need['contract']+' 期货 日线 数据 API 官方 文档',
                        'site:github.com/akfamily/akshare futures_zh_daily_sina',
                        'site:tushare.pro fut_daily'],
            'required': ['Host actively searches primary docs and opens candidate sources',
                         'Probe a small real request; verify contract, dates, OHLC, units, limits and continuous/adjustment semantics',
                         'Record evidence and a read-only source entry, then rerun; no invented keys or automatic purchase',
                         'If no candidate works, retain actual failed attempts and exact data gaps']})
    return report('NO_USABLE_SOURCE')


def daily(root, product, contract, first, last, settings):
    need = request_need(product, 'daily', first, last, contract)
    builtin = {'id': 'builtin-tushare-daily', 'provider': 'tushare', 'api': 'fut_daily',
               'params': {'ts_code': need['contract'], 'start_date': need['start_date'], 'end_date': need['end_date']},
               'fields': '', 'evidence': 'https://tushare.pro/document/2?doc_id=138',
               'daily': {'series_type': 'actual_contract', 'price_unit': 'unknown', 'adjustment': 'none',
                         'volume_unit': '手', 'amount_unit': '万元',
                         'columns': {'date': 'trade_date', 'contract': 'ts_code', 'open': 'open', 'high': 'high', 'low': 'low',
                                     'close': 'close', 'settle': 'settle', 'volume': 'vol', 'open_interest': 'oi', 'amount': 'amount'}}}
    # Provider-specific contract format must be verified, not guessed from product alone.
    if not re.fullmatch(re.escape(need['symbol'])+r'\d{3,4}\.'+re.escape(need['exchange']), need['contract']): builtin = None
    return route(root, need, settings, builtin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True); parser.add_argument('--sources')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    q = sub.add_parser('daily'); q.add_argument('--commodity', required=True); q.add_argument('--contract', required=True)
    q.add_argument('--start', required=True); q.add_argument('--end', required=True)
    q = sub.add_parser('request'); q.add_argument('--commodity', required=True); q.add_argument('--capability', required=True)
    q.add_argument('--start', required=True); q.add_argument('--end', required=True); q.add_argument('--contract', default='')
    q = sub.add_parser('resolve-mcp'); q.add_argument('--request-id', required=True); q.add_argument('--status', required=True)
    q.add_argument('--file'); q.add_argument('--call-evidence', required=True)
    args = parser.parse_args()
    try:
        root = workspace(args.work)
        if args.command == 'init':
            dest = root/'data-sources.json'
            write_once(dest, read_json(Path(__file__).resolve().parents[1]/'templates/data-sources.example.json'))
            result = {'status': 'CONFIG_CREATED', 'path': str(dest)}
        elif args.command == 'resolve-mcp': result = resolve_mcp(root, args.request_id, args.status, args.file, args.call_evidence)
        else:
            settings = config(root, args.sources)
            if args.command == 'daily': result = daily(root, args.commodity, args.contract, args.start, args.end, settings)
            else: result = route(root, request_need(args.commodity, args.capability, args.start, args.end, args.contract), settings)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({'status': 'BLOCKED_CONFIG', 'detail': 'Check local source configuration, paths and command arguments; no credentials should be pasted into files'})); return 2

if __name__ == '__main__': raise SystemExit(main())
