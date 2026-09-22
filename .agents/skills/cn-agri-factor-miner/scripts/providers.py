"""Read-only providers. Tokens stay in memory, never in artifacts or errors."""
import datetime as dt
import json
import os
import urllib.request
from urllib.parse import urlparse

class ProviderError(ValueError):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(status + ': ' + detail)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('BLOCKED_NETWORK', 'API redirect refused')


def public_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Use an HTTPS URL without embedded credentials')
    if any(k in p.query.lower() for k in ('token=', 'api_key=', 'password=', 'secret=')):
        raise ValueError('Credential-bearing URLs must not be archived')
    return url


def download(url, maximum=20000000):
    public_url(url)
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'cn-agri-factor-miner/0.3 (research source archiver)'})
        with urllib.request.urlopen(request, timeout=25) as r:
            final = public_url(r.geturl())
            data = r.read(maximum + 1)
            if len(data) > maximum: raise ProviderError('BLOCKED_SIZE', 'Download exceeds configured size limit')
            return data, {'url': final, 'content_type': r.headers.get('Content-Type', ''), 'http_status': r.status}
    except ProviderError: raise
    except Exception as exc: raise ProviderError('BLOCKED_NETWORK', type(exc).__name__) from None


TUSHARE_APIS = {'fut_wsr', 'fut_basic', 'fut_daily', 'fut_mapping', 'trade_cal'}

def tushare(task, max_pages=10, transport=None):
    if task['api'] not in TUSHARE_APIS: raise ValueError('Unsupported read-only Tushare API')
    token = os.environ.get('TUSHARE_TOKEN')
    if not token: raise ProviderError('BLOCKED_AUTH', 'TUSHARE_TOKEN absent; use the host Tushare connector or configure it locally')
    def send(payload):
        req = urllib.request.Request('https://api.tushare.pro', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=25) as r:
                data = r.read(20000001)
                if len(data)>20000000: raise ProviderError('BLOCKED_SIZE', 'API response too large')
                return json.loads(data)
        except ProviderError: raise
        except Exception as exc: raise ProviderError('BLOCKED_NETWORK', type(exc).__name__) from None
    transport = transport or send
    rows, seen = [], set()
    for page in range(max_pages):
        params = dict(task['params'], limit=1000, offset=page * 1000)
        response = transport({'api_name': task['api'], 'token': token, 'params': params, 'fields': task.get('fields', '')})
        if response.get('code') != 0:
            # Upstream text can echo credentials. Keep only the code.
            raise ProviderError('BLOCKED_PROVIDER', 'Tushare error code ' + str(response.get('code')) + '; check entitlement/rate limit/parameters')
        table = response.get('data') or {}
        columns, items = table.get('fields', []), table.get('items', [])
        if not columns and items: raise ProviderError('BLOCKED_SCHEMA', 'Missing Tushare fields')
        for values in items:
            if len(columns) != len(values): raise ProviderError('BLOCKED_SCHEMA', 'Tushare row width mismatch')
            row = dict(zip(columns, values))
            signature = json.dumps(row, sort_keys=True, ensure_ascii=False)
            if signature in seen: raise ProviderError('BLOCKED_PAGINATION', 'Repeated row/page; completeness unproven')
            seen.add(signature); rows.append(row)
        if len(items) < 1000: return rows
    raise ProviderError('BLOCKED_PAGINATION', 'Page budget reached; narrow the date range (no partial success)')


def choice(task, client=None):
    """Use an already installed/activated SDK; never install, activate, or force-login."""
    method = task['api']
    if method not in ('csd', 'ctr', 'edb', 'edbquery'): raise ValueError('Unsupported read-only Choice method')
    args = task.get('args', [])
    expected = {'csd':4, 'ctr':2, 'edb':1, 'edbquery':2}[method]
    if len(args) != expected or not all(isinstance(x,str) for x in args): raise ValueError('Choice argument count/type mismatch')
    if not task.get('mapping_evidence'): raise ValueError('Choice query requires mapping_evidence (verified indicator meaning and unit)')
    options = task.get('options', '')
    if not isinstance(options,str) or any(k in options.lower() for k in ('password', 'username', 'forcelogin', 'token')): raise ValueError('No credentials in query options')
    # Guarantee pandas option appears after another field for ctr's SDK parser.
    if 'ispandas' in options.lower(): raise ValueError('Ispandas is managed by the adapter')
    if 'recvtimeout=' not in options.lower(): options = (options + ',' if options else '') + 'RECVtimeout=20'
    options = options + ',Ispandas=1'
    if client is None:
        try: from EmQuantAPI import c as client
        except ImportError: raise ProviderError('BLOCKED_ENVIRONMENT', 'Choice EmQuantAPI is not installed in this Python; use the installed Choice skill setup') from None
    try: import pandas as pd
    except ImportError: raise ProviderError('BLOCKED_ENVIRONMENT', 'Choice adapter requires pandas') from None
    login = client.start('ForceLogin=0,HTTPTimeout=20')
    if login.ErrorCode:
        raise ProviderError('BLOCKED_AUTH', 'Choice login code ' + str(login.ErrorCode) + '; do not retry or force another session offline')
    try:
        result = getattr(client, method)(*args, options)
        if not isinstance(result, pd.DataFrame):
            raise ProviderError('BLOCKED_PROVIDER', 'Choice query code ' + str(getattr(result,'ErrorCode','unknown')))
        # Named columns only; retain index identifiers and dates in raw JSON.
        result = result.reset_index()
        return json.loads(result.to_json(orient='records', date_format='iso', force_ascii=False))
    finally:
        client.stop()
