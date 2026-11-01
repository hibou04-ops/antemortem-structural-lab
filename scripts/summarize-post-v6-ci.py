"""Validate saved CI receipts and expose a bounded JSON readback in job summary."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET

from tomolab.discovery import sequence_qualification as q
from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.schema import digest

def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(path):return json.loads(Path(path).read_bytes())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['functional','oci'],required=True)
    args=parser.parse_args()
    head=subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()
    files={}
    for path in sorted(Path('tomolab').rglob('*.py')):
        files[path.as_posix()]=sha(path.read_bytes())
    result=dict(schema='post-v6-ci-readback-v1',mode=args.mode,head=head,event=os.getenv('GITHUB_EVENT_NAME'),
        pr_head=os.getenv('POST_V6_PR_HEAD'),platform=platform.system(),python=platform.python_version(),
        runtime_files=files,runtime_digest=digest(files),paid_api_calls=0,release_actions=0)
    if args.mode=='functional':
        root=ET.parse('harvester-regressions.xml').getroot()
        tests=root.findall('.//testcase')
        result['pytest']=dict(tests=len(tests),failures=len(root.findall('.//failure')),errors=len(root.findall('.//error')),skipped=len(root.findall('.//skipped')))
        assert result['pytest']['failures']==result['pytest']['errors']==0
        for name in ['historical-preservation.json','product-runtime.json','harvester-installed.json','qualification-installed.json','work/structural-example/summary.json']:
            value=load(name)
            result.setdefault('artifacts',[]).append(dict(path=name,sha256=sha(Path(name).read_bytes()),status=value.get('status'),summary=value if name.endswith('structural-example/summary.json') else {k:v for k,v in value.items() if k in ('status','checks','platform','python','cases','passed')}))
        result['status']='PASS'
    else:
        manifest=q.validate_manifest(load('docs/SEQUENCE_QUALIFICATION_V7_20261101.json'))
        base=Path('work/sequence-qualification/public')
        receipt=load(base/'qualification-receipt.json')
        assert receipt['sha256']==digest({k:v for k,v in receipt.items() if k!='sha256'})
        assert receipt['status']=='REPRODUCED' and receipt['additional_source_gets']==0
        assert receipt['actual_entry_counts']==dict(external_target_calls=12,external_oracle_calls=12,external_reset_calls=24)
        assert receipt['unknown_external_call_records']==0 and receipt['actual_distinct_container_ids']==24
        assert all(c['cleanup']['status']=='PASS' for c in receipt['controller_ledger'])
        cases=[]
        for case in manifest['cases']:
            payloads={role:q._cached_payload('docs/sequence-v7-source',url,maximum=maximum) for role,url,_,maximum in q._urls(case)}
            candidate=q._restore_candidate(case,payloads)
            review,bundle=q._review_and_bundle(case,candidate)
            path=base/'cases'/case['case_id']/'reproduction.json'
            rep=execution.validate_reproduction_receipt(candidate,review,load(path))
            assert rep['status']=='REPRODUCED'
            cases.append(dict(case_id=case['case_id'],repository=case['projection']['repository'],function=case['function'],contract=case['contract'],
                witness=case['witness'],oracle_sha256=case['oracle_sha256'],reset_sha256=case['reset_sha256'],review_digest=review['review_digest'],
                reproduction_sha256=rep['sha256'],reproduction_raw_sha256=sha(path.read_bytes()),
                buggy=[p['target']['capture'] for p in rep['buggy']],fixed=[p['target']['capture'] for p in rep['fixed']],oracle=[p['oracle']['capture'] for p in rep['fixed']]))
        control=load('work/oci-control/oci-probe.json')
        assert control['status']=='PASS'
        result.update(status='PASS',qualification_summary=load(base/'summary.json'),cases=cases,oci_control=control,
            receipt_raw_sha256=sha((base/'qualification-receipt.json').read_bytes()),source_host_execution=0,
            artifact_files=[dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in sorted(base.rglob('*')) if p.is_file()])
    result['sha256']=digest(result)
    Path('post-v6-'+args.mode+'-readback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    compact={k:v for k,v in result.items() if k not in ('runtime_files','artifact_files','oci_control','artifacts')}
    compact['raw_readback_sha256']=sha(Path('post-v6-'+args.mode+'-readback.json').read_bytes())
    if 'artifacts' in result:compact['artifacts']=result['artifacts']
    if 'artifact_files' in result:compact['artifact_file_count']=len(result['artifact_files']);compact['artifact_files_digest']=digest(result['artifact_files'])
    if 'oci_control' in result:compact['oci_control_status']=result['oci_control']['status'];compact['oci_control_digest']=digest(result['oci_control'])
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as output:
        output.write('## Post-v6 verified readback\n\n```json\n'+json.dumps(compact,ensure_ascii=False,indent=2)+'\n```\n')
    print(json.dumps(compact,ensure_ascii=True))

if __name__=='__main__':main()
