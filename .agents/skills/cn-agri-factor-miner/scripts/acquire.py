#!/usr/bin/env python3
"""Acquire evidence and data before hypotheses; append-only receipts, no approvals."""
import argparse
import csv
import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import uuid
from pit import AsOf, IntegrityError, number, timestamp
from records import canonical, digest, read_json, write_once
from providers import ProviderError, choice, download, public_url, tushare
from sources import PROFILES, make_plan

ROOT = Path(__file__).resolve().parents[1]


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_config(value):
    if isinstance(value, dict):
        for k,v in value.items():
            if re.search(r'token|password|secret|api_key|credential', k, re.I):
                raise ValueError('Credentials must be configured outside acquisition files')
            safe_config(v)
    elif isinstance(value, list):
        for v in value: safe_config(v)


def workspace(path):
    p = Path(path).expanduser().resolve()
    if p == ROOT or ROOT in p.parents: raise ValueError('Acquisition must be outside the skill directory')
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_blob(root, data):
    sha = hashlib.sha256(data).hexdigest()
    p = root / 'raw' / (sha + '.bin')
    p.parent.mkdir(exist_ok=True)
    if p.exists():
        if p.read_bytes() != data: raise IntegrityError('Raw archive hash collision/mutation')
    else:
        with p.open('xb') as f: f.write(data)
    return {'path': str(p.relative_to(root)), 'sha256': sha, 'bytes': len(data)}


def archive(root, task, data, media_type, retrieved_at=None, metadata=None):
    safe_config(task)
    retrieval = retrieved_at or now()
    timestamp(retrieval)
    receipt = {'id': uuid.uuid4().hex, 'task': task, 'request_hash': digest(task),
               'retrieved_at': retrieval, 'media_type': media_type,
               'raw': save_blob(root, data), 'metadata': metadata or {}, 'status': 'FETCHED'}
    write_once(root / 'receipts' / (receipt['id'] + '.json'), receipt)
    return receipt


def receipts(root):
    result = []
    for p in sorted((root/'receipts').glob('*.json')):
        r = read_json(p)
        if r['id'] != p.stem: raise IntegrityError('Receipt id mismatch')
        raw = (root/r['raw']['path']).resolve()
        if root.resolve() not in raw.parents: raise IntegrityError('Archive path escapes acquisition')
        if hashlib.sha256(raw.read_bytes()).hexdigest() != r['raw']['sha256']:
            raise IntegrityError('Source snapshot changed: ' + r['id'])
        result.append(r)
    return sorted(result, key=lambda r: r['retrieved_at'])


def capture(root, url, title='', role='context'):
    task = {'provider':'public_web', 'url':public_url(url), 'title':title, 'role':role}
    data, meta = download(url)
    return archive(root, task, data, meta['content_type'], metadata=meta)


def fetch(root, plan, extra_tasks=None, refresh=False, sources_path=None):
    tasks = (extra_tasks or []) + plan['tasks']
    if len(tasks)>40: raise ValueError('At most 40 API queries per acquisition plan; narrow scope')
    safe_config(tasks)
    from source_router import config, request_need, route
    settings = config(root, sources_path)
    prior = {r['request_hash']:r for r in receipts(root)}
    outcomes = []
    for task in tasks:
        capability = task.get('capability') or {'fut_wsr': 'warehouse', 'fut_basic': 'contracts', 'fut_daily': 'daily'}.get(task.get('api'))
        configured = capability and task.get('commodity') and (not settings.get('allow_builtin', True) or any(
            s.get('enabled', True) and s['capability'] == capability and (not s.get('commodities') or task['commodity'] in s['commodities'])
            for s in settings['sources']))
        if configured:
            need = request_need(task['commodity'], capability, plan['start'], plan['end'], task.get('params', {}).get('ts_code', ''))
            routed = route(root, need, settings, task, refresh=refresh)
            outcomes.append(dict(routed, task=task['id']))
            continue
        key = digest(task)
        if key in prior and not refresh:
            outcomes.append({'task':task['id'], 'status':'CACHED', 'receipt_id':prior[key]['id']}); continue
        try:
            if task['provider']=='tushare': rows=tushare(task, plan['limits']['pages_per_request'])
            elif task['provider']=='choice':
                with contextlib.redirect_stdout(sys.stderr): rows=choice(task)
            elif task['provider']=='public_web':
                r=capture(root,task['url'],task.get('title',''),task.get('role','context'))
                outcomes.append({'task':task['id'],'status':'FETCHED','receipt_id':r['id']}); continue
            else: raise ValueError('Unsupported provider')
            r=archive(root,task,canonical(rows).encode(), 'application/json')
            prior[key]=r
            outcomes.append({'task':task['id'],'status':'FETCHED' if rows else 'EMPTY','rows':len(rows),'receipt_id':r['id']})
        except ProviderError as e:
            outcomes.append({'task':task['id'],'status':e.status,'detail':e.detail})
        except ValueError as e:
            outcomes.append({'task':task['id'],'status':'BLOCKED_SCHEMA','detail':type(e).__name__+'; verify provider query and returned schema'})
        except (ImportError, AttributeError) as e:
            outcomes.append({'task':task['id'],'status':'BLOCKED_ENVIRONMENT','detail':type(e).__name__+'; consult provider setup/version docs'})
    report={'created_at':now(),'outcomes':outcomes,'note':'FETCHED is not PIT-verified; failed sources do not prevent other sources.'}
    write_once(root/'attempts'/(uuid.uuid4().hex+'.json'),report)
    return report


def table(root, receipt):
    data=(root/receipt['raw']['path']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=receipt['raw']['sha256']: raise IntegrityError('Raw snapshot changed')
    if 'json' in receipt['media_type']:
        obj=json.loads(data)
        if not isinstance(obj,list) or any(not isinstance(r,dict) for r in obj):
            raise ValueError('Import a JSON array of row objects; unwrap connector envelopes first')
        return obj
    if 'csv' in receipt['media_type']: return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    raise ValueError('For PDFs/HTML archive evidence; extract a cited table to CSV/JSON before normalization')


def date_value(value):
    text=str(value).strip()
    if re.fullmatch(r'\d{8}',text): return dt.datetime.strptime(text,'%Y%m%d').date().isoformat()
    return dt.date.fromisoformat(text[:10].replace('/', '-')).isoformat()


def numeric(value):
    if isinstance(value,bool) or value is None: raise ValueError('missing/non-numeric value')
    try: return number(float(str(value).replace(',','')))
    except (ValueError, TypeError): raise ValueError('missing/non-numeric value') from None


def base_record(receipt, field, start, end, value, unit, kind='realization', source=None):
    return {'field':field,'period_start':start,'period_end':end,'published_at':None,
            'available_at':receipt['retrieved_at'],'first_seen_at':receipt['retrieved_at'],
            'source':source or receipt['task']['provider'], 'revision':0,'kind':kind,'unit':unit,'value':value,
            'availability_basis':'first_seen','event_id':digest([receipt['raw']['sha256'],field,start,end]),
            'receipt_id':receipt['id'],'raw_sha256':receipt['raw']['sha256'],
            'historical_pit_eligible':False}


def warehouse_records(root, receipt):
    task=receipt['task']
    if task.get('api')!='fut_wsr' or task.get('commodity') not in PROFILES: raise ValueError('Expected commodity-scoped fut_wsr receipt')
    symbol=PROFILES[task['commodity']][1]
    records, rejected, seen = [], [], {}
    for idx,row in enumerate(table(root,receipt)):
        try:
            if str(row.get('symbol','')).upper()!=symbol: raise ValueError('symbol mismatch')
            if row.get('exchange') and row['exchange']!=PROFILES[task['commodity']][2]: raise ValueError('exchange mismatch')
            unit=row.get('unit')
            if unit not in ('吨','手','张','tonne'): raise ValueError('unknown warehouse unit; no guessed conversion')
            date=date_value(row['trade_date'])
            # Preserve warehouse and classification dimensions; never add subtotal to detail.
            grain={k:row.get(k) for k in ('warehouse','wh_id','area','year','grade','brand','place','is_ct')}
            if not grain['warehouse'] and not grain['wh_id']: raise ValueError('warehouse grain missing')
            field='registered_receipts_'+task['commodity']+'_'+digest(grain)[:12]
            r=base_record(receipt,field,date,date,numeric(row['vol']),unit,source='tushare:fut_wsr')
            r.update(grain=grain, commodity=task['commodity'], role='registered_receipts_not_total_inventory')
            AsOf([r])
            key=(field,date)
            if key in seen:
                if seen[key]['value']!=r['value'] or seen[key]['unit']!=r['unit']: raise ValueError('conflicting warehouse rows')
                continue
            seen[key]=r; records.append(r)
        except (ValueError,KeyError) as e:
            rejected.append({'row':idx,'reason':str(e)})
    if rejected:
        # Ambiguous source schema must not create a partly complete inventory panel.
        return {'records':[],'quarantine':rejected,'status':'BLOCKED_SCHEMA'}
    return {'records':records,'quarantine':[],'status':'NORMALIZED_FIRST_SEEN' if records else 'EMPTY'}


def mapped_records(root, receipt, mapping):
    """Declarative table mapping: no eval/code, no implicit fill or timestamp guesses."""
    safe_config(mapping)
    records,rejected=[],[]
    for idx,row in enumerate(table(root,receipt)):
        for m in mapping['fields']:
            if any(str(row.get(k))!=str(v) for k,v in m.get('filters',{}).items()): continue
            try:
                field=m['field']
                if not re.fullmatch(r'[a-z][a-z0-9_]*',field): raise ValueError('invalid field name')
                start=date_value(row[m.get('period_start_column',m.get('date_column'))])
                end=date_value(row[m.get('period_end_column',m.get('date_column'))])
                unit=row[m['unit_column']] if 'unit_column' in m else m['unit']
                if not isinstance(unit,str) or not unit.strip(): raise ValueError('explicit unit required')
                r=base_record(receipt,field,start,end,numeric(row[m['value_column']]),unit,m.get('kind','realization'),m['source'])
                product=m.get('commodity',mapping.get('commodity'))
                if product not in PROFILES: raise ValueError('Explicit agricultural commodity ID required in mapping')
                r['commodity']=product
                if m.get('input_rule'): r['input_rule']=m['input_rule']
                mode=mapping.get('availability','first_seen')
                if mode=='documented_vintage':
                    if not mapping.get('vintage_evidence'): raise ValueError('archived vintage evidence required')
                    pub=row[mapping['publication_column']]; avail=row[mapping['availability_column']]
                    if timestamp(avail)>timestamp(receipt['retrieved_at']): raise ValueError('availability exceeds retrieval')
                    rev=row[mapping['revision_column']]
                    if isinstance(rev,bool) or not str(rev).isdigit(): raise ValueError('nonnegative integer source revision required')
                    r.update(published_at=pub,available_at=avail,revision=int(rev),availability_basis='observed',
                             historical_pit_eligible=True,vintage_evidence=mapping['vintage_evidence'])
                elif mode!='first_seen': raise ValueError('unsupported availability mode')
                if mapping.get('text_extraction'):
                    required=('source_excerpt','source_url','extraction_version','model_version','prompt_hash','archived_input_hash','retrospective_llm')
                    extraction=mapping['text_extraction']
                    if any(k not in extraction for k in required) or type(extraction.get('retrospective_llm')) is not bool:
                        raise ValueError('incomplete text extraction provenance')
                    originals=[x for x in receipts(root) if x['raw']['sha256']==extraction['archived_input_hash']]
                    if not originals or not extraction['source_excerpt']:
                        raise ValueError('text extraction must cite an archived source and nonempty excerpt')
                    if not any(extraction['source_url'] in (x['task'].get('url'),x['metadata'].get('url')) for x in originals):
                        raise ValueError('text extraction URL does not match source archive')
                    r.update(extraction,text_derived=True)
                AsOf([r]); records.append(r)
            except (ValueError,KeyError,TypeError) as e: rejected.append({'row':idx,'field':m.get('field'),'reason':str(e)})
    try: AsOf(records)
    except ValueError as e: rejected.append({'reason':str(e)})
    if rejected: return {'records':[],'quarantine':rejected,'status':'BLOCKED_SCHEMA'}
    return {'records':records,'quarantine':[],'status':'NORMALIZED' if records else 'EMPTY'}


def normalize(root, receipt_id, mapping=None):
    receipt=next(r for r in receipts(root) if r['id']==receipt_id)
    result=mapped_records(root,receipt,mapping) if mapping else warehouse_records(root,receipt)
    result.update(receipt_id=receipt_id,mapping=mapping or 'warehouse-v1',created_at=now())
    path=root/'normalized'/(uuid.uuid4().hex+'.json')
    write_once(path,result)
    return {'artifact':str(path),**{k:v for k,v in result.items() if k!='records'},'record_count':len(result['records'])}


def collect(root):
    known={r['id']:r for r in receipts(root)}
    records,seen=[],{}
    for p in sorted((root/'normalized').glob('*.json')):
        bundle=read_json(p)
        if bundle['receipt_id'] not in known: raise IntegrityError('Normalization without source receipt')
        r=known[bundle['receipt_id']]
        # Re-run the declarative transform and compare, rather than trusting an editable output.
        expected=warehouse_records(root,r) if bundle['mapping']=='warehouse-v1' else mapped_records(root,r,bundle['mapping'])
        if bundle['records']!=expected['records']: raise IntegrityError('Normalized data differs from archived source')
        for row in bundle['records']:
            key=canonical(row)
            if key not in seen: records.append(row);seen[key]=True
    # Multiple first-seen captures are observation vintages, ordered by capture time, not by file name.
    grouped={}
    for row in records:
        key=tuple(row[k] for k in ('field','source','period_start','period_end','kind'))
        grouped.setdefault(key,[]).append(row)
    result=[]
    for rows in grouped.values():
        bases={r['availability_basis'] for r in rows}
        if 'first_seen' in bases and len(bases)>1: raise IntegrityError('Do not mix archive and first-seen mappings for one series')
        for revision,row in enumerate(sorted(rows,key=lambda r:(r['available_at'],r['event_id']))):
            if row['availability_basis']=='first_seen': row=dict(row,revision=revision)
            result.append(row)
    AsOf(result)
    return result


def evidence(root, entry):
    safe_config(entry)
    for k in ('query','url','title','publisher','role','finding','supports','contradicts','publication_time','receipt_id'):
        if k not in entry: raise ValueError('Evidence missing '+k)
    public_url(entry['url'])
    if entry['role'] not in ('primary','secondary','rumor','context'): raise ValueError('Invalid evidence role')
    if entry['publication_time'] is not None: timestamp(entry['publication_time'])
    known={r['id']:r for r in receipts(root)}
    if entry['receipt_id'] not in known: raise ValueError('Archive the accessed page/table before registering evidence')
    receipt=known[entry['receipt_id']]
    if receipt['task'].get('url') and entry['url'] not in (receipt['task']['url'],receipt['metadata'].get('url')):
        raise ValueError('Evidence URL does not match archived page')
    for item in entry.get('coverage',[]):
        if item.get('commodity') not in PROFILES or not item.get('field') or not item.get('detail'):
            raise ValueError('Evidence coverage needs commodity, field and qualification detail')
        if item.get('status') not in ('EVIDENCE_ONLY','UNVERIFIED_PERIOD','UNVERIFIED_UNIT','UNVERIFIED_SAMPLE'):
            raise ValueError('Invalid evidence-only coverage status')
    entry=dict(entry,id=digest(entry),registered_at=now(),raw_sha256=known[entry['receipt_id']]['raw']['sha256'])
    write_once(root/'evidence'/(entry['id']+'.json'),entry)
    return entry


def search_log(root, entry):
    for key in ('query','tool','searched_at','outcome','result_urls'):
        if key not in entry: raise ValueError('Search log missing '+key)
    timestamp(entry['searched_at'])
    if entry.get('plan_search_ids'):
        valid={q['id'] for q in read_json(root/'plan.json')['searches']}
        if not isinstance(entry['plan_search_ids'],list) or not set(entry['plan_search_ids'])<=valid:
            raise ValueError('Unknown plan_search_ids')
    if entry['outcome'] not in ('RESULTS','NO_RESULTS','BLOCKED_TOOL','BLOCKED_NETWORK'):
        raise ValueError('Invalid search outcome')
    for url in entry['result_urls']: public_url(url)
    safe_config(entry)
    write_once(root/'searches'/(uuid.uuid4().hex+'.json'),entry)
    return {'status':'SEARCH_RECORDED','query':entry['query']}


def inventory(root, paths):
    """Record actual inspected workspace inputs without reading hidden credential files."""
    files=[]
    for value in paths:
        p=Path(value).expanduser().resolve()
        if not p.exists(): files.append({'path':str(p),'status':'MISSING'});continue
        candidates=sorted(p.rglob('*')) if p.is_dir() else [p]
        for f in candidates:
            if len(files)>=1000: raise ValueError('Discovery file budget reached; choose narrower data directories')
            if f.is_file() and not f.is_symlink() and not any(x.startswith('.') for x in f.relative_to(p if p.is_dir() else p.parent).parts) and f.suffix.lower() in ('.csv','.json','.jsonl','.xlsx','.parquet','.md'):
                files.append({'path':str(f),'bytes':f.stat().st_size,'status':'LOCATED_NOT_PARSED'})
    report={'created_at':now(),'files':files,'note':'Locations only. Inspect data dictionaries, existing factors, corrections and dates before mapping. Do not recursively scan account/home credentials.'}
    write_once(root/'discovery'/(uuid.uuid4().hex+'.json'),report)
    return report


def brief(root, plan):
    data=collect(root)
    sources=receipts(root)
    ev=[read_json(p) for p in sorted((root/'evidence').glob('*.json'))]
    fields={}
    for row in data:
        item=fields.setdefault(row['field'],{'source':row['source'],'unit':row['unit'],'commodity':row['commodity'],'records':0,'period_start':row['period_start'],'period_end':row['period_end'],'first_available':row['available_at'],'historical_pit_eligible':True})
        if item['unit']!=row['unit'] or item['source']!=row['source'] or item['commodity']!=row['commodity']: raise IntegrityError('Field has mixed source/unit; name separately')
        item['records']+=1;item['period_start']=min(item['period_start'],row['period_start']);item['period_end']=max(item['period_end'],row['period_end'])
        item['first_available']=min(item['first_available'],row['available_at'])
        item['historical_pit_eligible'] &= row['availability_basis']=='observed'
    searched={e['query'] for e in ev}
    search_attempts=[read_json(p) for p in (root/'searches').glob('*.json')]
    searched.update(x['query'] for x in search_attempts if x['outcome'] in ('RESULTS','NO_RESULTS'))
    searched_ids={ident for x in search_attempts if x['outcome'] in ('RESULTS','NO_RESULTS') for ident in x.get('plan_search_ids',[])}
    coverage={}
    for e in ev:
        for item in e.get('coverage',[]): coverage.setdefault((item['commodity'],item['field']),[]).append(dict(item,evidence_id=e['id']))
    gaps=[]
    for n in plan['fundamental_needs']:
        support=coverage.get((n['commodity'],n['field']),[])
        acquired=n['field'] in fields and fields[n['field']]['commodity']==n['commodity']
        gaps.append(dict(n,status='ACQUIRED' if acquired else 'EVIDENCE_ONLY' if support else 'NOT_ACQUIRED',qualifications=support))
    source_routes = [read_json(p) for p in sorted((root/'routing').glob('*.json'))]
    market = []
    for path in sorted((root/'market').glob('*.json')):
        daily_data = read_json(path)
        market.append({'path':str(path),'receipt_id':daily_data['receipt_id'],'rows':len(daily_data['bars'])})
    report={'source_routes':source_routes,'market_daily':market,'market_needs':plan.get('market_needs',[]),'created_at':now(),'commodities':plan['commodities'],'sources':len(sources),'evidence':ev,'fields':fields,
            'fundamental_gaps':gaps,'search_attempts':search_attempts,'pending_searches':[q for q in plan['searches'] if q['query'] not in searched and q['id'] not in searched_ids],
            'candidate_instruction':'Propose at most six evidence-linked hypotheses after source review. Preserve missing fields, contrary evidence and nearest factors. Registered receipts are not social/port inventory. Pause before factor computation.',
            'status':'READY_FOR_HYPOTHESES' if data or ev else 'BLOCKED_DATA',
            'historical_backtest_ready':False,'note':'Per-field PIT eligibility does not establish calendar/contract/split/evaluator completeness.'}
    directory=root/'briefs'/uuid.uuid4().hex
    write_once(directory/'data-availability.json',report)
    lines=['# 数据发现与因子研究简报','', '状态：'+report['status'],f'已归档来源：{len(sources)}；已记录证据：{len(ev)}；数值字段：{len(fields)}','',
           '先根据原始来源提出有限候选，并记录反证。尚未执行因子计算或外部评估。','', '## 字段与时点','',
           '|字段|数量|单位|观察期末|最早可用时间|历史时点证据|','|---|---:|---|---|---|---|']
    for f,v in fields.items(): lines.append(f"|{f}|{v['records']}|{v['unit']}|{v['period_end']}|{v['first_available']}|{v['historical_pit_eligible']}|")
    lines+=['','## 缺口','']+[g['commodity']+': '+g['field']+' — '+g['status'] for g in gaps]
    lines+=['','## 来源证据','']+[e['title']+' — '+e['url']+'\n'+e['finding']+'\n反证/局限：'+e['contradicts'] for e in ev]
    lines+=['','## 下一步','',report['candidate_instruction'],'检索清单中尚未完成的查询及逐字段信息见 data-availability.json。']
    (directory/'research-brief.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'status':report['status'],'directory':str(directory),'numeric_records':len(data),'fields':len(fields),'pending_searches':len(report['pending_searches'])}


def export(root, destination, manifest_path, catalog_path, corrections_path):
    records=collect(root)
    if not records: raise ValueError('No normalized numeric data to export')
    manifest=read_json(manifest_path)
    if manifest.get('synthetic') is not False: raise ValueError('Real acquisition must use synthetic=false')
    manifest['discovery_audit']={'acquisition':str(root),'source_receipts':[r['id'] for r in receipts(root)],
       'discovery':[str(p) for p in (root/'discovery').glob('*.json')],
       'evidence':[str(p) for p in (root/'evidence').glob('*.json')],
       'prior_audit':manifest.get('discovery_audit')}
    dictionary={}
    for r in records:
        if r['commodity'] not in manifest['commodity_group']['members']: raise ValueError('Acquired commodity differs from export manifest')
        rule={'source':r['source'],'unit':r['unit'],'kind':r['kind'],'max_release_age_days':10,'max_observation_age_days':14}
        rule.update(r.get('input_rule',{}))
        if (rule['source'],rule['unit'],rule['kind'])!=(r['source'],r['unit'],r['kind']): raise ValueError('Input rule cannot change source/unit/kind')
        if r['kind']=='forecast' and (type(rule.get('target_days')) is not int or rule['target_days']<=0):
            raise ValueError('Forecast mapping needs an explicit positive input_rule.target_days')
        if r['field'] in dictionary and dictionary[r['field']]!=rule: raise IntegrityError('Mixed field semantics')
        dictionary[r['field']]=rule
    destination=workspace(destination)
    for name,value in [('manifest',manifest),('predictors',records),('data_dictionary',dictionary),('existing_factors',read_json(catalog_path)),('human_corrections',read_json(corrections_path))]:
        write_once(destination/(name+'.json'),value)
    return {'status':'EXPORTED_FOR_REVIEW','inputs':str(destination),'records':len(records),'note':'Set field freshness to source cadence before init; first-seen records remain ineligible before capture.'}


def start(root, commodities, first, last, extra_tasks=None, refresh=False, sources_path=None):
    plan=make_plan(commodities,first,last)
    path=root/'plan.json'
    if path.exists():
        if read_json(path)!=plan: raise ValueError('Existing acquisition has a different plan; use a new work directory')
    else: write_once(path,plan)
    attempt=fetch(root,plan,extra_tasks,refresh,sources_path)
    done={read_json(p)['receipt_id'] for p in (root/'normalized').glob('*.json')}
    normalizations=[]
    for r in receipts(root):
        if r['task'].get('api')=='fut_wsr' and r['media_type']=='application/json' and r['id'] not in done:
            normalizations.append(normalize(root,r['id']))
        elif r['task'].get('mapping') and r['media_type']=='application/json' and r['id'] not in done:
            normalizations.append(normalize(root,r['id'],r['task']['mapping']))
    return {'attempt':attempt,'normalizations':normalizations,'brief':brief(root,plan),
            'next':'Host agent must resolve pending MCP handoffs, fetch daily context via source_router.py daily after contract verification, execute source searches, inspect evidence and propose hypotheses; this CLI does not replace the host LLM.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',required=True);p.add_argument('--sources')
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('plan');q.add_argument('--commodity',nargs='+',required=True);q.add_argument('--start',required=True);q.add_argument('--end',required=True)
    q=sub.add_parser('start');q.add_argument('--commodity',nargs='+',required=True);q.add_argument('--start',required=True);q.add_argument('--end',required=True);q.add_argument('--extra-tasks');q.add_argument('--refresh',action='store_true')
    q=sub.add_parser('fetch');q.add_argument('--extra-tasks');q.add_argument('--refresh',action='store_true')
    q=sub.add_parser('capture');q.add_argument('--url',required=True);q.add_argument('--title',default='');q.add_argument('--role',default='context')
    q=sub.add_parser('import-table');q.add_argument('--file',required=True);q.add_argument('--task',required=True);q.add_argument('--format',choices=['json','csv'],required=True)
    q=sub.add_parser('normalize');q.add_argument('--receipt',required=True);q.add_argument('--mapping')
    q=sub.add_parser('evidence');q.add_argument('--file',required=True)
    q=sub.add_parser('search-log');q.add_argument('--file',required=True)
    q=sub.add_parser('inventory');q.add_argument('paths',nargs='+')
    sub.add_parser('brief')
    q=sub.add_parser('export');q.add_argument('--output',required=True);q.add_argument('--manifest',required=True);q.add_argument('--catalog',required=True);q.add_argument('--corrections',required=True)
    args=p.parse_args()
    try:
        root=workspace(args.work)
        if args.command=='plan':
            result=make_plan(args.commodity,args.start,args.end);write_once(root/'plan.json',result)
        elif args.command=='start': result=start(root,args.commodity,args.start,args.end,read_json(args.extra_tasks) if args.extra_tasks else None,args.refresh,args.sources)
        elif args.command=='fetch': result=fetch(root,read_json(root/'plan.json'),read_json(args.extra_tasks) if args.extra_tasks else None,args.refresh,args.sources)
        elif args.command=='capture': result=capture(root,args.url,args.title,args.role)
        elif args.command=='import-table':
            result=archive(root,read_json(args.task),Path(args.file).read_bytes(),'application/json' if args.format=='json' else 'text/csv',metadata={'transport':'host_connector_or_local_file','availability':'first_seen_at_import_unless_documented_archive'})
        elif args.command=='normalize': result=normalize(root,args.receipt,read_json(args.mapping) if args.mapping else None)
        elif args.command=='evidence': result=evidence(root,read_json(args.file))
        elif args.command=='search-log': result=search_log(root,read_json(args.file))
        elif args.command=='inventory': result=inventory(root,args.paths)
        elif args.command=='brief': result=brief(root,read_json(root/'plan.json'))
        else: result=export(root,args.output,args.manifest,args.catalog,args.corrections)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,OSError,StopIteration) as e:
        detail=e.detail if isinstance(e,ProviderError) else str(e)
        print(json.dumps({'status':getattr(e,'status','BLOCKED_DATA'),'detail':detail},ensure_ascii=False));return 2

if __name__=='__main__': raise SystemExit(main())
