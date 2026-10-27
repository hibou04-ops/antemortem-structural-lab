"""Authorized real-project QA with private callbacks and a once-only final ledger.

Only reviewed, pinned suites may be loaded. Generators receive declared public
specifications and development archives; final callbacks never enter a worker.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal,localcontext
from fractions import Fraction
import hashlib,importlib.util,json,os,statistics,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'docs/E7_EVALUATION_CONTRACT.json'
FINAL_AUTHORITY=ROOT.parent/'e7-evaluation'
METHODS=('NativeHypothesis','NativeStateful','E6','E7')
SEEDS=(11,37,73)
RETIRED_ORACLE_SUITE_SHA256=frozenset({'02ca6e20e3f511e9063ae805aa7d75ead06ddee34537ff474a9de8da9af5f0f1'})
class EvaluationStop(BaseException):pass
class OracleEvaluationError(BaseException):
 """Evaluator failure must escape the product's approved target-exception adapter."""
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def exact_centered(values):
 """Exact binary-float centering; never infer zero from rounded arithmetic."""
 xs=[Fraction.from_float(float(x)) for x in values]
 if not xs:raise ValueError('exact centering requires nonempty values')
 mean=sum(xs,Fraction(0))/len(xs)
 centered=[x-mean for x in xs]
 return centered,sum((x*x for x in centered),Fraction(0))

def rational_sqrt(value):
 """Approximate only the final square root, after exact sign/zero decisions."""
 value=Fraction(value)
 if value<0:raise ValueError('square root requires nonnegative rational')
 with localcontext() as context:
  context.prec=100
  return float((Decimal(value.numerator)/Decimal(value.denominator)).sqrt())

def exact_correlation(a,b,epsilon=Fraction(0)):
 if len(a)!=len(b) or not a:raise ValueError('aligned nonempty series required')
 da,va=exact_centered(a);db,vb=exact_centered(b);epsilon=Fraction(epsilon)
 ca=va<epsilon if epsilon else va==0;cb=vb<epsilon if epsilon else vb==0
 if ca or cb:return None,ca,cb
 covariance=sum((x*y for x,y in zip(da,db)),Fraction(0))
 magnitude=rational_sqrt(covariance*covariance/(va*vb))
 return -magnitude if covariance<0 else magnitude,False,False

def final_target_set_identity(reviewed):
 """Pinned production identity, independent of Oracle, aliases and bundles."""
 identities=[]
 for row in reviewed['reviewed']:
  if row['split']!='final':continue
  identity={key:row[key] for key in ('project','revision','path','function_ast_sha256')}
  if not identity['function_ast_sha256']:raise ValueError('missing original final function AST identity')
  identities.append(canonical(identity))
 if not identities:raise ValueError('empty final target set')
 return digest({'schema':'e7-pinned-final-target-set-v1','targets':sorted(set(identities))})

def oracle_identity(suite_path):
 return digest({'suite_sha256':sha(suite_path),'math_helper_evaluator_sha256':sha(__file__)})
def save(path,x):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def reject_retired_suite(path):
 if sha(path) in RETIRED_ORACLE_SUITE_SHA256:
  raise ValueError('retired v1 suite has a known invalid Oracle; execution is forbidden')
def module(path):
 reject_retired_suite(path)
 s=importlib.util.spec_from_file_location('e7_private_'+sha(path),path)
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def product_hashes(root):
 root=Path(root)
 names=[*root.glob('tomolab/**/*.py'),root/'pyproject.toml',root/'scripts/evaluate-e7.py',CONTRACT]
 return {p.relative_to(root).as_posix():sha(p) for p in sorted(set(names)) if p.is_file() and p.is_relative_to(root)}
def baseline_hashes(root):
 root=Path(root)
 return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.glob('tomolab/**/*.py'))}
def verify_baseline(root):
 root=Path(root).resolve();expected=read(CONTRACT)['baseline_commit']
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()
 if head!=expected:raise ValueError('baseline HEAD is not the preregistered E6 commit')
 paths=subprocess.check_output(['git','ls-tree','-r','--name-only',expected,'tomolab'],cwd=root).decode().splitlines()
 frozen={p:hashlib.sha256(subprocess.check_output(['git','show',expected+':'+p],cwd=root)).hexdigest() for p in paths if p.endswith('.py')}
 if baseline_hashes(root)!=frozen:raise ValueError('baseline runtime differs from the E6 Git blobs')
 return frozen
def external_output(path):
 path=Path(path).resolve()
 if path.is_relative_to(ROOT):raise ValueError('raw evaluation output must remain outside the public repository')
 return path
def verify_suite(path):
 path=Path(path).resolve();reject_retired_suite(path);c=read(CONTRACT)
 if c.get('evaluation_generation')!=2 or c.get('oracle_repair_review',{}).get('status')!='PASS':raise ValueError('generation-v2 Oracle review and preregistration are incomplete')
 if c.get('oracle_math_helper_evaluator_sha256')!=sha(__file__):raise ValueError('reviewed independent math helper identity changed')
 if sha(path)!=c['private_suite_sha256']:raise ValueError('reviewed suite identity changed')
 reviewed=path.parent/'REVIEWED_SOURCES.json'
 if sha(reviewed)!=c['reviewed_source_manifest_sha256']:raise ValueError('reviewed provenance changed')
 for row in read(reviewed)['reviewed']:
  p=path.parent/'reviewed'/row['extracted_file']
  if sha(p)!=row['extracted_sha256']:raise ValueError('reviewed production function drift')
 if final_target_set_identity(read(reviewed))!=c['final_target_set_identity']:raise ValueError('reviewed final target identity changed')
 return c
def verify_final(manifest,suite,baseline_root=None):
 m=read(manifest)
 if digest({k:v for k,v in m.items() if k!='manifest_sha256'})!=m['manifest_sha256']:raise ValueError('freeze receipt mismatch')
 if baseline_root is not None and Path(baseline_root).resolve()!=Path(m['baseline_root']).resolve():raise ValueError('baseline override differs from frozen baseline')
 if Path(suite).resolve()!=Path(m['suite']).resolve():raise ValueError('suite path differs from frozen suite')
 identity=final_target_set_identity(read(Path(suite).resolve().parent/'REVIEWED_SOURCES.json'))
 if m['final_target_set_identity']!=identity or read(CONTRACT)['final_target_set_identity']!=identity:raise ValueError('final target set identity differs')
 if m['execution_claim']!=str(authoritative_claim_path(identity)):raise ValueError('final execution authority differs')
 verify_suite(suite)
 if sha(CONTRACT)!=m['contract_sha256'] or product_hashes(ROOT)!=m['product']:raise ValueError('frozen product or contract drift')
 if baseline_hashes(m['baseline_root'])!=m['baseline']:raise ValueError('baseline drift')
 if sha(m['archives'])!=m['archives_sha256']:raise ValueError('source knowledge archive drift')
 if sha(suite)!=m['suite_sha256']:raise ValueError('suite drift')
 if m['oracle_identity']!=oracle_identity(suite):raise ValueError('frozen suite and reference math identity differs')
 return m
def begin_once(path,event):
 p=Path(path)
 with p.open('x',encoding='utf-8',newline='\n') as f:
  f.write(canonical({'event':'START',**event})+'\n');f.flush();os.fsync(f.fileno())
def complete_once(path,event):
 p=Path(path);rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
 if len(rows)!=1 or rows[0]['event']!='START':raise ValueError('once-only ledger is not open')
 with p.open('a',encoding='utf-8',newline='\n') as f:
  f.write(canonical({'event':'COMPLETE',**event})+'\n');f.flush();os.fsync(f.fileno())
def authoritative_claim_path(target_set_identity):
 if len(target_set_identity)!=64 or any(ch not in '0123456789abcdef' for ch in target_set_identity):raise ValueError('invalid frozen target set identity')
 return FINAL_AUTHORITY.resolve()/('FINAL_CONSUMED-'+target_set_identity+'.jsonl')
def claim_final(manifest,output):
 m=read(manifest);authority=authoritative_claim_path(m['final_target_set_identity']);authority.parent.mkdir(parents=True,exist_ok=True)
 if str(authority)!=m['execution_claim']:raise ValueError('frozen execution authority mismatch')
 event={'manifest_sha256':sha(manifest),'suite_sha256':m['suite_sha256'],'final_target_set_identity':m['final_target_set_identity'],'contract_sha256':m['contract_sha256'],'output':str(Path(output).resolve())}
 # The original pinned target set remains consumed after any suite/Oracle change.
 begin_once(authority,event)
 ledger=Path(manifest).resolve().parent/'FINAL_LEDGER.jsonl';begin_once(ledger,event)
 return authority,ledger
def full_grid(rows,cases,methods=METHODS,seeds=SEEDS):
 expected={(c,m,s) for c in cases for m in methods for s in seeds}
 observed=[(r['case'],r['method'],r['seed']) for r in rows]
 return len(observed)==len(expected) and set(observed)==expected and len(set(observed))==len(observed)
def verdict(rows,qualified_usage,source_cost=0.):
 required=[r for r in rows if r['method'] in ('NativeHypothesis','E6','E7')]
 if any(r['status']!='COMPLETE' or r.get('false_alerts',0) or r.get('source_drift',False) for r in required):return {'status':'INCONCLUSIVE','reason':'execution-control-or-source-gate'}
 per={m:[r for r in required if r['method']==m] for m in ('NativeHypothesis','E6','E7')}
 families={m:{r['case'] for r in group if r.get('found')} for m,group in per.items()}
 if not any(families.values()):return {'status':'INCONCLUSIVE','reason':'no-comparable-positive-mechanism','qualified_use':qualified_usage}
 comps=[]
 for baseline in ('NativeHypothesis','E6'):
  by={(r['case'],r['seed']):r for r in per[baseline]};pairs=[(r,by[(r['case'],r['seed'])]) for r in per['E7']]
  ratios=[a['wall_seconds']/b['wall_seconds'] for a,b in pairs if b['wall_seconds']>0]
  first_ratios=[a['first_failure_seconds']/b['first_failure_seconds'] for a,b in pairs if a.get('first_failure_seconds') is not None and b.get('first_failure_seconds') not in (None,0)]
  comps.append({'baseline':baseline,'paired_runs':len(pairs),'median_wall_ratio':statistics.median(ratios) if ratios else None,
   'median_first_failure_wall_ratio_conditional':statistics.median(first_ratios) if first_ratios else None,
   'no_detection_loss':families[baseline]<=families['E7'],'baseline_mechanisms':len(families[baseline]),'e7_mechanisms':len(families['E7'])})
 extra=families['E7']-set.union(families['NativeHypothesis'],families['E6'])
 all_found=all(c['no_detection_loss'] for c in comps)
 combined=sum(r['wall_seconds'] for r in per['E7'])+source_cost
 ref=sum(r['wall_seconds'] for r in per['NativeHypothesis'])
 guided_witnesses=sum(r.get('found',False) and r.get('first_witness_guided') is True and r.get('replay')=='MATCHED_TWICE' for r in per['E7'])
 benefit=bool(qualified_usage) and bool(guided_witnesses) and all_found and (bool(extra) or all(c['median_wall_ratio'] is not None and c['median_wall_ratio']<=.8 for c in comps) and combined<=.8*ref)
 return {'status':'IMPROVED' if benefit else 'NO_IMPROVEMENT','comparisons':comps,'extra_mechanisms':len(extra),
  'qualified_use':qualified_usage,'replayed_qualified_first_witness_runs':guided_witnesses,'e7_source_inclusive_wall_seconds':combined,'native_target_wall_seconds':ref,
  'reason':'preregistered marginal benefit' if benefit else 'no preregistered marginal benefit; fallback alone never improvement'}

class Meter:
 def __init__(self,suite,case,limit):
  self.suite,self.case,self.limit=suite,case,limit;self.rows=[];self.rejected=0;self.target_calls=0;self.oracle_calls=0
  self.first=None;self.first_monotonic_ns=None;self.witness=None;self.started=time.perf_counter();self.oracle_seconds=0.;self.failure_calls=0
 def failed(self,x,phase='search'):
  if not self.suite.valid(self.case,x):self.rejected+=1;return False
  if self.target_calls>=self.limit:raise EvaluationStop()
  tick=time.perf_counter()
  try:r=self.suite.compare(self.case,deepcopy(x))
  except Exception as error:raise OracleEvaluationError('independent comparison/Oracle failed; no target finding or feedback') from error
  self.oracle_seconds+=time.perf_counter()-tick
  self.oracle_calls+=1;self.target_calls+=1
  if r['failed']:
   self.failure_calls+=1
   if self.first is None:self.first=time.perf_counter()-self.started;self.first_monotonic_ns=time.monotonic_ns();self.witness=deepcopy(x)
  self.rows.append({'inputs':deepcopy(x),'failed':r['failed'],'phase':phase,'result':r,'wall_seconds':time.perf_counter()-self.started})
  return r['failed']
 def receipt(self):
  return {'actual_target_calls':self.target_calls,'actual_oracle_calls':self.oracle_calls,'actual_primitive_calls':self.target_calls+self.oracle_calls,
   'invalid_inputs_rejected_before_execution':self.rejected,'first_failure_seconds':self.first,'first_failure_monotonic_ns':self.first_monotonic_ns,'first_failure_pair_call':next((i+1 for i,r in enumerate(self.rows) if r['failed']),None),
   'found':self.witness is not None,'witness':self.witness,'oracle_seconds':self.oracle_seconds,'failed_evaluations':self.failure_calls,
   'unique_evaluated_inputs':len({canonical(r['inputs']) for r in self.rows}),
   'duplicate_evaluation_rate':1-len({canonical(r['inputs']) for r in self.rows})/len(self.rows) if self.rows else 0.,'raw':self.rows}

def source_archive(suite,case,seed,archives):
 if not archives:return None
 exact=archives.get(case['semantics']+':'+str(seed))
 if exact is not None:return exact
 # Retrieval by declared roles is only a candidate lookup; the strict semantic
 # applicability gate must still reject different operation/status policies.
 roles={i['role'] for i in suite.prepare(case)['inputs']}
 return next((a for key,a in sorted(archives.items()) if key.endswith(':'+str(seed)) and {i['role'] for i in a['spec']['inputs']}==roles),None)
def propose_or_exhausted(generator):
 try:return generator.request('propose')
 except ValueError as error:
  if str(error) in {'Hypothesis candidate pool exhausted','ValueError: Hypothesis candidate pool exhausted'}:return None
  raise
def symbolic_worker(packet,suite,case,spec,meter,directory):
 from tomolab.discovery.symbolic import check_contract
 from tomolab.discovery.schema import validate_inputs
 if case['id']=='target-05':return {'tool_status':'NOT_COMPARABLE','reason':'extracted method requires a validated model; no fake source-level standalone contract'}
 metadata=next(x for x in suite.META['reviewed'] if x['case']==case['id'])
 source=(Path(packet['suite']).parent/'reviewed'/metadata['extracted_file']).read_text(encoding='utf-8')
 k=case['id'];names=[i['name'] for i in spec['inputs']]
 annotation=lambda t:'list['+annotation(t['items'])+']' if t['kind']=='list' else {'float':'float','str':'str','int':'int'}[t['kind']]
 args=', '.join(i['name']+': '+annotation(i['type']) for i in spec['inputs'])
 conditions=[]
 for item in spec['inputs']:
  n,t=item['name'],item['type']
  if t['kind']=='list':
   conditions.append(f"{t['min_size']} <= len({n}) <= {t['max_size']}")
   if t['items']['kind']=='float':conditions.append(f"all({t['items']['min']} <= v <= {t['items']['max']} for v in {n})")
   else:conditions.append(f"all(set(v) <= set({t['items']['alphabet']!r}) and len(v) <= {t['items']['max_size']} for v in {n})")
  elif t['kind']=='str':conditions.append(f"len({n}) <= {t['max_size']} and set({n}) <= set({t['alphabet']!r})")
  else:conditions.append(f"{t['min']} <= {n} <= {t['max']}")
 if k=='target-01':conditions.append('len(set(a)) == len(a) and len(set(b)) == len(b)')
 calls={
 'source-01':'pearson_result(a,b).value','source-02':'_max_pairwise_jaccard(values)',
 'source-03':'compute_context_margin(system_prompt_chars=a,rubric_chars=b,longest_input_chars=c,longest_reference_chars=d,longest_response_chars=e,context_window_tokens=capacity,chars_per_token=4.)',
 'target-01':'compute_spearman(a,b)','target-02':'_pearson(a,b)[0]','target-03':'gini_coefficient(values)',
 'target-04':'normalize_evidence_text(text)','target-06':'noise_floor_estimate(fitness_samples=values)'}
 post='normalize_evidence_text(_) == _' if k=='target-04' else '_ <= 1.00000001' if k=='source-03' else '_ >= -0.00000001' if k=='target-06' else '(_ is None or -1.00000001 <= _ <= 1.00000001)' if k in ('source-01','target-01','target-02') else '-0.00000001 <= _ <= 1.00000001'
 code=source+'\n\ndef checked('+args+'):\n    """\n'+''.join('    pre: '+c+'\n' for c in conditions)+'    post: '+post+'\n    """\n    return '+calls[k]+'\n'
 path=Path(directory)/(case['id']+'-source-aware.py');path.write_text(code,encoding='utf-8',newline='\n')
 result=check_contract(path,'checked',timeout_seconds=3,per_condition_seconds=.6,trusted_execution=True)
 candidates=result.get('candidates',[]);accepted=0;rejected=0
 for point in candidates:
  try:validate_inputs(point,spec)
  except ValueError:rejected+=1;continue
  if not suite.valid(case,point):rejected+=1;continue
  accepted+=1;meter.failed(point,'crosshair-independent-replay')
 return {'tool_status':result['status'],'internal_symbolic_target_calls':'UNKNOWN','symbolic_source_sha256':result['source_sha256'],
  'candidate_count':len(candidates),'in_scope_candidates':accepted,'rejected_candidates':rejected,'tool_receipt':result}
def run_e6_development(spec,meter,seed):
 """Unchanged frozen E6 worker, with the reviewed host precondition enforced.

 A rejected proposal consumes generation work but is never sent to an Oracle
 or falsely labelled a refutation. Search/shrink settings remain preregistered.
 """
 from tomolab.discovery.boundary import DiscoveryBoundary
 from tomolab.discovery.hypothesis_adapter import native_find
 started=time.perf_counter();generation=0.;evidence=[]
 with DiscoveryBoundary() as generator:
  tick=time.perf_counter();generator.request('init',spec=spec,seed=seed,pool_size=128,public_ir=None,solver='enumeration');generation+=time.perf_counter()-tick
  for index in range(64):
   if time.perf_counter()-started>=10:break
   tick=time.perf_counter();point=propose_or_exhausted(generator);generation+=time.perf_counter()-tick
   if point is None:break
   if not meter.suite.valid(meter.case,point['inputs']):meter.rejected+=1;continue
   failed=meter.failed(point['inputs'])
   event={'kind':'FAILURE' if failed else 'REFUTATION','evidence_id':f'dev-{index:04}',
    'inputs':point['inputs'],'invariant':spec['contract']['invariants'][0],'category':'mismatch','signature':'reference-comparison'}
   tick=time.perf_counter();generator.request('observe',evidence=event);generation+=time.perf_counter()-tick;evidence.append(event)
  snapshot=generator.request('freeze')
 shrink={}
 if meter.witness is not None and time.perf_counter()-started<10:
  shrink=native_find(spec,lambda x:meter.failed(x,'shrink'),budget=128,seed=seed+1,time_budget=max(.001,10-(time.perf_counter()-started)),cache=False)
 witness=shrink.get('witness') or meter.witness
 if witness is not None:
  if not all(meter.failed(witness,'replay') for _ in range(2)):raise ValueError('independent E6 witness replay changed')
 return {'status':'COUNTEREXAMPLE_FOUND' if witness is not None else 'NOT_REFUTED_WITHIN_BUDGET',
  'snapshot':snapshot,'evidence':evidence,'shrink':shrink,
  'timing':{'wall_seconds':time.perf_counter()-started,'generation_and_ipc_seconds':generation,'oracle_seconds':meter.oracle_seconds},
  'precondition_rejections_never_observed':True}
def worker(packet):
 started,cpu=time.perf_counter(),time.process_time();method=packet['method'];phase=packet['phase']
 verify_suite(packet['suite'])
 root=Path(packet['baseline_root']) if method=='E6' else ROOT
 sys.path.insert(0,str(root))
 suite=module(packet['suite']);case=next(x for x in suite.cases('development' if phase=='development' else 'final') if x['id']==packet['case'])
 if phase=='development' or method=='CrossHair':suite.module(case['id']) # Configuration errors are not target defects.
 prep=time.perf_counter();spec=suite.prepare(case);origin=suite.provenance(case)
 meta=next(x for x in suite.META['reviewed'] if x['case']==case['id'])
 origin.update(implementation_sha256=meta['extracted_sha256'],oracle_sha256=oracle_identity(packet['suite']),independence_id='reviewed-'+case['id'])
 preparation=time.perf_counter()-prep
 result={'case':case['id'],'method':method,'seed':packet['seed'],'phase':phase,'status':'COMPLETE','false_alerts':0,'source_drift':False,'public_spec_sha256':digest(spec),'oracle_identity':oracle_identity(packet['suite']),'final_feedback_to_generator':0}
 if method=='NativeStateful':return {**result,'status':'NOT_COMPARABLE','reason':'reviewed production function is stateless','found':False,'actual_target_calls':0,'actual_oracle_calls':0,'actual_primitive_calls':0,'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,'raw':[]}
 meter=Meter(suite,case,256 if phase=='development' else 64)
 if method=='CrossHair':
  r=symbolic_worker(packet,suite,case,spec,meter,packet['symbolic_directory'])
  result.update(r);result.update(meter.receipt());result['status']='NOT_COMPARABLE' if r['tool_status']=='NOT_COMPARABLE' else 'COMPLETE'
  result.update(worker_wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu);return result
 from tomolab.discovery.schema import canonical as product_canonical
 from tomolab.discovery.hypothesis_adapter import generate_pool,native_find
 archives=read(packet['archives']) if packet.get('archives') else {}
 archive=source_archive(suite,case,packet['seed'],archives)
 plans=[];run=None;generation=0.;qualified=0;guided=0;guided_first=False
 def accepts(point):
  valid=suite.valid(case,point)
  if not valid:meter.rejected+=1
  return valid
 if phase=='development':
  try:
   if method=='NativeHypothesis':run=native_find(spec,lambda x:meter.failed(x),budget=256,seed=packet['seed'],time_budget=10,cache=False)
   elif method=='E6':
    run=run_e6_development(spec,meter,packet['seed'])
   else:
    from tomolab.discovery.knowledge_service import run_knowledge
    run=run_knowledge(lambda **x:meter.failed(x),lambda **x:False,spec,archive=archive,target_provenance=origin,budget=64,shrink_budget=128,pool_size=128,seed=packet['seed'],time_budget=10,trusted_execution=True,public_ir=None,input_accepts=accepts)
  except EvaluationStop:result['resource_stop']='PAIR_BUDGET'
  if run:
   if method=='E6':result['source_snapshot']=run['snapshot'];result['evidence']=run['evidence']
   result['engine_timing']=run.get('timing',{});result['engine_status']=run.get('status');result['engine_shrink']=run.get('shrinking') or run.get('shrink',{}).get('shrinking')
   result['native_predicate_attempts']=run.get('hypothesis_attempts',run.get('native',{}).get('predicate_calls',run.get('shrink',{}).get('hypothesis_attempts')))
   result['engine_metrics']=run.get('metrics',{})
   result['precondition_rejections_never_observed']=all(suite.valid(case,e['inputs']) for e in run.get('evidence',[]))
   if not result['precondition_rejections_never_observed']:raise ValueError('unexecuted rejected input was falsely observed')
   if method=='E7' and run.get('metrics',{}).get('precondition_rejected_attempts')!=meter.rejected:raise ValueError('host guard rejection accounting differs from independent meter')
 elif method=='NativeHypothesis':
  tick=time.perf_counter();plans=[{'inputs':x,'source':'NATIVE'} for x in generate_pool(spec,seed=packet['seed'],size=128)][:64];generation=time.perf_counter()-tick
 elif method=='E6':
  from tomolab.discovery.boundary import DiscoveryBoundary
  tick=time.perf_counter()
  with DiscoveryBoundary() as generator:
   generator.request('init',spec=spec,seed=packet['seed'],pool_size=128,public_ir=None,solver='enumeration')
   for _ in range(64):
    p=propose_or_exhausted(generator)
    if p is None:break
    plans.append(p)
   snapshot=generator.request('freeze');result['generator_frozen']=snapshot['frozen']
  generation=time.perf_counter()-tick;result['information_boundary']='PUBLIC_JSON_SUBPROCESS_LOGICAL_ONLY'
 else:
  from tomolab.discovery.knowledge_boundary import KnowledgeBoundary
  tick=time.perf_counter()
  with KnowledgeBoundary() as generator:
   p=generator.request('plan',archive=archive,spec=spec,target_provenance=origin,budget=64,seed=packet['seed'],pool_size=128,guidance_budget=16,public_ir=None)
   result['worker_costs']=generator.request('metrics')
  plans=p['candidates'];result['generator_frozen']=p['snapshot']['frozen'];result['gate']=p['gate'];generation=time.perf_counter()-tick
  result['information_boundary']='PUBLIC_JSON_SUBPROCESS_LOGICAL_ONLY'
  qualified=len(p['gate'].get('claims',[]));guided=sum(str(x.get('source','')).startswith('QUALIFIED') for x in plans)
 if phase=='final':
  suite.module(case['id']) # Private implementation loads only after the public plan has frozen.
  result['frozen_plan_sha256']=digest(plans);result['frozen_before_target_execution']=meter.target_calls==0;result['plan_count']=len(plans)
  result['generator_target_calls']=0;result['generator_oracle_calls']=0
  for p in plans:
   try:
    first=meter.witness is None;failed=meter.failed(p['inputs'])
    if failed and first:
     guided_first=str(p.get('source','')).startswith('QUALIFIED')
     if meter.limit-meter.target_calls>=2:
      result['replay']='MATCHED_TWICE' if all(meter.failed(meter.witness,'replay') for _ in range(2)) else 'MISMATCH'
      if result['replay']!='MATCHED_TWICE':result['status']='INCONSISTENT_REPLAY'
     else:result['status']='INCOMPLETE_REPLAY_BUDGET'
   except EvaluationStop:break
  result['qualified_claims']=qualified;result['guided_candidates']=guided;result['first_witness_guided']=guided_first
 result.update(meter.receipt());result['observed_mismatch']=result['found'];result['defect_eligible']=case.get('defect_eligible',True)
 result['false_alerts']=int(case.get('normal_control',False) and result['found'])
 if not result['defect_eligible']:result['found']=False
 result['normal_control']=case.get('normal_control',False)
 result.update(public_preparation_seconds=preparation,generation_seconds=generation,worker_wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu)
 return result

def run_packet(packet,directory,index):
 import psutil
 directory=external_output(directory);directory.mkdir(parents=True,exist_ok=True)
 inp=directory/f'packet-{index:04}.json';out=directory/f'receipt-{index:04}.json';save(inp,packet)
 environment={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP'}}
 environment['PYTHONIOENCODING']='utf-8';environment['HYPOTHESIS_STORAGE_DIRECTORY']=str(directory/'hypothesis')
 started=time.perf_counter();started_ns=time.monotonic_ns();p=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--_worker',str(inp),str(out)],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
 max_rss=0;cpu_samples={};timed_out=False
 while p.poll() is None:
  try:
   processes=[psutil.Process(p.pid),*psutil.Process(p.pid).children(recursive=True)];rss=0
   for proc in processes:
    try:
     with proc.oneshot():rss+=proc.memory_info().rss;ct=proc.cpu_times();cpu_samples[(proc.pid,proc.create_time())]=ct.user+ct.system
    except(psutil.NoSuchProcess,psutil.AccessDenied):pass
   max_rss=max(max_rss,rss)
  except(psutil.NoSuchProcess,psutil.AccessDenied):pass
  if time.perf_counter()-started>=12:
   timed_out=True;p.kill();break
  time.sleep(.01)
 stdout,stderr=p.communicate(timeout=5)
 if timed_out:result={'case':packet['case'],'method':packet['method'],'seed':packet['seed'],'phase':packet['phase'],'status':'TIMEOUT','found':False}
 elif p.returncode or not out.exists():result={'case':packet['case'],'method':packet['method'],'seed':packet['seed'],'phase':packet['phase'],'status':'ERROR','error':stderr[-4096:],'found':False}
 else:result=read(out)
 result.update(wall_seconds=time.perf_counter()-started,sampled_process_tree_cpu_lower_bound=sum(cpu_samples.values()),maximum_sampled_live_tree_rss_bytes=max_rss)
 result['first_failure_callback_elapsed_seconds']=result.get('first_failure_seconds')
 if result.get('first_failure_monotonic_ns') is not None:
  first=(result['first_failure_monotonic_ns']-started_ns)/1e9
  if not 0<=first<=result['wall_seconds']:raise ValueError('cross-process monotonic first-failure clock mismatch')
  result['first_failure_seconds']=first;result['first_failure_wall_scope']='PARENT_SPAWN_THROUGH_CONCRETE_FIRST_MISMATCH'
 save(out,result);return result

def summarize(rows):
 result=[]
 for method in METHODS:
  group=[r for r in rows if r['method']==method];valid=[r for r in group if r['status']=='COMPLETE']
  result.append({'method':method,'attempted':len(group),'complete':len(valid),'not_comparable':sum(r['status']=='NOT_COMPARABLE' for r in group),
   'errors':sum(r['status'] not in ('COMPLETE','NOT_COMPARABLE') for r in group),'control_false_alerts':sum(r.get('false_alerts',0) for r in group),
   'runs_with_mismatch':sum(bool(r.get('found')) for r in valid),'distinct_function_mechanisms':len({r['case'] for r in valid if r.get('found')}),
   'defect_eligible_runs':sum(r.get('defect_eligible',True) for r in valid),'declared_compatibility_control_runs':sum(not r.get('defect_eligible',True) for r in valid),
   'actual_target_calls':sum(r.get('actual_target_calls',0) for r in group),'actual_oracle_calls':sum(r.get('actual_oracle_calls',0) for r in group),
   'wall_seconds':sum(r['wall_seconds'] for r in group),'sampled_cpu_lower_bound':sum(r['sampled_process_tree_cpu_lower_bound'] for r in group),
   'maximum_sampled_live_tree_rss_bytes':max([r['maximum_sampled_live_tree_rss_bytes'] for r in group] or [0]),
   'conditional_median_first_failure_wall_seconds':statistics.median([r['first_failure_seconds'] for r in valid if r.get('first_failure_seconds') is not None]) if any(r.get('first_failure_seconds') is not None for r in valid) else None,
   'guided_candidates':sum(r.get('guided_candidates',0) for r in group),'first_witness_guided_runs':sum(r.get('first_witness_guided',False) for r in group),
   'duplicate_evaluation_rate_mean':statistics.mean([r['duplicate_evaluation_rate'] for r in valid]) if valid else None})
 return result

def freeze(args):
 verify_suite(args.suite);output=external_output(args.output);archives=Path(args.archives).resolve()
 if not archives.is_file():raise ValueError('completed development archives required')
 identity=final_target_set_identity(read(Path(args.suite).resolve().parent/'REVIEWED_SOURCES.json'))
 m={'schema':'tomolab-e7-final-freeze-v2','evaluation_generation':2,'suite':str(Path(args.suite).resolve()),'suite_sha256':sha(args.suite),
  'final_target_set_identity':identity,'execution_claim':str(authoritative_claim_path(identity)),'oracle_identity':oracle_identity(args.suite),
  'baseline_root':str(Path(args.baseline_root).resolve()),'baseline':verify_baseline(args.baseline_root),
  'product':product_hashes(ROOT),'contract_sha256':sha(CONTRACT),'archives':str(archives),'archives_sha256':sha(archives),'seeds':list(SEEDS),'final_rows':72}
 m['manifest_sha256']=digest(m);output.mkdir(parents=True,exist_ok=True)
 path=output/'FINAL_FREEZE.json'
 with path.open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(m,indent=2)+'\n')
 return {'freeze_manifest_sha256':sha(path),'manifest_digest':m['manifest_sha256'],'final_target_set_identity':identity,'product_files':len(m['product']),'baseline_runtime_files':len(m['baseline']),'final_attempts':0}
def build_archives(args):
 started=time.perf_counter();cpu=time.process_time();verify_suite(args.suite)
 sys.path.insert(0,str(ROOT))
 from tomolab.discovery.knowledge import KnowledgeArchive,make_observation
 from tomolab.discovery.hypothesis_adapter import generate_pool
 suite=module(args.suite);directory=external_output(args.output);rows=read(directory/'records.json')
 if not full_grid(rows,[c['id'] for c in suite.cases('development')]):raise ValueError('complete source grid required before source knowledge freeze')
 if any(r['status'] not in ('COMPLETE','NOT_COMPARABLE') for r in rows):raise ValueError('source execution errors must be resolved before archive capture')
 archives={};audit=[]
 for case in suite.cases('development'):
  spec=suite.prepare(case);origin=suite.provenance(case);meta=next(x for x in suite.META['reviewed'] if x['case']==case['id'])
  origin.update(implementation_sha256=meta['extracted_sha256'],oracle_sha256=oracle_identity(args.suite),independence_id='reviewed-'+case['id'])
  meter=Meter(suite,case,64);points=generate_pool(spec,seed=101,size=64)
  for point in points:meter.failed(point,'independent-development-counterevidence')
  for seed in SEEDS:
   source=next(r for r in rows if r['method']=='E6' and r['case']==case['id'] and r['seed']==seed)
   unique={canonical(row['inputs']):row for row in source['raw']}
   valid_events=[{'kind':'FAILURE' if row['failed'] else 'REFUTATION','evidence_id':f'actual-{i:04}',
    'inputs':row['inputs'],'invariant':spec['contract']['invariants'][0],'category':'mismatch','signature':'reference-comparison'} for i,row in enumerate(unique.values())]
   archive=KnowledgeArchive.from_failure_log(spec,valid_events,origin) if valid_events else KnowledgeArchive(spec,source=origin)
   before=Counter(c['status'] for c in archive.claims())
   for index,row in enumerate(meter.rows):
    evidence={'kind':'FAILURE' if row['failed'] else 'REFUTATION','evidence_id':f'audit-{index:04}',
     'inputs':row['inputs'],'invariant':spec['contract']['invariants'][0],'category':'mismatch','signature':'reference-comparison'}
    archive.observe(make_observation(spec,evidence,origin),trusted_observation=True)
   snapshot=archive.freeze();archives[case['semantics']+':'+str(seed)]=snapshot
   audit.append({'case':case['id'],'seed':seed,'before_status_counts':dict(before),'after_status_counts':dict(Counter(c['status'] for c in snapshot['claims'])),
    'claims':len(snapshot['claims']),'counterevidence_events':len(meter.rows),'independent_implementation_claimed':False,
    'meaning':'fresh development observations on same pinned implementation; not cross-project positive/negative qualification',
    'snapshot_sha256':snapshot['receipt']['sha256']})
  save(directory/(case['id']+'-contrastive-raw.json'),meter.receipt())
 save(directory/'source-archives.json',archives)
 summary={'schema':'e7-source-knowledge-audit-v1','archives':len(archives),'audit':audit,
  'additional_actual_target_calls':sum(read(directory/(c['id']+'-contrastive-raw.json'))['actual_target_calls'] for c in suite.cases('development')),
  'additional_actual_oracle_calls':sum(read(directory/(c['id']+'-contrastive-raw.json'))['actual_oracle_calls'] for c in suite.cases('development')),
  'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,'final_feedback':0,'final_execution':False}
 save(directory/'source-audit-summary.json',summary)
 # Development-only ablation, no result-based tuning and no final target calls.
 ablations=[]
 for case in suite.cases('development'):
  for enabled in (False,True):
   packet={'case':case['id'],'seed':SEEDS[0],'method':'E7','phase':'development','suite':str(Path(args.suite).resolve()),
    'baseline_root':str(Path(args.baseline_root).resolve()),'archives':str(directory/'source-archives.json') if enabled else None}
   row=run_packet(packet,directory,2000+len(ablations));row['archive_enabled']=enabled;ablations.append(row)
 save(directory/'development-ablations.json',ablations)
 return summary
def execute(args):
 verify_suite(args.suite);directory=external_output(args.output);directory.mkdir(parents=True,exist_ok=True)
 suite=module(args.suite);split='development' if args.development else 'final';cases=suite.cases(split)
 before=product_hashes(ROOT);m=None
 if not args.development:
  if not args.freeze:raise ValueError('final requires a frozen manifest')
  m=verify_final(args.freeze,args.suite,args.baseline_root)
  # The caller must separately satisfy root authorization and normal PR CI.
  if not args.final_authorized:raise PermissionError('explicit root final authorization required')
  baseline=m['baseline_root'];archives=m['archives']
  authority,final_ledger=claim_final(args.freeze,directory)
 else:baseline=str(Path(args.baseline_root).resolve());verify_baseline(baseline);archives=args.archives
 rows=[]
 for case in cases:
  for seed in SEEDS:
   for method in METHODS:
    packet={'case':case['id'],'seed':seed,'method':method,'phase':split,'suite':str(Path(args.suite).resolve()),'baseline_root':baseline,'archives':archives}
    if m:verify_final(args.freeze,args.suite,baseline)
    row=run_packet(packet,directory,len(rows));row['source_drift']=product_hashes(ROOT)!=before;rows.append(row)
    save(directory/'records.json',rows)
    print(json.dumps({'case':case['id'],'seed':seed,'method':method,'status':row['status'],'completed':len(rows)},ensure_ascii=True),flush=True)
 if not full_grid(rows,[c['id'] for c in cases]):raise ValueError('incomplete evaluation grid')
 symbolic=[]
 for case in cases:
  packet={'case':case['id'],'seed':SEEDS[0],'method':'CrossHair','phase':split,'suite':str(Path(args.suite).resolve()),'baseline_root':baseline,'archives':None,'symbolic_directory':str(directory)}
  if m:verify_final(args.freeze,args.suite,baseline)
  symbolic.append(run_packet(packet,directory,1000+len(symbolic)))
  save(directory/'symbolic-records.json',symbolic)
 if m:
  verify_final(args.freeze,args.suite,baseline)
  completion={'rows':len(rows),'records_sha256':sha(directory/'records.json'),'generator_feedback':0}
  complete_once(final_ledger,completion);complete_once(authority,completion)
 summary={'schema':'e7-evaluation-track-v2','evaluation_generation':2,'split':split,'summary':summarize(rows),'records':len(rows),'symbolic_records':len(symbolic),'symbolic_status_counts':dict(Counter(r.get('tool_status',r['status']) for r in symbolic)),
  'symbolic_wall_seconds':sum(r['wall_seconds'] for r in symbolic),'symbolic_actual_concrete_replay_pairs':sum(r.get('actual_target_calls',0) for r in symbolic),
  'evaluator_sha256':sha(__file__),'contract_sha256':sha(CONTRACT),'suite_sha256':sha(args.suite),'oracle_identity':oracle_identity(args.suite),'full_grid':True,'generator_final_feedback':0}
 save(directory/'summary.json',summary);return summary
def publish_aggregate(development,final=None,freeze_manifest=None):
 development=external_output(development);devrows=read(development/'records.json');devsummary=read(development/'summary.json')
 contract=read(CONTRACT);retired=contract['retired_generation_v1']
 audit=read(development/'source-audit-summary.json') if (development/'source-audit-summary.json').exists() else None
 ablations=read(development/'development-ablations.json') if (development/'development-ablations.json').exists() else []
 observed_source_cost=sum(r['wall_seconds'] for r in devrows)+devsummary.get('symbolic_wall_seconds',0.)+sum(r['wall_seconds'] for r in ablations)+(audit['wall_seconds'] if audit else 0.)+1.0729024
 source_claim_counts=Counter()
 if audit:
  for item in audit['audit']:source_claim_counts.update(item['after_status_counts'])
 data={'schema':'tomolab-e7-public-evaluation-v2','evaluation_generation':2,'evaluation_generation_status':'REGISTERED_EXECUTED_DEVELOPMENT',
  'retired_generation_v1':retired,'oracle_repair_review':contract['oracle_repair_review'],
  'oracle_only_repair_diagnostic_calls_not_production_pairs':62,
  'final_target_set_identity':contract['final_target_set_identity'],
  'baseline_release':'v0.6.0a1','baseline_commit':contract['baseline_commit'],
  'contract_sha256':sha(CONTRACT),'evaluator_sha256':sha(__file__),'scope':read(CONTRACT)['scope'],
  'actual_call_unit':'original extracted top-level production function + independent reference calls; not state transitions, predicate attempts, or symbolic internals',
  'apriori_applicability_design':read(CONTRACT)['apriori_applicability_design'],
  'development':devsummary,'source_knowledge':{'status_counts':dict(source_claim_counts),'archives':audit['archives'] if audit else 0,
   'counterevidence_target_calls':audit['additional_actual_target_calls'] if audit else 0,
   'counterevidence_oracle_calls':audit['additional_actual_oracle_calls'] if audit else 0,
   'audits':audit['audit'] if audit else [],'ablation_summary':summarize(ablations) if ablations else [],
   'ablation_rows':[{'case':r['case'],'archive_enabled':r['archive_enabled'],'status':r['status'],'found':r.get('found',False),'wall_seconds':r['wall_seconds'],'actual_target_calls':r.get('actual_target_calls',0),'actual_oracle_calls':r.get('actual_oracle_calls',0)} for r in ablations],
   'source_cost_wall_seconds_observed':observed_source_cost,'source_capture_wall_seconds':1.0729024,
   'human_and_llm_reasoning_cost':'UNKNOWN_NOT_MEASURED','same_implementation_counterevidence_is_independence':False,
   'predeclared_failure_log_capture_policy':'E6 only; NativeHypothesis/E7 source logs never substituted after outcomes',
   'selected_E6_mismatch_runs':sum(r['method']=='E6' and r.get('found',False) for r in devrows),
   'native_hypothesis_mismatch_runs':sum(r['method']=='NativeHypothesis' and r.get('found',False) for r in devrows),
   'E7_native_mismatch_runs':sum(r['method']=='E7' and r.get('found',False) for r in devrows),
   'primary_candidate_claims':sum(r['claims'] for r in audit['audit']) if audit else 0},
  'cost_ledger':{'v2_source_comparison_preparation_wall_seconds':observed_source_cost,
   'retired_v1_primary_source_wall_seconds':retired['observed_primary_source_wall_seconds'],
   'posthoc_v1_api_ingestion_wall_seconds_excluded_from_primary':retired['supplemental_api_ingestion_wall_seconds'],
   'oracle_only_repair_diagnostic_wall_seconds':contract['oracle_repair_review']['diagnostic_wall_seconds'],
   'human_and_llm_reasoning':'UNKNOWN_NOT_MEASURED','prior_costs_not_silently_erased':True},
  'metric_definitions':{'duplicate_evaluation_rate':'duplicates across all actual evaluations, including shrink and mandatory independent replay; not pure generation duplication or wasted-search rate'},
  'final':{'status':'NOT_EXECUTED'},'final_attempts_started':0,'final_attempts_completed':0,'final_feedback_to_generator':0,
  'external_generalization':'NOT_EXECUTED','consumed_E1_E6_holdouts_accessed':False,
  'limits':['exact pure-function extraction, not whole-project execution','static reviewer inspected all candidate code before preregistration; generator never received final target implementation',
   'shared author, some shared repositories and standard mathematical algorithm ancestry; no claim of fully independent mechanism lineage',
   'native Stateful is NOT_COMPARABLE on every stateless case; no invented state-machine wrappers',
   'CrossHair receives source in its separate privileged tier; internal calls UNKNOWN',
   'fresh same-implementation development evidence can refute claims but cannot satisfy independent positive-and-negative promotion',
   'confidence applies only to declared finite domains and reviewed math/documentation Oracles; no population base-rate claim',
   'sampled CPU is lower bound and RSS is not actual OS peak; overlapping phase times are not additive',
   'retrospective source/target function selection is not random real-project sampling; no claims of novelty or operational exploitability',
   'generation1 retired after finite-precision Oracle false alerts; earlier static authority review missed that numerical implementation error',
   'duplicate_evaluation_rate includes shrink and mandatory replay, not pure generator duplication or wasted search']}
 if final:
  final=external_output(final);frows=read(final/'records.json');fs=read(final/'summary.json');m=verify_final(freeze_manifest,read(freeze_manifest)['suite'])
  ledger=Path(freeze_manifest).resolve().parent/'FINAL_LEDGER.jsonl';events=[json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()]
  if [x['event'] for x in events]!=['START','COMPLETE'] or events[1]['records_sha256']!=sha(final/'records.json'):raise ValueError('completed final ledger does not bind these records')
  if not full_grid(frows,['target-'+str(i).zfill(2) for i in range(1,7)]):raise ValueError('final public aggregate requires full frozen grid')
  guided=sum(r.get('guided_candidates',0) for r in frows if r['method']=='E7')
  data['final']={**fs,'verdict':verdict(frows,guided,source_cost=observed_source_cost),
   'per_problem':[{'case':c,'method':method,'runs':sum(r['case']==c and r['method']==method for r in frows),'runs_with_mismatch':sum(r['case']==c and r['method']==method and r.get('found',False) for r in frows)} for c in ['target-'+str(i).zfill(2) for i in range(1,7)] for method in METHODS],
   'qualified_claims_summed':sum(r.get('qualified_claims',0) for r in frows),'guided_candidates':guided,
   'actual_production_defect_eligible_functions':5,'compatibility_only_functions_not_defect_denominator':1,
   'generator_frozen_before_target_execution':all(r.get('frozen_before_target_execution',False) for r in frows if r['method']!='NativeStateful'),
   'replay_status_counts':dict(Counter(r.get('replay','NO_WITNESS') for r in frows if r['method']!='NativeStateful'))}
  data.update(freeze_manifest_sha256=sha(freeze_manifest),frozen_product_files=len(m['product']),frozen_baseline_runtime_files=len(m['baseline']),
   frozen_source_archives=len(read(m['archives'])),final_attempts_started=1,final_attempts_completed=1,
   external_generalization='INCONCLUSIVE',final_records_sha256_ledger_binding=events[1]['records_sha256'])
  data['external_generalization_reason']='actual reviewed project functions executed; qualified transferable knowledge and marginal source-to-target advantage not established' if guided==0 else 'bounded actual project execution, not random project sampling or full operational generalization'
 save(ROOT/'docs/E7_RESULTS.json',data)
 lines=['# E7 실제 프로젝트 독립 평가','',
  '최종 판정: **'+(data['final'].get('verdict',{}).get('status','NOT_EXECUTED'))+'**. 외적 일반화: **'+data['external_generalization']+'**.','',
  '현재 수치는 명시적으로 재등록한 generation-v2다. v1은 INVALID_ORACLE / INCONCLUSIVE로 원본·127개 개발 파일·해시를 보존했다. 원래 역사적 계약 SHA-256은 `22abade2c41fbcccd02ce898a2591f67dcefaa1f23700c72284688c423eacfe5`이며 현재 v2 계약의 해시와 구분한다.','',
  'v1의 원시 불일치6개 실행 중 실제 생산 코드 불일치는2개 실행(15rows·한 함수 메커니즘), Oracle 오판은4개 실행(42rows·한 Oracle 메커니즘)이었다. 사전 정적·수식 감사가 유한 정밀도 zero 판정 구현 오류를 놓쳤으며, 결과 후 개발 로그 정적 감사에서 발견했다. 정확한 Fraction 산술로만 고쳤고 문제·domain·seed·예산·E6-only 수집 정책·제품 runtime54개는 바꾸지 않았다. 앞선3/3 실제 제품 결함 해석은 철회한다. novelty·운영 영향은 UNKNOWN이다.','',
  '합성 mutation을 추가하지 않고 사용자 소유5개 저장소에서 실제 함수9개를 HEAD Git blob으로 고정했다. 개발3개와 최종6개는 동일 함수가 아니며, 정적 검토한 함수·필요 class의 AST를 원본 그대로 추출했다. 프로젝트 전체나 provider/네트워크를 실행하지 않았다. 원본 저장소·태그는 수정하지 않았다.','',
  '평가자가 코드를 읽고 대상을 선정했으므로 무작위 프로젝트 표본이 아니다. 일부 프로젝트·작성자·표준 알고리즘 계보가 겹친다. 이 한계를 독립 프로젝트 수 또는 일반적 버그 발견률로 확대하지 않는다.','',
  '## 사전 계약과 Oracle','',
  'v2 계약 SHA-256: `'+sha(CONTRACT)+'`. v2 비교 전, 최종 관측0 상태에서 재등록했다. float의 Fraction 표현으로 centered variance/covariance와 zero·epsilon 판정을 정확히 계산하고 마지막 제곱근만 기존100-digit Decimal로 변환한다. float tolerance(rel1e-8/abs1e-10)·정상 대조군4개·seeds11/37/73·예산은 그대로다. 개발 자료는 v1에서도 소비된 DEVELOPMENT이며 새로운 blind source라고 주장하지 않는다. 바깥 영역은 대상/Oracle 호출 전에 거절한다.','',
  'Oracle 수정 정확성 진단은 기존 개발57rows와 독립 작성5개 수학 fixture에 대해 Oracle-only62calls, production target0이었다. 이 단위를 생산 함수+Oracle 평가 pair와 혼동하지 않는다. 독립 감사와 정상 승인 경로로 연동을 검토했고 suite와 공개 수학 helper의 hash를 함께 동결했다.','',
  '## 개발 결과','',
  '| 방법 | COMPLETE/전체 | 실제 불일치 run | 함수별 메커니즘 | 실제 target/Oracle 호출 | 전체 wall(s) |','|---|---:|---:|---:|---:|---:|']
 for row in devsummary['summary']:lines.append(f"| {row['method']} | {row['complete']}/{row['attempted']} | {row['runs_with_mismatch']} | {row['distinct_function_mechanisms']} | {row['actual_target_calls']}/{row['actual_oracle_calls']} | {row['wall_seconds']:.3f} |")
 lines +=['','상태 없는 실제 함수만 선택했으므로 Native Stateful은 NOT_COMPARABLE이다. CrossHair는 source-aware 별도 tier이며 실제 내부 symbolic 호출 수는 UNKNOWN이다. source-level 필요조건으로 제안한 후보는 유효 범위에서 별도 Oracle로 재검증하며, 미분석·timeout을 correctness proof로 해석하지 않는다.','',
  '## 구조적 지식 신뢰성과 비용','',
  '고정된 E6 source 실행의 실제 유효 영역 실패·반증 로그를 중복 제거해 지식을 만들고 새 개발 입력으로 반증했다. 실행하지 않은 precondition 위반 입력을 clean REFUTATION으로 학습하지 않는다. 실제 같은 구현의 새 입력은 독립 구현 지지로 꾸미지 않았다. 합산 archive 상태는 `'+canonical(dict(source_claim_counts))+'`이다. 반증된 가설은 삭제하지 않고 자동 전이에서 배제한다. 미확인 가설이나 전부 fallback인 경로를 연구 우위로 인정하지 않는다.','',
  f"v2 주평가 source archive 후보는 {data['source_knowledge']['primary_candidate_claims']}개다. 사전 고정한 E6 수집의 불일치 실행은 {data['source_knowledge']['selected_E6_mismatch_runs']}개이며 Native Hypothesis {data['source_knowledge']['native_hypothesis_mismatch_runs']}개, E7 native {data['source_knowledge']['E7_native_mismatch_runs']}개와 구분한다. v1 E6 경로는 seed11의 실제 불일치도 놓쳤다. 결과를 보고 다른 방법의 로그를 주평가로 대체하지 않았다. 후보0개라면 반증 정확도·qualified knowledge 발견 기여를 검증할 수 없다.",'',
  '결과 관측 전부터 공통 robust Pearson 수학 도메인에 한정한 호환 가능한 cross-project 계약 쌍은1개, 독립 구현의 양성·음성 DEVELOPMENT 지지 계보는0개였다. 따라서 아무 후보도 승격되지 않는다면 이 설계는 qualified knowledge의 발견 유틸리티를 검증할 수 없다는 사전 근거 부족을 명시했다. 같은 함수의 이름을 바꾸거나 final을 개발 검증에 쓰지 않았다.','',
  f"관측한 source 실행·검사·지식 축적 비용은 {observed_source_cost:.3f}초다. capture 실행1.073초와 개발/별도 symbolic/반증/ablation을 포함한 보수적 합계다. 분석자·LLM 추론 비용은 측정하지 않아 UNKNOWN이다. 위 비용과 target-only 비용을 구분한다.",'',
  f"별도 비용 장부: 퇴역 v1 주개발·source 준비 {retired['observed_primary_source_wall_seconds']:.3f}초, 사후 비비교 API ingestion {retired['supplemental_api_ingestion_wall_seconds']:.3f}초, Oracle-only 수정 진단 {contract['oracle_repair_review']['diagnostic_wall_seconds']:.6f}초다. v2만 소비한 것처럼 이전 비용을 숨기지 않으며 사후 보충 archive는 주평가·최종 계획에서 제외한다.",'',
  'duplicate_evaluation_rate는 shrink와 필수 독립 replay를 포함한 전체 실제 평가의 중복이다. 순수 생성 중복률이나 낭비 탐색률로 해석하지 않는다.','',
  'E7 archive enabled/empty ablation은 개발3개 문제에서만 시행했고 결과에 따라 정책·문제·seed·가설을 고치지 않았다. 가이드가 실제 사용됐다는 사실과 독립적인 발견 기여는 별도다.','',
  '## 최종 동결 평가','']
 if final:
  lines +=['전체72 records: 실제 비교54개와 Native Stateful18 NOT_COMPARABLE. 비교 가능한54개 중45개는 생산 결함 판정 범위5함수,9개는 production-defect-eligible가 아닌 새로 선언한 population-equivalence 호환성 대조군1함수다. 이 대조군의 불일치는 결함 발견 분자·분모에 넣지 않고 전체 개선 판정을 보류시킨다. 각 방법의64개 이하 계획을 대상 실행 전에 동결하고 최종 피드백0으로 실행했다. 원래 pinned final project/revision/path/function-AST identity에 대한 canonical exclusive claim과 manifest 인접 ledger의 START/COMPLETE 각1회로 재소비를 차단했다. Oracle·suite·case alias·출력 경로를 바꿔도 같은 최종 대상은 재사용할 수 없다.','',
   '| 방법 | COMPLETE/전체 | 불일치 run | 함수별 메커니즘 | target/Oracle 호출 | 전체 wall(s) |','|---|---:|---:|---:|---:|---:|']
  for row in fs['summary']:lines.append(f"| {row['method']} | {row['complete']}/{row['attempted']} | {row['runs_with_mismatch']} | {row['distinct_function_mechanisms']} | {row['actual_target_calls']}/{row['actual_oracle_calls']} | {row['wall_seconds']:.3f} |")
  lines+=['',f"실제 qualified guidance 후보 {guided}개. 판정 `{data['final']['verdict']['status']}`. 비용 감소가 보이더라도 가이드의 실제 재생된 발견 기여·source 포함 비용 기준을 충족하지 못하면 개선이라고 하지 않는다. 발견이 없는 문제에서 최초 발견 시간을 만들어내지 않는다.",'',
   '동결 manifest SHA-256: `'+sha(freeze_manifest)+'`. 최종 입력·출력·구현·원시 기록·archive·ledger는 저장소 밖에 보존한다. Generator에는 predeclared spec·역할·검토된 provenance·개발 archive만 전달했고, 비공개 target IR/정답/구현/최종 labels는 전달하지 않았다.']
 else:lines+=['아직 실행하지 않았다. 정상 CI·제품·source archive·계약·suite 동결 및 root의 명시 신호 뒤 한 번만 실행한다.']
 lines+=['','## 해석 한계','',
  '실제 프로젝트 함수의 제한된 수학/문자열 계약 검증이다. 동일 결함의 입력·seed를 별개 메커니즘으로 세지 않는다. E1~E6 소비된 final 자료를 읽거나 재사용하지 않았다. 기본 subprocess는 LOGICAL_ISOLATION_ONLY이고 Docker 검사는 별도 CI의 실제 범위만 인정한다. 대상·Oracle은 신뢰된 host code다.','',
  'CPU는10ms process-tree 표본 하한, 메모리는 live-tree 표본 최대이며 true peak가 아니다. timing phase 일부는 겹친다. 원시 자료를 독립 재산출하지 않은 metadata 감사와 실행 자체의 검증도 구별한다. 공개 수치는 [E7_RESULTS.json](E7_RESULTS.json), 선행 계약은 [E7_EVALUATION_CONTRACT.json](E7_EVALUATION_CONTRACT.json)에 있다.']
 (ROOT/'docs/E7_EVALUATION_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
 return {'aggregate_sha256':sha(ROOT/'docs/E7_RESULTS.json'),'report_sha256':sha(ROOT/'docs/E7_EVALUATION_REPORT.md'),'final':data['final'].get('verdict',{}).get('status','NOT_EXECUTED')}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite');p.add_argument('--baseline-root');p.add_argument('--output');p.add_argument('--archives');p.add_argument('--freeze');p.add_argument('--development',action='store_true');p.add_argument('--prepare-freeze',action='store_true');p.add_argument('--build-archives',action='store_true');p.add_argument('--final-authorized',action='store_true');p.add_argument('--trusted-project-execution',action='store_true');p.add_argument('--_worker',nargs=2,help=argparse.SUPPRESS)
 args=p.parse_args()
 if args._worker:
  packet=read(args._worker[0]);result=worker(packet);save(args._worker[1],result);return
 if not args.suite or not args.output:raise ValueError('suite and output required')
 if args.prepare_freeze:result=freeze(args)
 else:
  if not args.trusted_project_execution:raise PermissionError('explicit trusted project execution authorization required')
  result=build_archives(args) if args.build_archives else execute(args)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
