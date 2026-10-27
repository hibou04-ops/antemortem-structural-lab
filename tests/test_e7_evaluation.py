import importlib.util,json
from pathlib import Path
import pytest

def evaluator():
 path=Path(__file__).parents[1]/'scripts/evaluate-e7.py'
 s=importlib.util.spec_from_file_location('e7_eval_tests',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_once_ledger_never_restarts_completed_or_started_attempt(tmp_path):
 e=evaluator();p=tmp_path/'ledger.jsonl';e.begin_once(p,{'freeze':'x'})
 with pytest.raises(FileExistsError):e.begin_once(p,{'freeze':'x'})
 e.complete_once(p,{'rows':72})
 with pytest.raises(ValueError):e.complete_once(p,{'rows':72})
 assert [json.loads(x)['event'] for x in p.read_text().splitlines()]==['START','COMPLETE']

def test_grid_rejects_missing_or_duplicate_method_seed_cells():
 e=evaluator();rows=[{'case':c,'method':m,'seed':s} for c in ['a','b'] for m in e.METHODS for s in e.SEEDS]
 assert e.full_grid(rows,['a','b'])
 assert not e.full_grid(rows[:-1],['a','b'])
 assert not e.full_grid(rows[:-1]+[rows[0]],['a','b'])

def rows(e,extra=False):
 return [{'case':c,'method':m,'seed':1,'status':'COMPLETE','found':c=='a' or extra and m=='E7',
  'wall_seconds':.1 if m=='E7' else 1.,'first_failure_seconds':None,'first_witness_guided':m=='E7','replay':'MATCHED_TWICE'} for m in ('NativeHypothesis','E6','E7') for c in ('a','b')]

def test_cheap_fallback_is_never_discovery_improvement():
 e=evaluator();result=e.verdict(rows(e),qualified_usage=0)
 assert result['status']=='NO_IMPROVEMENT'
 assert result['qualified_use']==0

def test_source_acquisition_cost_cannot_be_omitted_for_efficiency_claim():
 e=evaluator();assert e.verdict(rows(e),qualified_usage=1,source_cost=0)['status']=='IMPROVED'
 assert e.verdict(rows(e),qualified_usage=1,source_cost=100)['status']=='NO_IMPROVEMENT'

def test_required_baseline_error_or_false_alert_prevents_promotion():
 e=evaluator();data=rows(e,extra=True);data[0]['false_alerts']=1
 assert e.verdict(data,qualified_usage=1)['status']=='INCONCLUSIVE'
 data=rows(e,extra=True);data[0]['status']='ERROR'
 assert e.verdict(data,qualified_usage=1)['status']=='INCONCLUSIVE'

def test_zero_observed_mechanisms_does_not_fabricate_first_failure_advantage():
 e=evaluator();data=rows(e)
 for row in data:row['found']=False
 assert e.verdict(data,qualified_usage=1)['status']=='INCONCLUSIVE'

def test_raw_output_cannot_enter_public_repository():
 e=evaluator()
 with pytest.raises(ValueError):e.external_output(e.ROOT/'research'/'e7-private')

@pytest.mark.parametrize('entry',['verify_suite','module','worker'])
def test_retired_invalid_oracle_is_rejected_before_contract_or_dynamic_import(tmp_path,monkeypatch,entry):
 e=evaluator();path=tmp_path/'authored-unexecuted.py';path.write_text('raise RuntimeError("must never import")\n')
 retired=next(iter(e.RETIRED_ORACLE_SUITE_SHA256))
 monkeypatch.setattr(e,'sha',lambda _:retired)
 monkeypatch.setattr(e,'read',lambda _:pytest.fail('retired rejection must precede contract access'))
 monkeypatch.setattr(e.importlib.util,'spec_from_file_location',lambda *a:pytest.fail('retired suite must never import'))
 with pytest.raises(ValueError,match='known invalid Oracle'):
  if entry=='worker':e.worker({'method':'NativeHypothesis','phase':'development','suite':str(path)})
  else:getattr(e,entry)(path)

@pytest.mark.parametrize('contract',[
 {'evaluation_generation':2,'oracle_repair_review':{'status':'PENDING'}},
 {'evaluation_generation':2,'oracle_repair_review':{'status':'PASS'},'oracle_math_helper_evaluator_sha256':'a'*64}])
def test_new_suite_requires_review_pass_and_exact_math_helper_identity(tmp_path,monkeypatch,contract):
 e=evaluator();path=tmp_path/'authored-no-import.py';path.write_text('raise AssertionError("not executable")\n')
 monkeypatch.setattr(e,'sha',lambda _:'b'*64)
 monkeypatch.setattr(e,'read',lambda _:contract)
 with pytest.raises(ValueError,match='(preregistration are incomplete|math helper identity changed)'):e.verify_suite(path)

def test_baseline_path_override_rejected_before_any_suite_loading(tmp_path,monkeypatch):
 e=evaluator();m={'baseline_root':str(tmp_path/'frozen'),'suite':str(tmp_path/'suite.py')}
 m['manifest_sha256']=e.digest(m);p=tmp_path/'freeze.json';e.save(p,m)
 monkeypatch.setattr(e,'verify_suite',lambda *_:pytest.fail('must reject path before suite loading'))
 with pytest.raises(ValueError,match='baseline override'):e.verify_final(p,tmp_path/'suite.py',tmp_path/'different')

def test_alternate_output_cannot_reconsume_same_frozen_suite(tmp_path,monkeypatch):
 e=evaluator();monkeypatch.setattr(e,'FINAL_AUTHORITY',tmp_path/'authority')
 m={'suite_sha256':'c'*64,'final_target_set_identity':'a'*64,'contract_sha256':'b'*64,'execution_claim':str(e.authoritative_claim_path('a'*64))}
 first=tmp_path/'first';first.mkdir();p=first/'freeze.json';e.save(p,m)
 e.claim_final(p,tmp_path/'output-a')
 copied=tmp_path/'copied';copied.mkdir();p2=copied/'freeze.json';e.save(p2,m)
 with pytest.raises(FileExistsError):e.claim_final(p2,tmp_path/'output-b')
 assert not (copied/'FINAL_LEDGER.jsonl').exists()

def test_oracle_or_suite_revision_cannot_reset_final_target_consumption(tmp_path,monkeypatch):
 e=evaluator();monkeypatch.setattr(e,'FINAL_AUTHORITY',tmp_path/'authority')
 m={'suite_sha256':'b'*64,'contract_sha256':'c'*64,'final_target_set_identity':'a'*64,
  'execution_claim':str(e.authoritative_claim_path('a'*64))}
 (tmp_path/'v1').mkdir();first=tmp_path/'v1/freeze.json';e.save(first,m);e.claim_final(first,tmp_path/'out1')
 m.update(suite_sha256='d'*64,contract_sha256='e'*64)
 (tmp_path/'v2').mkdir();second=tmp_path/'v2/freeze.json';e.save(second,m)
 with pytest.raises(FileExistsError):e.claim_final(second,tmp_path/'out2')

def test_final_identity_uses_original_ast_and_ignores_alias_bundle_or_oracle():
 from copy import deepcopy
 e=evaluator();review={'reviewed':[{'split':'final','case':'target1','project':'owned','revision':'a'*40,
  'path':'src/a.py','function_ast_sha256':{'f':'b'*64},'extracted_file':'one.py','extracted_sha256':'c'*64}]}
 expected=e.final_target_set_identity(review);changed=deepcopy(review)
 changed['reviewed'][0].update(case='renamed',extracted_file='other.py',extracted_sha256='d'*64,oracle_sha256='e'*64)
 assert e.final_target_set_identity(changed)==expected
 changed['reviewed'].append(deepcopy(changed['reviewed'][0]))
 assert e.final_target_set_identity(changed)==expected
 changed['reviewed'][0]['function_ast_sha256']['f']='f'*64
 assert e.final_target_set_identity(changed)!=expected

@pytest.mark.parametrize('constant',[0.1,2.0**-130,5e-324,-1e-40,0.0])
def test_exact_constant_correlation_is_uncomputable_even_with_tiny_floats(constant):
 e=evaluator();centered,variance=e.exact_centered([constant]*3)
 assert variance==0 and all(v==0 for v in centered)
 assert e.exact_correlation([0.,0.,1.],[constant]*3)==(None,False,True)

def test_exact_variance_nonconstant_sanity_and_signed_correlation():
 from fractions import Fraction
 e=evaluator();assert e.exact_centered([0.,1.,2.])[1]==2
 assert e.exact_correlation([0.,1.,2.],[0.,1.,2.])==(1.,False,False)
 assert e.exact_correlation([0.,1.,2.],[2.,1.,0.])==(-1.,False,False)
 assert e.exact_correlation([0.,1.,0.],[1.,0.,-1.])==(0.,False,False)
 assert e.rational_sqrt(Fraction(1,4))==0.5

def test_qualified_claim_without_actual_guided_witness_never_improves():
 e=evaluator();data=rows(e)
 for row in data:row['first_witness_guided']=False
 assert e.verdict(data,qualified_usage=1)['status']=='NO_IMPROVEMENT'

def test_replay_mismatch_blocks_improvement():
 e=evaluator();data=rows(e)
 for row in data:
  if row['method']=='E7':row['status']='INCONSISTENT_REPLAY';row['replay']='MISMATCH'
 assert e.verdict(data,qualified_usage=1)['status']=='INCONCLUSIVE'

def test_exclusive_claim_is_atomic_across_processes(tmp_path):
 import subprocess,sys
 e=evaluator();path=Path(__file__).parents[1]/'scripts/evaluate-e7.py';claim=tmp_path/'atomic.jsonl'
 code="import importlib.util,sys;s=importlib.util.spec_from_file_location('e',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.begin_once(sys.argv[2],{})"
 processes=[subprocess.Popen([sys.executable,'-c',code,str(path),str(claim)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
 statuses=[p.wait(timeout=15) for p in processes]
 assert sorted(statuses)==[0,1]
 assert len(claim.read_text().splitlines())==1

def test_wrong_baseline_revision_is_rejected_before_runtime_reads(tmp_path,monkeypatch):
 e=evaluator();monkeypatch.setattr(e.subprocess,'check_output',lambda *a,**k:b'0'*40)
 monkeypatch.setattr(e,'baseline_hashes',lambda *_:pytest.fail('must reject identity before reading runtime'))
 with pytest.raises(ValueError,match='baseline HEAD'):e.verify_baseline(tmp_path)

def test_expected_pool_exhaustion_does_not_swallow_unrelated_errors():
 e=evaluator()
 class Fake:
  def __init__(self,message):self.message=message
  def request(self,_):raise ValueError(self.message)
 assert e.propose_or_exhausted(Fake('ValueError: Hypothesis candidate pool exhausted')) is None
 with pytest.raises(ValueError,match='independent Oracle broke'):e.propose_or_exhausted(Fake('independent Oracle broke'))

def test_independent_oracle_error_escapes_product_target_exception_adapter():
 from tomolab.discovery.service import evaluate_pair
 e=evaluator()
 class BrokenOracleSuite:
  @staticmethod
  def valid(case,x):return True
  @staticmethod
  def compare(case,x):raise RuntimeError('reference implementation failed')
 spec={'schema':'tomolab-discovery-spec-v1','task_id':'oracle-error','inputs':[{'name':'x','role':'value','type':{'kind':'int','min':0,'max':2}}],
  'contract':{'id':'oracle-error','operation':'identity','preconditions':[],'invariants':['equivalence'],'state_model':'stateless','graph_signature':'UNKNOWN'}}
 meter=e.Meter(BrokenOracleSuite,{},10)
 with pytest.raises(e.OracleEvaluationError,match='no target finding'):
  evaluate_pair(lambda **x:meter.failed(x),lambda **x:False,{'x':1},spec)
 assert meter.witness is None and meter.rows==[] and meter.target_calls==meter.oracle_calls==0

@pytest.mark.parametrize('method',['NativeHypothesis','E6'])
def test_comparison_failure_is_fatal_in_each_baseline_adapter(method):
 e=evaluator()
 class BrokenComparison:
  @staticmethod
  def valid(case,x):return True
  @staticmethod
  def compare(case,x):raise RuntimeError('comparison configuration failed')
 spec={'schema':'tomolab-discovery-spec-v1','task_id':'fatal-oracle','inputs':[{'name':'x','role':'value','type':{'kind':'int','min':0,'max':2}}],
  'contract':{'id':'fatal-oracle','operation':'identity','preconditions':[],'invariants':['equivalence'],'state_model':'stateless','graph_signature':'UNKNOWN'}}
 meter=e.Meter(BrokenComparison,{},10)
 with pytest.raises(e.OracleEvaluationError):
  if method=='E6':e.run_e6_development(spec,meter,11)
  else:
   from tomolab.discovery.hypothesis_adapter import native_find
   native_find(spec,meter.failed,budget=10,seed=11,time_budget=3)
 assert meter.witness is None and meter.rows==[]
