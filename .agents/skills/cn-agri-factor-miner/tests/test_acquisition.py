import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import acquire
from pit import AsOf, BlockedData, IntegrityError
from providers import ProviderError, tushare, choice
from sources import make_plan
from records import canonical

class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.task={'id':'meal','provider':'tushare','api':'fut_wsr','commodity':'soybean_meal','params':{'symbol':'M'},'fields':''}
        self.raw=[{'trade_date':'20260918','symbol':'M','warehouse':'甲仓库','wh_id':'1','vol':100,'unit':'吨'}]
    def receipt(self,rows=None,at='2026-09-22T01:00:00+00:00'):
        return acquire.archive(self.root,self.task,canonical(self.raw if rows is None else rows).encode(),'application/json',at)
    def test_profiles_scope_and_real_requests(self):
        p=make_plan(['豆粕','豆油'],'2026-09-01','2026-09-21')
        self.assertEqual(p['commodities'],['soybean_meal','soybean_oil'])
        self.assertEqual(p['tasks'][0]['params']['symbol'],'M')
        self.assertTrue(any('moa.gov.cn' in q['query'] for q in p['searches']))
        with self.assertRaises(ValueError): make_plan(['铜'],'2026-09-01','2026-09-21')
    def test_first_seen_never_backdates_historical_data(self):
        r=self.receipt();rows=acquire.warehouse_records(self.root,r)['records'];row=rows[0]
        self.assertIsNone(row['published_at']);self.assertEqual(row['availability_basis'],'first_seen')
        rule={'source':row['source'],'unit':'吨','kind':'realization','max_release_age_days':10,'max_observation_age_days':14}
        store=AsOf(rows)
        with self.assertRaises(BlockedData):store.latest(row['field'],rule,'2026-09-19T00:00:00+00:00')
        self.assertEqual(store.latest(row['field'],rule,'2026-09-22T02:00:00+00:00')['value'],100)
    def test_first_seen_requires_receipt_and_capture_time(self):
        r=acquire.warehouse_records(self.root,self.receipt())['records'][0]
        r['available_at']='2026-09-18T01:00:00+00:00'
        with self.assertRaises(IntegrityError):AsOf([r])
    def test_warehouse_grain_no_sum_or_conversion(self):
        rows=self.raw+[dict(self.raw[0],warehouse='合计',wh_id='',vol=100)]
        normalized=acquire.warehouse_records(self.root,self.receipt(rows))['records']
        self.assertEqual(len(normalized),2);self.assertNotEqual(normalized[0]['field'],normalized[1]['field'])
        bad=[dict(self.raw[0],unit='未知')]
        self.assertEqual(acquire.warehouse_records(self.root,self.receipt(bad))['status'],'BLOCKED_SCHEMA')
    def test_schema_failures_do_not_silently_drop_bad_data(self):
        for row in [dict(self.raw[0],symbol='Y'),dict(self.raw[0],vol=None),dict(self.raw[0],vol='NaN'),dict(self.raw[0],vol=True)]:
            result=acquire.warehouse_records(self.root,self.receipt([row]))
            self.assertEqual(result['records'],[]);self.assertTrue(result['quarantine'])
    def test_conflicts_and_identical_reposts(self):
        self.assertEqual(len(acquire.warehouse_records(self.root,self.receipt(self.raw*2))['records']),1)
        result=acquire.warehouse_records(self.root,self.receipt(self.raw+[dict(self.raw[0],vol=101)]))
        self.assertEqual(result['status'],'BLOCKED_SCHEMA')
    def test_append_only_cache_and_refresh_vintages(self):
        p=make_plan(['豆粕'],'2026-09-18','2026-09-18');p['tasks']=[self.task]
        with patch('acquire.tushare',return_value=self.raw) as call:
            a=acquire.fetch(self.root,p);b=acquire.fetch(self.root,p)
            self.assertEqual(call.call_count,1);self.assertEqual(b['outcomes'][0]['status'],'CACHED')
            call.return_value=[dict(self.raw[0],vol=110)]
            c=acquire.fetch(self.root,p,refresh=True);self.assertEqual(call.call_count,2)
        for r in acquire.receipts(self.root):acquire.normalize(self.root,r['id'])
        records=acquire.collect(self.root)
        self.assertEqual([r['revision'] for r in records],[0,1]);self.assertEqual([r['value'] for r in records],[100,110])
    def test_raw_and_normalized_tamper_blocked(self):
        r=self.receipt();n=acquire.normalize(self.root,r['id']);p=Path(n['artifact'])
        x=json.loads(p.read_text());x['records'][0]['value']=999;p.write_text(json.dumps(x))
        with self.assertRaises(IntegrityError):acquire.collect(self.root)
        (self.root/r['raw']['path']).write_text('changed')
        with self.assertRaises(IntegrityError):acquire.receipts(self.root)
    def test_tushare_pagination_and_secret_never_in_receipt(self):
        payloads=[]
        def transport(p):
            payloads.append(p)
            return {'code':0,'data':{'fields':['id'],'items':[[i] for i in range(1000)] if p['params']['offset']==0 else [[1001]]}}
        with patch.dict(os.environ,{'TUSHARE_TOKEN':'unit-test-secret'}):
            rows=tushare(self.task,transport=transport)
        self.assertEqual(len(rows),1001);self.assertEqual(len(payloads),2)
        r=self.receipt(rows)
        self.assertNotIn('unit-test-secret',json.dumps(r))
    def test_missing_auth_provider_failure_and_page_budget(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ProviderError) as e:tushare(self.task)
            self.assertEqual(e.exception.status,'BLOCKED_AUTH')
        with patch.dict(os.environ,{'TUSHARE_TOKEN':'unit-test-secret'}):
            with self.assertRaises(ProviderError) as e:tushare(self.task,transport=lambda p:{'code':-1,'msg':'unit-test-secret'})
            self.assertNotIn('unit-test-secret',str(e.exception))
            response={'code':0,'data':{'fields':['id'],'items':[[i] for i in range(1000)]}}
            with self.assertRaises(ProviderError):tushare(self.task,max_pages=1,transport=lambda p:response)
            with self.assertRaises(ProviderError):tushare(self.task,transport=lambda p:response)
    def test_one_source_failure_keeps_other_results(self):
        p=make_plan(['豆粕'],'2026-09-18','2026-09-18')
        with patch('acquire.tushare',side_effect=[ProviderError('BLOCKED_AUTH','missing'),self.raw]):
            report=acquire.fetch(self.root,p)
        self.assertEqual([x['status'] for x in report['outcomes']],['BLOCKED_AUTH','FETCHED'])
    def mapping(self):
        return {'commodity':'soybean_meal','fields':[{'field':'meal_stock','source':'public-table','date_column':'date','value_column':'stock','unit':'tonne'}]}
    def test_csv_normalization_and_explicit_historical_vintage(self):
        data=b'date,stock,published,available,revision\n2026-09-18,125,2026-09-18T08:00:00+08:00,2026-09-18T09:00:00+08:00,0\n'
        r=acquire.archive(self.root,{'provider':'csv'},data,'text/csv','2026-09-22T01:00:00+00:00')
        m=self.mapping()
        self.assertEqual(acquire.mapped_records(self.root,r,m)['records'][0]['availability_basis'],'first_seen')
        m.update(availability='documented_vintage',publication_column='published',availability_column='available',revision_column='revision')
        self.assertEqual(acquire.mapped_records(self.root,r,m)['status'],'BLOCKED_SCHEMA')
        m['vintage_evidence']='Source archived release dated September 18; see immutable source receipt'
        row=acquire.mapped_records(self.root,r,m)['records'][0]
        self.assertTrue(row['historical_pit_eligible']);self.assertEqual(row['published_at'],'2026-09-18T08:00:00+08:00')
    def test_text_extraction_needs_provenance(self):
        r=acquire.archive(self.root,{'provider':'csv'},b'date,stock\n2026-09-18,125\n','text/csv','2026-09-22T01:00:00+00:00')
        m=self.mapping();m['text_extraction']={'model_version':'example'}
        self.assertEqual(acquire.mapped_records(self.root,r,m)['status'],'BLOCKED_SCHEMA')
    def test_evidence_requires_archive_and_no_fake_search_completion(self):
        p=make_plan(['豆粕'],'2026-09-18','2026-09-18')
        result=acquire.brief(self.root,p)
        self.assertEqual(result['status'],'BLOCKED_DATA');self.assertGreater(result['pending_searches'],0)
        entry={'query':p['searches'][0]['query'],'url':'https://example.org/report','title':'source','publisher':'example','role':'primary','finding':'A fact','supports':'hypothesis','contradicts':'sample incomplete','publication_time':None,'receipt_id':'missing'}
        with self.assertRaises(ValueError):acquire.evidence(self.root,entry)
        r=acquire.archive(self.root,{'provider':'public_web','url':entry['url']},b'<p>A fact</p>','text/html')
        entry['receipt_id']=r['id'];acquire.evidence(self.root,entry)
        result=acquire.brief(self.root,p);self.assertEqual(result['status'],'READY_FOR_HYPOTHESES')
        self.assertEqual(result['pending_searches'],len(p['searches'])-1)
    def test_secret_config_and_skill_output_rejected(self):
        with self.assertRaises(ValueError): acquire.safe_config({'token':'hidden'})
        with self.assertRaises(ValueError): acquire.workspace(acquire.ROOT/'bad-output')
    def test_choice_readonly_shape_logout_and_mapping(self):
        try:import pandas as pd
        except ImportError:self.skipTest('optional Choice pandas runtime unavailable')
        class Fake:
            def __init__(self):self.stopped=False
            def start(self,options):return type('Login',(),{'ErrorCode':0})()
            def csd(self,*args):self.args=args;return pd.DataFrame([{'DATES':'2026-09-18','FTREGORDERVOL':'100'}],index=pd.Index(['M.TEST'],name='CODES'))
            def stop(self):self.stopped=True
        c=Fake();task={'api':'csd','args':['M.TEST','FTREGORDERVOL','2026-09-18','2026-09-18'],'mapping_evidence':'TEST_ONLY'}
        rows=choice(task,c);self.assertEqual(rows[0]['FTREGORDERVOL'],'100');self.assertTrue(c.stopped)
        self.assertIn('Ispandas=1',c.args[-1])
        with self.assertRaises(ValueError):choice(dict(task,api='order'),c)
    def test_export_flows_into_existing_run_without_approval(self):
        from workflow import Run
        r=self.receipt();acquire.normalize(self.root,r['id'])
        skill=Path(__file__).resolve().parents[1]
        manifest=json.loads((skill/'examples/manifest.json').read_text());manifest['synthetic']=False
        mp=self.root/'real-manifest.json';mp.write_text(json.dumps(manifest))
        out=self.root/'inputs';acquire.export(self.root,out,mp,skill/'examples/existing_factors.json',skill/'examples/human_corrections.json')
        run=Run(self.root/'run')
        state=run.init(*[json.loads((out/(n+'.json')).read_text()) for n in ('manifest','predictors','existing_factors','human_corrections','data_dictionary')])
        self.assertFalse(state['manifest']['synthetic']);self.assertFalse(state['proposed'])
        self.assertTrue(all(x['status']=='missing' for x in json.loads((run.path/'data-availability.json').read_text())['fields']))

    def test_first_seen_future_invariance_safeguard(self):
        from factors import future_invariance,compute
        row=acquire.warehouse_records(self.root,self.receipt())['records'][0]
        spec={'formula':{'field':row['field']},'input_fields':{row['field']:{'source':row['source'],'unit':row['unit'],'kind':'realization','max_release_age_days':10,'max_observation_age_days':14}}}
        self.assertTrue(future_invariance(spec,[row],'2026-09-22T02:00:00+00:00','2026-09-21T00:00:00+00:00'))
        self.assertFalse(compute(spec,AsOf([row]),'2026-09-22T02:00:00+00:00')['verified_pit'])
    def test_start_automates_fetch_normalization_and_cache(self):
        with patch('acquire.tushare',return_value=self.raw) as query:
            report=acquire.start(self.root,['豆粕'],'2026-09-18','2026-09-18')
            self.assertEqual(report['brief']['numeric_records'],1)
            self.assertEqual(len(report['normalizations']),1)
            again=acquire.start(self.root,['豆粕'],'2026-09-18','2026-09-18')
            self.assertEqual(query.call_count,2);self.assertEqual(again['normalizations'],[])
        with self.assertRaises(ValueError):acquire.start(self.root,['豆油'],'2026-09-18','2026-09-18')
    def test_choice_date_format_normalizes_without_time_fabrication(self):
        row={'date':'2026/09/18','stock':100}
        r=self.receipt([row]);result=acquire.mapped_records(self.root,r,self.mapping())
        self.assertEqual(result['records'][0]['period_end'],'2026-09-18')
        self.assertIsNone(result['records'][0]['published_at'])
    def test_search_no_result_logged_and_blocked_search_remains_pending(self):
        plan=make_plan(['豆粕'],'2026-09-18','2026-09-18')
        log={'query':plan['searches'][0]['query'],'tool':'test-search','searched_at':'2026-09-22T01:00:00+00:00','outcome':'BLOCKED_TOOL','result_urls':[]}
        acquire.search_log(self.root,log)
        self.assertEqual(acquire.brief(self.root,plan)['pending_searches'],len(plan['searches']))
        acquire.search_log(self.root,dict(log,outcome='NO_RESULTS'))
        self.assertEqual(acquire.brief(self.root,plan)['pending_searches'],len(plan['searches'])-1)

    def test_alternative_query_links_to_plan_without_faking_query(self):
        from records import write_once
        plan=make_plan(['豆粕'],'2026-09-18','2026-09-18');write_once(self.root/'plan.json',plan)
        entry={'query':'实际执行的不同关键词','plan_search_ids':[plan['searches'][0]['id']],'tool':'search','searched_at':'2026-09-22T01:00:00+00:00','outcome':'RESULTS','result_urls':['https://example.org/report']}
        acquire.search_log(self.root,entry)
        self.assertEqual(acquire.brief(self.root,plan)['pending_searches'],len(plan['searches'])-1)
        with self.assertRaises(ValueError):acquire.search_log(self.root,dict(entry,plan_search_ids=['invented']))
    def test_unverified_stock_evidence_is_not_missing_or_numeric(self):
        plan=make_plan(['豆粕'],'2026-09-18','2026-09-18')
        r=acquire.archive(self.root,{'provider':'public_web','url':'https://example.org/report'},b'report says stock but no observation date','text/plain')
        entry={'query':'stock','url':'https://example.org/report','title':'source','publisher':'publisher','role':'secondary','finding':'stock without observation date','supports':'a hypothesis','contradicts':'date unknown','publication_time':None,'receipt_id':r['id'],'coverage':[{'commodity':'soybean_meal','field':'meal_stock','status':'UNVERIFIED_PERIOD','detail':'No exact observation cutoff'}]}
        acquire.evidence(self.root,entry)
        b=acquire.brief(self.root,plan);self.assertEqual(b['numeric_records'],0)
        report=json.loads((Path(b['directory'])/'data-availability.json').read_text())
        gap=next(x for x in report['fundamental_gaps'] if x['field']=='meal_stock')
        self.assertEqual(gap['status'],'EVIDENCE_ONLY');self.assertEqual(gap['qualifications'][0]['status'],'UNVERIFIED_PERIOD')

if __name__=='__main__':unittest.main()
