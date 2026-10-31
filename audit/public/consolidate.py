"""Read already-produced audit artifacts; do not install or execute product code."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

EXPECTED={
 'antemortem_structural_lab-0.8.0a1-py3-none-any.whl':'d7a1725acd490e460eb94d0180055d339ce2c6b4bb26c52172f152ae461ef5bc',
 'antemortem_structural_lab-0.8.0a1.tar.gz':'63b69a1239df2c2422fcdf47352f46c247e4df26ea22397e8a59351a567d02ab'}
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def compact(value):
    return dict(returncode=value.get('returncode'),status=value.get('receipt',{}).get('status'),
        outcome=value.get('run',{}).get('outcome'),replay_status=value.get('receipt',{}).get('replay_status'),
        stdout=value.get('stdout','')[-500:],stderr=value.get('stderr','')[-1600:])

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--originals',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    root=dict(schema='tomolab-public-audit-consolidated-v1',version='0.8.0a1',original_run=41226721157,
        installed_package_source='3ece4df3bd01abe6aae58ef8a01bf4b01515f689',new_product_executions=0,new_installs=0,new_uploads=0,research_runs=0,
        correction='Only the auditor private-directory matcher changed; original reports and failures are retained',environments=[])
    folders=sorted(a.originals.glob('independent-public-audit-*'));assert len(folders)==4
    for folder in folders:
        item=dict(environment=folder.name,original_report_sha256=digest(folder/'audit.json'))
        old=read(folder/'audit.json');failed=[x['name'] for x in old['checks'] if x['status']!='PASS']
        assert failed==['independent-package-inspection'],failed
        item.update(python=old['python'],os=old['os'],original_checks=len(old['checks']),execution_checks_passed=len(old['checks'])-1,
            original_only_failure='AUDITOR_PRIVATE_DIRECTORY_MATCHER_FALSE_POSITIVE',original_package_report_sha256=digest(folder/'package.json'))
        for service in ('pypi','github'):
            for name,sha in EXPECTED.items():assert digest(folder/service/name)==sha
        output=a.output/(folder.name+'-package.json')
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('package_audit.py')),
            '--directory',str(folder/'pypi'),'--source-root',str(a.source),
            '--pypi-json',str(folder/'pypi.json'),'--github-release-json',str(folder/'release.json'),
            '--output',str(output)],capture_output=True,text=True,encoding='utf-8',timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        static=read(output);item['corrected_package_audit']=dict(status=static['status'],checks=len(static['checks']),failed=static['failed_checks'],findings=static['findings'])
        item['contribution_document_probe']=read(folder/'contribution-doc-probe.json')
        item['behavior']={}
        for kind in ('wheel','sdist'):
            value=read(folder/(kind+'-behavior.json'));assert value['status']=='EXECUTED' and value['source_collection_calls']==value['research_cohort_runs']==value['package_edits']==value['publishing_calls']==0
            assert json.loads(value['installed_identity']['stdout'])['version']=='0.8.0a1'
            rows=[]
            for record in value['records']:
                row={k:record[k] for k in ('id','observed_issue','passed','classification','expected','scope','independent_expected_model') if k in record}
                for k in ('direct','actual','replay','explicit_actual_name_control','zero','nonzero','allowed','oracle_error'):
                    if k in record:row[k]=compact(record[k])
                rows.append(row)
            item['behavior'][kind]=dict(original_receipt_sha256=digest(folder/(kind+'-behavior.json')),records=rows)
        root['environments'].append(item)
    root['status']='COMPLETED_AUDIT_WITH_CONFIRMED_FINDINGS'
    write(a.output/'consolidated.json',root)
    print(json.dumps(root,indent=2,ensure_ascii=True))
if __name__=='__main__':main()
