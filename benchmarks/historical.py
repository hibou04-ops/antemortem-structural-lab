"""Reviewed historical non-security defects; external execution is container-only.

Metadata reads parse source but never import it. Only the explicit reviewed
container gate can load the exact selected original function capsules.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
import json
import operator
from pathlib import Path
import string
import sys
import types

from tomolab.discovery.schema import digest
from tomolab.discovery.online_schema import validate_contract, validate_input

DEFAULT_CATALOG=Path(__file__).parent/'historical'
SCHEMA='tomolab-reviewed-historical-corpus-v1'
ADAPTERS={'interpose','bucket','windowed','accumulate','split','punct','lines','bytes'}
FORBIDDEN_NAMES={'eval','exec','open','__import__','compile','breakpoint','input'}
STDLIB_IMPORTS={'itertools','collections','math','re','string'}
ADAPTER_INPUTS={'interpose':'sequence_int','bucket':'sequence_int','windowed':'sequence_int',
                'accumulate':'sequence_int','split':'sequence_int','punct':'text','lines':'text','bytes':'float'}


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(catalog, relative):
    if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('relative reviewed catalog path required')
    root=Path(catalog).resolve(strict=True)
    path=(root/relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('reviewed catalog path escaped its root')
    return path


def _statement_name(node):
    if isinstance(node,(ast.FunctionDef,ast.ClassDef)):
        return node.name
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
        return node.targets[0].id
    if (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
        and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name)):
        return node.value.func.value.id+'.'+node.value.func.attr
    return None


def read_manifest(catalog=None):
    catalog=Path(catalog or DEFAULT_CATALOG).resolve(strict=True)
    data=(catalog/'manifest.json').read_bytes()
    if len(data)>1_000_000:
        raise ValueError('bounded reviewed historical manifest required')
    value=json.loads(data)
    if (value.get('schema')!=SCHEMA or value.get('scope')!='HISTORICAL_DEFECT_REDISCOVERY'
        or value.get('external_execution')!='REVIEWED_CONTAINER_ONLY'
        or not isinstance(value.get('cases'),list) or len(value['cases'])>20):
        raise ValueError('reviewed historical corpus schema or execution scope differs')
    seen=set()
    for item in value['cases']:
        if item['id'] in seen or item['role'] not in ('SOURCE','TARGET') or item['adapter'] not in ADAPTERS:
            raise ValueError('duplicate or unsupported reviewed case')
        seen.add(item['id']);validate_contract(item['contract'])
        if item['contract']['kind']!=ADAPTER_INPUTS[item['adapter']]:
            raise ValueError('adapter cannot disguise its original public input kind')
        license_raw=_path(catalog,item['license_file']).read_bytes()
        if _hash(license_raw)!=item['license_provenance']['retained_sha256']:
            raise ValueError('retained original license changed')
        for version in ('buggy','fixed'):
            record=item[version]
            raw=_path(catalog,record['capsule']).read_bytes()
            if _hash(raw)!=record['capsule_sha256'] or len(raw)>100_000:
                raise ValueError('reviewed original capsule bytes changed')
            source=raw.decode('utf-8');tree=ast.parse(source)
            for statement in record['source_statements']:
                matches=[node for node in tree.body if _statement_name(node)==statement['name']]
                if (len(matches)!=1 or _hash(ast.get_source_segment(source,matches[0]).encode())
                    !=statement['normalized_lf_source_sha256']):
                    raise ValueError('original reviewed source statement changed')
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    imports=([a.name.split('.')[0]for a in node.names]if isinstance(node,ast.Import)
                             else[(node.module or '').split('.')[0]])
                    if any(name not in STDLIB_IMPORTS for name in imports):
                        raise ValueError('unreviewed external capsule dependency')
                if isinstance(node,ast.Name) and node.id in FORBIDDEN_NAMES:
                    raise ValueError('unreviewed external execution primitive')
            targets=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==item['function']]
            if len(targets)!=1:
                raise ValueError('one fixed original function or class required')
    return value


def _oracle_interpose(point):
    result=[]
    for value in point:
        if result:result.append(0)
        result.append(value)
    return result


def _oracle_bucket(point):
    # The reviewed public AllowedKeys(empty set) validator rejects every key.
    return []


def _oracle_windowed(point):
    if not point:return []
    if len(point)==1:return [(point[0],None)]
    return [(point[i],point[i+1])for i in range(len(point)-1)]


def _oracle_accumulate(point):
    total=0;result=[]
    for value in point:
        total+=value;result.append(total)
    return result


def _oracle_split(point):
    return [list(point)]


def _oracle_punct(point):
    separators=set(string.punctuation+string.whitespace)
    result=[];current=[]
    for char in point:
        if char in separators:
            if current:result.append(''.join(current));current=[]
        else:current.append(char)
    if current:result.append(''.join(current))
    return result


def _oracle_lines(point):
    if not point:return []
    endings={'\n','\v','\f','\r','\x85','\u2028','\u2029'}
    result=[];start=0;i=0
    while i<len(point):
        width=2 if point[i:i+2]=='\r\n' else 1 if point[i] in endings else 0
        if width:
            result.append(point[start:i]);i+=width;start=i
            if start==len(point):result.append('')
        else:i+=1
    if start<len(point):result.append(point[start:])
    return result


def _oracle_bytes(point):
    # Independently use the displayed B magnitude to select the public unit.
    # The declared finite [-2048,2048] domain only needs B and K.
    large=float(format(abs(point),'.0f'))>=1024
    return format(point/(1024 if large else 1),'.0f')+('K'if large else'B')


ORACLES={'interpose':_oracle_interpose,'bucket':_oracle_bucket,'windowed':_oracle_windowed,
         'accumulate':_oracle_accumulate,'split':_oracle_split,'punct':_oracle_punct,
         'lines':_oracle_lines,'bytes':_oracle_bytes}


class _AllowedKeys(set):
    """Same valid falsey callable configuration as upstream regression #1308."""
    def __call__(self,key):
        return key in self


def _apply(function,point,adapter):
    if adapter=='interpose':return list(function(0,point))
    if adapter=='bucket':return list(function(point,key=lambda value:value,validator=_AllowedKeys()))
    if adapter=='windowed':return list(function(point,2))
    if adapter=='accumulate':return list(function(operator.add,point))
    if adapter=='split':return list(function(point,maxsplit=0))
    if adapter=='punct':return function(point)
    if adapter=='lines':return list(function(point))
    if adapter=='bytes':return function(point)
    raise ValueError('unsupported reviewed public API adapter')


def _normalized_ast(source,function):
    tree=ast.parse(source)
    target=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==function)
    clone=deepcopy(target)
    for node in ast.walk(clone):
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)):node.name='DEFINITION'
        elif isinstance(node,ast.arg):node.arg='ROLE'
        elif isinstance(node,ast.Name):node.id='NAME'
        elif isinstance(node,ast.Constant):node.value=type(node.value).__name__
    return _hash(ast.dump(clone,include_attributes=False).encode())


@dataclass
class HistoricalCase:
    entry:dict
    catalog:Path
    version:str
    role:str
    target:object=None
    oracle:object=None
    upstream:object=None

    @property
    def id(self):return self.entry['id']+('-fixed-control'if self.role=='CONTROL'else'')
    @property
    def axis(self):return self.entry['contract']['kind']
    @property
    def mechanism(self):return self.entry['mechanism']
    @property
    def contract(self):return deepcopy(self.entry['contract'])
    @property
    def lineage(self):return self.entry['implementation_lineage']

    def metadata(self):
        e=self.entry;r=e[self.version]
        source=_path(self.catalog,r['capsule']).read_text(encoding='utf-8')
        original=dict(project=e['project'],path=e['original_path'],function=e['function'])
        identity=dict(canonical_function_identity=digest(dict(original,revision=r['revision'])),
            cross_revision_function_key=digest(original),
            normalized_ast_clone_sha256=_normalized_ast(source,e['function']),
            implementation_sha256=r['capsule_sha256'])
        return dict(id=self.id,axis=self.axis,mechanism=self.mechanism,role=self.role,
            contract=self.contract,lineage=self.lineage,implementation_lineage=self.lineage,identity=identity,
            oracle_sha256=_hash(inspect.getsource(ORACLES[e['adapter']]).encode()),
            origin='REVIEWED_UPSTREAM_HISTORICAL_DEFECT',project=e['project'],license=e['license'],
            bug_identity=e['id'],issue=e['issue'],buggy_revision=e['buggy_revision'],fixed_revision=e['fixed_revision'],
            original_path=e['original_path'],original_function=e['function'],implementation_revision=r['revision'],
            mechanism_family=e['mechanism'],input_kind=e['contract']['kind'],
            original_input_roles=deepcopy(e['public_parameters']),public_contract=e['public_contract'],
            adapter_kind=e['adapter'],adapter_mri_scope=('UNSUPPORTED_CLASS_EXPLICIT_BLACK_BOX'
                if e['adapter']=='bucket' else 'REVIEWED_ORIGINAL_AST_ROOT_LINES_ARGUMENT_MAPPING_UNKNOWN'),
            adapter_scope=e['adapter_limits'],control_group=e['id'],
            usage_role='CLEAN_CONTROL'if self.role=='CONTROL'else'POSITIVE_REPRODUCTION',
            project_independence='PROJECT_IDENTITY_VERIFIED_CODE_LINEAGE_REVIEW_REQUIRED',
            developer_known=True,fixed_is_independent_implementation=False)

    def direct(self,point):
        from tomolab.historical import require_reviewed_container
        require_reviewed_container()
        if self.upstream is None:raise PermissionError('load the reviewed case inside its container first')
        return _apply(self.upstream,point,self.entry['adapter'])


def _bind(case):
    from tomolab.historical import require_reviewed_container
    require_reviewed_container()
    record=case.entry[case.version]
    path=_path(case.catalog,record['capsule']);raw=path.read_bytes()
    if _hash(raw)!=record['capsule_sha256']:raise ValueError('capsule changed before original execution')
    module=types.ModuleType('_reviewed_historical_'+case.entry['id'].replace('-','_')+'_'+case.version)
    module.__file__=str(path)
    # Only exact pinned, statically reviewed capsules reach this gated compile.
    exec(compile(raw,str(path),'exec'),module.__dict__)
    function=getattr(module,case.entry['function'])
    watched=({function.__code__}if inspect.isfunction(function)else
             {getattr(function,name).__code__ for name in ('__init__','__iter__')})
    metrics=dict(adapter_invocations=0,original_entry_events=0,
        generator_resume_events_are_not_distinct_target_calls=True,
        original_code_sha256=record['capsule_sha256'])
    adapter=case.entry['adapter']
    def target(point):
        metrics['adapter_invocations']+=1
        previous=sys.getprofile()
        def profile(frame,event,arg):
            if event=='call'and frame.f_code in watched:metrics['original_entry_events']+=1
            if previous is not None:previous(frame,event,arg)
        try:
            sys.setprofile(profile)
            return _apply(function,point,adapter)
        finally:sys.setprofile(previous)
    target.upstream_execution_metrics=metrics
    target.upstream_function=function
    case.target=target;case.oracle=ORACLES[adapter];case.upstream=function
    return case


def cases(load=False,catalog=None):
    if load:
        from tomolab.historical import require_reviewed_container
        require_reviewed_container()
    root=Path(catalog or DEFAULT_CATALOG).resolve(strict=True)
    result=[]
    for entry in read_manifest(root)['cases']:
        case=HistoricalCase(deepcopy(entry),root,'buggy',entry['role'])
        result.append(_bind(case)if load else case)
        if entry['role']=='TARGET':
            control=HistoricalCase(deepcopy(entry),root,'fixed','CONTROL')
            result.append(_bind(control)if load else control)
    return result


def load_case(case_id,catalog=None):
    from tomolab.historical import require_reviewed_container
    require_reviewed_container()
    selected=[case for case in cases(load=False,catalog=catalog)if case.id==case_id]
    if len(selected)!=1:raise ValueError('one reviewed allowlisted case identity required')
    return _bind(selected[0])
