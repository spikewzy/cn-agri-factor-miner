import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import acquire
import source_router as router
from providers import ProviderError
from records import canonical, read_json
from sources import make_plan


class SourceRoutingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.need = router.request_need('豆粕', 'daily', '2026-09-01', '2026-09-21', 'M2701.DCE')
        self.rows = [{'date': '2026-09-18', 'symbol': 'M2701.DCE', 'open': 10, 'high': 12, 'low': 9, 'close': 11, 'vol': 100}]
        self.source = {'id': 'my-api', 'provider': 'http', 'capability': 'daily', 'read_only': True,
            'request': {'url': 'https://example.com/daily', 'params': {'symbol': '{contract}'}},
            'response': {}, 'evidence': 'local verified documentation',
            'daily': {'series_type': 'actual_contract', 'price_unit': 'CNY/tonne', 'adjustment': 'none',
                'columns': {'date': 'date', 'contract': 'symbol', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'vol'}}}
        self.settings = {'schema_version': 1, 'sources': [self.source], 'allow_builtin': True}
    def run_route(self, rows=None, **kwargs):
        with patch.object(router, 'http', return_value=canonical(self.rows if rows is None else rows).encode()):
            return router.route(self.root, self.need, self.settings, **kwargs)
    def mcp(self):
        self.source.update(provider='mcp', server='my-data', tool='get_daily', arguments={'symbol': '{contract}'})
    def test_user_source_preempts_builtin(self):
        with patch.object(router, 'tushare', side_effect=AssertionError('Must not call builtin')):
            result = self.run_route(builtin={'id': 'builtin', 'provider': 'tushare'})
        self.assertEqual(result['source'], 'my-api'); self.assertEqual(len(result['attempts']), 1)
    def test_failure_then_next_source_and_all_fail_discovery(self):
        self.settings['sources'].append(dict(self.source, id='second'))
        with patch.object(router, 'http', side_effect=[ProviderError('BLOCKED_AUTH', 'absent'), canonical(self.rows).encode()]):
            result = router.route(self.root, self.need, self.settings)
        self.assertEqual(result['source'], 'second'); self.assertEqual(result['attempts'][0]['status'], 'BLOCKED_AUTH')
        with patch.object(router, 'http', side_effect=ProviderError('BLOCKED_AUTH', 'absent')):
            result = router.route(self.root, self.need, self.settings, refresh=True)
        self.assertEqual(result['status'], 'DISCOVER_DAILY_SOURCE'); self.assertTrue(result['discovery']['queries'])
    def test_no_provider_returns_actionable_host_discovery(self):
        result = router.daily(self.root, '豆粕', 'M2701.DCE', '2026-09-01', '2026-09-21', {'sources': [], 'allow_builtin': False})
        self.assertEqual(result['status'], 'DISCOVER_DAILY_SOURCE'); self.assertEqual(result['attempts'], [])
    def test_absent_builtin_token_also_triggers_host_discovery(self):
        with patch.dict(os.environ, {}, clear=True):
            result = router.daily(self.root, '豆粕', 'M2701.DCE', '2026-09-01', '2026-09-21', {'sources': []})
        self.assertEqual(result['status'], 'DISCOVER_DAILY_SOURCE')
        self.assertEqual(result['attempts'][0]['status'], 'BLOCKED_AUTH')

    def test_disabled_and_other_commodity_sources_not_called(self):
        self.source['commodities'] = ['soybean_oil']
        with patch.object(router, 'http', side_effect=AssertionError):
            self.assertEqual(router.route(self.root, self.need, self.settings)['status'], 'DISCOVER_DAILY_SOURCE')
        self.source.pop('commodities'); self.source['enabled'] = False
        with patch.object(router, 'http', side_effect=AssertionError):
            self.assertEqual(router.route(self.root, self.need, self.settings)['status'], 'DISCOVER_DAILY_SOURCE')
    def test_mcp_pauses_before_fallback_and_resolution_resumes(self):
        self.mcp(); self.settings['sources'].append(dict(self.source, id='later', provider='http'))
        with patch.object(router, 'http', side_effect=AssertionError('Unattempted MCP must have priority')):
            pending = router.route(self.root, self.need, self.settings)
        self.assertEqual(pending['status'], 'PAUSED_MCP')
        handoff = read_json(pending['handoff'])
        self.assertEqual(handoff['task']['arguments']['symbol'], 'M2701.DCE')
        data = self.root/'response.json'; data.write_text(canonical(self.rows))
        router.resolve_mcp(self.root, pending['request_id'], 'SUCCESS', data, 'test-fixture: simulated tool return, not live MCP')
        result = router.route(self.root, self.need, self.settings)
        self.assertEqual(result['status'], 'CACHED'); self.assertEqual(result['source'], 'my-api')
        with self.assertRaises(ValueError): router.resolve_mcp(self.root, pending['request_id'], 'EMPTY', call_evidence='duplicate')
    def test_mcp_real_failure_allows_next_source(self):
        self.mcp(); self.settings['sources'].append(dict(self.source, id='later', provider='http'))
        pending = router.route(self.root, self.need, self.settings)
        router.resolve_mcp(self.root, pending['request_id'], 'BLOCKED_TOOL', call_evidence='test-fixture: no matching tool')
        result = self.run_route()
        self.assertEqual(result['source'], 'later'); self.assertEqual(result['attempts'][0]['status'], 'BLOCKED_TOOL')
    def test_invalid_mcp_result_does_not_create_success(self):
        self.mcp(); pending = router.route(self.root, self.need, self.settings)
        data = self.root/'bad.json'; data.write_text('{"error":"not rows"}')
        with self.assertRaises(ValueError): router.resolve_mcp(self.root, pending['request_id'], 'SUCCESS', data, 'fixture')
        self.assertEqual(router.route(self.root, self.need, self.settings)['status'], 'PAUSED_MCP')
    def test_mcp_binding_tampering_rejected(self):
        self.mcp(); pending = router.route(self.root, self.need, self.settings)
        handoff = read_json(pending['handoff']); handoff['task']['tool'] = 'different'
        Path(pending['handoff']).write_text(canonical(handoff))
        with self.assertRaises(ValueError): router.resolve_mcp(self.root, pending['request_id'], 'EMPTY', call_evidence='fixture')
    def test_header_query_body_auth_and_no_credential_in_archive(self):
        for place in ('header', 'query', 'body'):
            source = copy.deepcopy(self.source)
            source['auth'] = {'env': 'TEST_DATA_KEY', 'in': place, 'name': 'Authorization', 'prefix': 'Bearer '}
            if place == 'body': source['request']['method'] = 'POST'
            with patch.dict(os.environ, {'TEST_DATA_KEY': 'sensitive-example-test-key'}):
                def transport(req):
                    parts = str(req.headers) + req.full_url + str(req.data)
                    self.assertIn('sensitive-example-test-key', parts)
                    return canonical(self.rows).encode()
                data = router.http(source, transport)
                acquire.archive(self.root, source, data, 'application/json')
        all_text = ''.join(p.read_text() for p in self.root.rglob('*') if p.is_file())
        self.assertNotIn('sensitive-example-test-key', all_text)
    def test_echoed_credentials_and_network_error_sanitized(self):
        self.source['auth'] = {'env': 'TEST_DATA_KEY', 'in': 'header', 'name': 'X-Key'}
        with patch.dict(os.environ, {'TEST_DATA_KEY': 'sensitive-example-test-key'}):
            with self.assertRaises(ProviderError) as result:
                router.http(self.source, lambda req: b'{"echo":"sensitive-example-test-key"}')
            self.assertEqual(result.exception.status, 'BLOCKED_SECRET_ECHO')
            def fail(req): raise OSError('sensitive-example-test-key')
            with self.assertRaises(ProviderError) as result: router.http(self.source, fail)
            self.assertNotIn('sensitive-example-test-key', str(result.exception))
    def test_literal_keys_headers_and_missing_config_rejected(self):
        path = self.root/'data-sources.json'
        path.write_text(canonical({'schema_version': 1, 'sources': [], 'api_key': 'bad'}))
        with self.assertRaises(ValueError): router.config(self.root)
        with self.assertRaises(ValueError): router.config(self.root, self.root/'missing.json')
        self.source['request']['headers'] = {'Authorization': 'literal'}
        with self.assertRaises(ValueError): router.http(self.source)
    def test_decode_formats_pagination_and_jsonp_never_execute(self):
        expected = [{'date': '2026-09-18', 'close': '1'}]
        self.assertEqual(router.decode(b'date,close\n2026-09-18,1\n', {'format':'csv'}), expected)
        self.assertEqual(router.decode(b'/*<script>bad()</script>*/ var x=([{"close":1}]);', {'format':'jsonp'}), [{'close': 1}])
        with self.assertRaises(ValueError): router.decode(b'var x=(bad());', {'format':'jsonp'})
        with self.assertRaises(ProviderError): router.decode(b'[{"close":1}]', {'row_limit':1})
        self.assertEqual(router.decode(b'{"data":{"rows":[[1,2]]}}', {'rows_path':['data','rows'], 'columns':['a','b']}), [{'a':1,'b':2}])
    def test_daily_invalid_ohlc_and_conflicting_rows_fall_through(self):
        for rows in ([dict(self.rows[0], high=9)], self.rows+[dict(self.rows[0], close=10)], [dict(self.rows[0], symbol='Y2701.DCE')], [dict(self.rows[0], close='NaN')]):
            result = self.run_route(rows, refresh=True)
            self.assertEqual(result['status'], 'DISCOVER_DAILY_SOURCE')
            self.assertEqual(result['attempts'][0]['status'], 'BLOCKED_SCHEMA')
    def test_daily_first_seen_separate_missing_fields_and_continuous(self):
        result = self.run_route(self.rows*2)
        doc = read_json(result['daily_file'])
        self.assertEqual(len(doc['bars']), 1); self.assertIsNone(doc['bars'][0]['settle'])
        self.assertFalse(doc['historical_backtest_ready']); self.assertTrue(doc['first_seen_at'])
        self.assertEqual(acquire.collect(self.root), [])
        need = dict(self.need, contract='M0')
        with self.assertRaises(ValueError): router.daily_rows(self.rows, self.source, need)
        self.source['daily']['series_type'] = 'continuous'
        self.source['daily']['columns'].pop('contract')
        self.assertEqual(len(router.daily_rows(self.rows, self.source, need)), 1)
    def test_missing_range_is_empty_and_declared_alias_supported(self):
        self.assertEqual(router.daily_rows([dict(self.rows[0], date='2020-01-01')], self.source, self.need), [])
        self.source['daily']['contract_value'] = 'M2701'
        self.assertEqual(len(router.daily_rows([dict(self.rows[0], symbol='M2701')], self.source, self.need)), 1)
    def test_acquisition_configured_contract_source_precedes_tushare(self):
        source = copy.deepcopy(self.source); source.update(capability='contracts')
        (self.root/'data-sources.json').write_text(canonical({'schema_version':1,'sources':[source]}))
        plan = make_plan(['豆粕'], '2026-09-01', '2026-09-21'); plan['tasks'] = [plan['tasks'][1]]
        with patch.object(router,'http',return_value=b'[{"contract":"M2701.DCE"}]'), patch.object(acquire,'tushare',side_effect=AssertionError):
            result = acquire.fetch(self.root,plan)
        self.assertEqual(result['outcomes'][0]['source'], 'my-api')
    def test_builtin_disabled_for_existing_acquisition(self):
        (self.root/'data-sources.json').write_text(canonical({'schema_version':1,'sources':[],'allow_builtin':False}))
        with patch.object(acquire,'tushare',side_effect=AssertionError):
            result = acquire.fetch(self.root, make_plan(['豆粕'],'2026-09-01','2026-09-21'))
        self.assertTrue(all(x['status']=='NO_USABLE_SOURCE' for x in result['outcomes']))
    def test_http_fundamental_mapping_keeps_original_envelope(self):
        self.source.update(capability='inventory', response={'rows_path':['data']}, mapping={'availability':'first_seen','commodity':'soybean_meal','fields':[
            {'field':'meal_stock','date_column':'date','value_column':'stock','unit':'tonne','source':'my-api','commodity':'soybean_meal'}]})
        need = dict(self.need, capability='inventory')
        with patch.object(router,'http',return_value=b'{"data":[{"date":"2026-09-18","stock":10}]}'):
            result = router.route(self.root,need,self.settings)
        self.assertEqual(result['status'],'FETCHED')
        receipt = next(r for r in acquire.receipts(self.root) if r['id']==result['receipt_id'])
        self.assertIn('derived_from',receipt['metadata'])
        normalized = acquire.normalize(self.root,receipt['id'],self.source['mapping'])
        self.assertEqual(normalized['status'],'NORMALIZED')
        self.assertEqual(acquire.collect(self.root)[0]['field'],'meal_stock')

if __name__ == '__main__': unittest.main()
