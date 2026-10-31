"""One reviewed product publication path; historical research authority is unchanged.

GitHub/PyPI use the same verified build. No tag/asset replacement, token logging,
registry deletion, research re-scoring, or upload retry occurs in this script.
"""
import argparse
import datetime
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.parse import quote,urlsplit
from urllib.request import Request,urlopen
import zipfile

REPO='hibou04-ops/antemortem-structural-lab'
NAME='antemortem-structural-lab'
WORKFLOW='Python tests'
ROOT=Path(__file__).resolve().parents[1]
REQUIRED_JOBS={f'tests ({system}, {version})' for system in ('ubuntu-latest','windows-latest') for version in ('3.11','3.12','3.13')} | {
    'generator-isolation','unified-generator-isolation','temporal-generator-isolation',
    'knowledge-generator-isolation','corroboration-integration','historical-e7-release',
    'historical-functional','product-installation'}

def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as out:
        json.dump(value,out,ensure_ascii=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
def output(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:
            for key,value in values.items():out.write(f'{key}={str(value).lower() if isinstance(value,bool) else value}\n')
def request(url,*,method='GET',data=None,binary=False,missing=False,github=False,content_type='application/json'):
    headers={'User-Agent':'antemortem-product-publication','Accept':'application/vnd.github+json' if github else 'application/json'}
    if github:
        parsed=urlsplit(url)
        if parsed.hostname not in ('api.github.com','uploads.github.com'):raise ValueError('unapproved GitHub API origin')
        token=os.environ.get('GH_TOKEN')
        if not token:raise PermissionError('normal scoped GitHub workflow token required')
        headers['Authorization']='Bearer '+token
        headers['X-GitHub-Api-Version']='2022-11-28'
    body=None if data is None else data if isinstance(data,bytes) else json.dumps(data).encode()
    if body is not None:headers['Content-Type']=content_type
    try:
        with urlopen(Request(url,data=body,headers=headers,method=method),timeout=60) as response:
            raw=response.read(32*1024*1024+1)
    except HTTPError as error:
        if missing and error.code==404:return None
        detail=''
        try:detail=str(json.loads(error.read(8192)).get('message',''))[:400]
        except (ValueError,AttributeError,TypeError):pass
        for key in ('GH_TOKEN','GITHUB_TOKEN'):
            if os.environ.get(key):detail=detail.replace(os.environ[key],'[redacted]')
        location=urlsplit(url)
        raise RuntimeError(f'HTTP {error.code} for {location.hostname}{location.path}: {detail}; no retry') from None
    if len(raw)>32*1024*1024:raise ValueError('bounded release response exceeded')
    return raw if binary else json.loads(raw)
def api(path,**kwargs):return request('https://api.github.com/repos/'+REPO+'/'+path,github=True,**kwargs)
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()
def inputs():
    version=os.environ.get('RELEASE_VERSION','');source=os.environ.get('RELEASE_SHA','')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+a[1-9][0-9]*',version) or not re.fullmatch(r'[a-f0-9]{40}',source):
        raise ValueError('bounded experimental version and exact commit SHA required')
    if version=='0.7.0a1':raise ValueError('historical E7 files are never uploaded by this workflow')
    return version,source,'v'+version
def verify_tag(tag,source,*,missing=False):
    ref=api('git/ref/tags/'+tag,missing=missing)
    if ref is None:return False
    if ref['object']['type']!='tag':raise ValueError('annotated release tag required')
    record=api('git/tags/'+ref['object']['sha'])
    if record['tag']!=tag or record['object']!={'sha':source,'type':'commit','url':'https://api.github.com/repos/'+REPO+'/git/commits/'+source}:
        # Compare relevant identity fields; API additions do not change identity.
        if record.get('tag')!=tag or record.get('object',{}).get('sha')!=source or record['object'].get('type')!='commit':
            raise ValueError('immutable annotated tag points elsewhere')
    return True
def source_ci(source):
    runs=api('actions/runs?head_sha='+source+'&event=push&per_page=100')['workflow_runs']
    eligible=[r for r in runs if r['name']==WORKFLOW and r['path']=='.github/workflows/tests.yml' and r.get('event')=='push' and r['head_sha']==source and r['head_branch']=='main' and r['status']=='completed' and r['conclusion']=='success']
    if not eligible:raise ValueError('successful final-main Python tests required before publication')
    run=max(eligible,key=lambda r:r['id'])
    jobs=api(f"actions/runs/{run['id']}/jobs?per_page=100")['jobs']
    by_name={j['name']:j for j in jobs}
    if len(by_name)!=len(jobs):raise ValueError('ambiguous duplicate CI job names')
    if not REQUIRED_JOBS<=set(by_name) or any(by_name[n]['conclusion']!='success' for n in REQUIRED_JOBS):
        raise ValueError('required final-main product CI jobs are incomplete')
    return dict(status='PASS',repository=REPO,source_sha=source,workflow=WORKFLOW,event='push',
        head_branch='main',conclusion='success',run_id=run['id'],
        required_jobs=[dict(name=n,conclusion='success') for n in sorted(REQUIRED_JOBS)])
def validate_source(*,tag_required=False):
    version,source,tag=inputs()
    if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_REF')!='refs/heads/main' or os.environ.get('GITHUB_SHA')!=source:
        raise ValueError('dispatch identity must be exact approved main commit')
    if git('rev-parse','HEAD')!=source or api('git/ref/heads/main')['object']['sha']!=source:
        raise ValueError('checkout or current main moved away from approved release SHA')
    auth=read(ROOT/'docs/PRODUCT_RELEASE_AUTHORIZATION.json')
    import tomllib
    metadata=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']
    if metadata['name']!=NAME or metadata['version']!=version or auth['version']!=version or auth['tag']!=tag or not auth['product_publication_authorized']:
        raise ValueError('source metadata and explicit product authorization differ')
    if auth.get('research_qualification_granted') is not False or auth.get('final_evaluation_authorized') is not False or auth.get('study_reruns_authorized') is not False:
        raise ValueError('product approval cannot grant research authority')
    ci=source_ci(source);write(ROOT/'verification/source-ci.json',ci)
    exists=verify_tag(tag,source,missing=not tag_required)
    write(ROOT/'verification/source.json',dict(status='PASS',version=version,source_sha=source,tag=tag,annotated_tag_present=exists,ci_run=ci['run_id']))
    return version,source,tag
def create_tag():
    version,source,tag=validate_source()
    present=verify_tag(tag,source,missing=True)
    existing=request('https://pypi.org/pypi/'+NAME+'/'+version+'/json',missing=True)
    if existing is not None and not present:
        raise ValueError('PyPI version already exists without this annotated tag; stop before creating a conflicting release')
    if not present:
        item=api('git/tags',method='POST',data=dict(tag=tag,message=f'Antemortem Structural Lab {version}: experimental product release\nSource: {source}\nResearch qualification remains unchanged.',object=source,type='commit'))
        api('git/refs',method='POST',data=dict(ref='refs/tags/'+tag,sha=item['sha']))
    verify_tag(tag,source)
def package_names(version):
    prefix=NAME.replace('-','_')+'-'+version
    return {prefix+'-py3-none-any.whl',prefix+'.tar.gz'}
def verify_dist(folder,manifest):
    folder=Path(folder)
    expected=manifest['packages']
    if set(p.name for p in folder.iterdir())!=set(expected):raise ValueError('upload directory must contain exactly two distributions')
    for name,record in expected.items():
        p=folder/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=record['size'] or sha(p.read_bytes())!=record['sha256']:
            raise ValueError('distribution changed after verification')
def package_source_binding(folder,version):
    """Bind runtime inventory and rendered long description to reviewed source."""
    prefix=NAME.replace('-','_')+'-'+version
    runtime={p.relative_to(ROOT).as_posix():p.read_bytes() for p in (ROOT/'tomolab').rglob('*.py')}
    for p in Path(folder).iterdir():
        if p.suffix=='.whl':
            with zipfile.ZipFile(p) as z:
                if {n for n in z.namelist() if n.startswith('tomolab/') and n.endswith('.py')}!=set(runtime):raise ValueError('wheel runtime inventory differs')
                for name,data in runtime.items():
                    if z.read(name)!=data:raise ValueError('wheel runtime differs from release source')
                metadata_raw=z.read(prefix+'.dist-info/METADATA')
        else:
            with tarfile.open(p) as z:
                members={m.name.removeprefix(prefix+'/'):m for m in z.getmembers() if m.isfile()}
                if {n for n in members if n.startswith('tomolab/') and n.endswith('.py')}!=set(runtime):
                    raise ValueError('sdist runtime inventory differs')
                for name,data in runtime.items():
                    if z.extractfile(members[name]).read()!=data:raise ValueError('sdist runtime differs from release source')
                metadata_raw=z.extractfile(members['PKG-INFO']).read()
        metadata=BytesParser().parsebytes(metadata_raw)
        description=metadata_raw.replace(b'\r\n',b'\n').split(b'\n\n',1)[1].decode('utf-8')
        if metadata['Name']!=NAME or metadata['Version']!=version or description.strip()!=(ROOT/'README.md').read_text(encoding='utf-8').strip():
            raise ValueError('distribution Name/Version/PyPI long description differs')
def manifest():
    version,source,tag=validate_source(tag_required=True)
    folder=ROOT/'dist'
    if set(p.name for p in folder.iterdir())!=package_names(version):raise ValueError('exact current wheel and sdist required')
    package_source_binding(folder,version)
    result=dict(schema='tomolab-product-distributions-v1',repository=REPO,version=version,source_sha=source,tag=tag,
        authorization_sha256=sha((ROOT/'docs/PRODUCT_RELEASE_AUTHORIZATION.json').read_bytes()),
        packages={p.name:dict(sha256=sha(p.read_bytes()),size=p.stat().st_size) for p in sorted(folder.iterdir())})
    write(ROOT/'verification/release-manifest.json',result)
    (ROOT/'verification/SHA256SUMS.txt').write_text(''.join(v['sha256']+'  '+n+'\n' for n,v in result['packages'].items()),encoding='ascii',newline='\n')
def registry(manifest):
    document=request('https://pypi.org/pypi/'+NAME+'/'+manifest['version']+'/json',missing=True)
    if document is None:return [],list(manifest['packages'])
    if document['info']['name']!=NAME or document['info']['version']!=manifest['version']:raise ValueError('registry package identity differs')
    entries={r['filename']:r for r in document['urls']}
    if len(entries)!=len(document['urls']):raise ValueError('duplicate registry filenames are ambiguous')
    if not set(entries)<=set(manifest['packages']):raise ValueError('existing registry inventory conflicts')
    for name,row in entries.items():
        expected=manifest['packages'][name]
        if row.get('yanked') or row['digests']['sha256']!=expected['sha256'] or row['size']!=expected['size']:
            raise ValueError('existing PyPI files conflict; no replacement or skip-existing')
    return list(entries),sorted(set(manifest['packages'])-set(entries))
def release_for_tag(tag):
    # Draft releases are not returned reliably by the public tag endpoint.
    releases=api('releases?per_page=100')
    matches=[r for r in releases if r['tag_name']==tag]
    if len(matches)>1:raise ValueError('ambiguous release identity')
    return matches[0] if matches else None
def verified_handoff():
    """Revalidate local artifact handoff without requesting OIDC or a GitHub token."""
    version,source,tag=inputs()
    if (os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_REF')!='refs/heads/main'
            or os.environ.get('GITHUB_SHA')!=source or git('rev-parse','HEAD')!=source):
        raise ValueError('artifact handoff is not the approved source checkout')
    record=read(ROOT/'verification/release-manifest.json')
    if (record.get('repository')!=REPO or record.get('source_sha')!=source or record.get('version')!=version
            or record.get('tag')!=tag or record.get('authorization_sha256')!=sha((ROOT/'docs/PRODUCT_RELEASE_AUTHORIZATION.json').read_bytes())):
        raise ValueError('manifest handoff identity or approval differs')
    verify_dist(ROOT/'dist',record);package_source_binding(ROOT/'dist',version)
    spec=importlib.util.spec_from_file_location('_product_handoff_gate',ROOT/'scripts/check-product-release.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    checked=gate.evaluate(root=ROOT,source_sha=source,version=version,tag=tag,
        ci_receipt=ROOT/'verification/source-ci.json',installation_receipt=ROOT/'verification/product-install.json',
        required_jobs=sorted(REQUIRED_JOBS))
    approved=read(ROOT/'verification/product-gate.json')
    for key in ('schema','repository','version','tag','authorization_sha256','source_sha','status',
                'product_publication_authorized','research_allow_release','ci_receipt_sha256',
                'installation_receipt_sha256','assets'):
        if checked.get(key)!=approved.get(key):raise ValueError('stale or altered product gate handoff: '+key)
    for asset in checked['assets'].values():
        if record['packages'].get(asset['name'],{}).get('sha256')!=asset['sha256']:
            raise ValueError('approved product gate and upload manifest differ')
    return record
def draft():
    version,source,tag=validate_source(tag_required=True)
    record=verified_handoff()
    if record['source_sha']!=source or record['version']!=version:raise ValueError('manifest identity mismatch')
    gate=read(ROOT/'verification/product-gate.json')
    if gate['status']!='PRODUCT_PUBLICATION_AUTHORIZED' or not gate['product_publication_authorized']:raise ValueError('actual product checks not authorized')
    present,missing=registry(record)
    release=release_for_tag(tag)
    if release is None:
        release=api('releases',method='POST',data=dict(tag_name=tag,target_commitish=source,name='Antemortem Structural Lab '+tag,
            body=(ROOT/('docs/releases/'+tag+'.md')).read_text(encoding='utf-8'),draft=True,prerelease=True))
    if release['prerelease'] is not True:raise ValueError('experimental prerelease required')
    assets={a['name']:a for a in api(f"releases/{release['id']}/assets?per_page=100")}
    paths=[*(ROOT/'dist'/name for name in record['packages']),ROOT/'verification/SHA256SUMS.txt',ROOT/'verification/release-manifest.json']
    if set(assets)-{p.name for p in paths}:raise ValueError('unexpected existing release assets')
    for p in paths:
        expected='sha256:'+sha(p.read_bytes())
        if p.name in assets:
            if assets[p.name].get('digest')!=expected:raise ValueError('immutable GitHub asset conflict; no clobber')
        else:
            if not release['draft']:raise ValueError('do not add files to an already public release')
            item=request(f"https://uploads.github.com/repos/{REPO}/releases/{release['id']}/assets?name={quote(p.name)}",method='POST',data=p.read_bytes(),github=True,content_type='application/octet-stream')
            if item.get('digest')!=expected:raise ValueError('GitHub upload readback digest mismatch')
    write(ROOT/'verification/draft-release.json',dict(status='PASS',release_id=release['id'],source_sha=source,version=version,tag=tag,packages_present=present,packages_missing=missing))
    output(publish_required=bool(missing))
def official_file(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='files.pythonhosted.org' or p.username or p.password or p.fragment:raise ValueError('official PyPI file URL required')
    return request(url,binary=True)
def public_verify():
    version,source,tag=validate_source(tag_required=True)
    record=verified_handoff()
    document=None
    for delay in (0,1,2,4,8,16):
        if delay:time.sleep(delay)
        present,missing=registry(record)
        if not missing:
            document=request('https://pypi.org/pypi/'+NAME+'/'+version+'/json');break
    if document is None:raise ValueError('PyPI public readback incomplete; upload is not retried')
    if document['info']['description'].strip()!=(ROOT/'README.md').read_text(encoding='utf-8').strip():raise ValueError('public PyPI description differs from verified English README')
    folder=ROOT/'verification/pypi-download';folder.mkdir(parents=True,exist_ok=False)
    for row in document['urls']:
        data=official_file(row['url']);expected=record['packages'][row['filename']]
        if sha(data)!=expected['sha256'] or len(data)!=expected['size']:raise ValueError('public PyPI bytes differ')
        (folder/row['filename']).write_bytes(data)
    subprocess.run([sys.executable,str(ROOT/'scripts/check-product-wheel.py'),'--directory',str(folder),
        '--source-sha',source,'--output',str(ROOT/'verification/public-install.json')],cwd=ROOT,check=True)
    release=release_for_tag(tag)
    if release is None:raise ValueError('prepared GitHub release missing')
    assets={a['name']:a for a in api(f"releases/{release['id']}/assets?per_page=100")}
    for name,item in record['packages'].items():
        if assets[name].get('digest')!='sha256:'+item['sha256']:raise ValueError('GitHub and PyPI assets differ')
    if release['draft']:
        api(f"releases/{release['id']}",method='PATCH',data=dict(draft=False,prerelease=True))
    release=api(f"releases/{release['id']}")
    if release['draft'] or not release['prerelease'] or release['tag_name']!=tag:raise ValueError('GitHub public prerelease readback differs')
    public_folder=ROOT/'verification/github-public-download';public_folder.mkdir(exist_ok=False)
    for name,item in record['packages'].items():
        data=request('https://github.com/'+REPO+'/releases/download/'+tag+'/'+name,binary=True)
        if sha(data)!=item['sha256'] or len(data)!=item['size']:raise ValueError('independent public GitHub download differs from PyPI')
        (public_folder/name).write_bytes(data)
    write(ROOT/'verification/public-release.json',dict(status='PASS',version=version,source_sha=source,tag=tag,
        github_url=release['html_url'],pypi_url='https://pypi.org/project/'+NAME+'/'+version+'/',
        github_draft=False,github_prerelease=True,packages=record['packages'],public_downloads_match=True,
        public_install_receipt_sha256=sha((ROOT/'verification/public-install.json').read_bytes()),research_authority_changed=False))
def upload_directory():
    record=verified_handoff()
    _,missing=registry(record)
    folder=ROOT/'upload';folder.mkdir(exist_ok=False)
    for name in missing:shutil.copyfile(ROOT/'dist'/name,folder/name)
    output(publish_required=bool(missing))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('source','tag','manifest','draft','upload-directory','public-verify'))
    args=p.parse_args()
    if args.phase=='source':validate_source()
    elif args.phase=='tag':create_tag()
    elif args.phase=='manifest':manifest()
    elif args.phase=='draft':draft()
    elif args.phase=='upload-directory':upload_directory()
    else:public_verify()
    print(json.dumps(dict(status='PASS',phase=args.phase,research_execution_calls=0)))
if __name__=='__main__':main()
