"""Typed public predicates interpreted as data, never eval/exec or imports.

Predicates describe possible failure membership, not the program's semantics.
Unsupported/undefined operations abstain rather than inventing a truth label.
"""
from copy import deepcopy
import ast
import math
import re

from .schema import canonical, decode_value, digest, keys, validate_inputs, validate_spec

MAX_NODES = 96
MAX_DEPTH = 16
COMPARISONS = {"eq", "ne", "lt", "le", "gt", "ge"}
ARITHMETIC = {"add", "sub", "mul", "mod", "neg", "abs", "len", "sum", "min", "max"}


def _numeric(type_):
    return type_["kind"] in {"int", "float"}


def validate_predicate(predicate, spec):
    """Validate syntax and types against semantic roles in the public contract."""
    spec = validate_spec(spec)
    roles = {item["role"]: item["type"] for item in spec["inputs"]}
    count = [0]

    def check(node, depth=0):
        count[0] += 1
        if depth > MAX_DEPTH or count[0] > MAX_NODES:
            raise ValueError("predicate exceeds bounded expression size")
        if type(node) is bool:
            return {"kind": "bool"}
        if type(node) in (int, float):
            if not math.isfinite(node) or abs(node) > 10**12:
                raise ValueError("predicate requires bounded finite constants")
            return {"kind": "int" if type(node) is int else "float"}
        if type(node) is str:
            if len(node) > 64:
                raise ValueError("predicate literal is too long")
            return {"kind": "str"}
        if not isinstance(node, dict):
            raise ValueError("predicate must be JSON syntax")
        if "var" in node:
            keys(node, ("var",))
            if node["var"] not in roles:
                raise ValueError("predicate references an undeclared semantic role")
            return roles[node["var"]]
        op = node.get("op")
        if op in COMPARISONS:
            keys(node, ("op", "left", "right"))
            left, right = check(node["left"], depth+1), check(node["right"], depth+1)
            if op in ("eq", "ne"):
                if left["kind"] != right["kind"] and not (_numeric(left) and _numeric(right)):
                    raise ValueError("predicate compares incompatible types")
            elif not ((_numeric(left) and _numeric(right)) or left["kind"] == right["kind"] == "str"):
                raise ValueError("ordered comparison requires numbers or strings")
            return {"kind": "bool"}
        if op in ("and", "or", "not"):
            keys(node, ("op", "args"))
            args = node["args"]
            if not isinstance(args, list) or (len(args) != 1 if op == "not" else not 2 <= len(args) <= 16):
                raise ValueError("invalid Boolean predicate arity")
            if any(check(arg, depth+1)["kind"] != "bool" for arg in args):
                raise ValueError("Boolean predicate requires Boolean operands")
            return {"kind": "bool"}
        if op not in ARITHMETIC:
            raise ValueError("unsupported predicate operation")
        keys(node, ("op", "args"))
        args = node["args"]
        arity = 2 if op in {"add", "sub", "mul", "mod"} else 1
        if not isinstance(args, list) or len(args) != arity:
            raise ValueError("invalid predicate arithmetic arity")
        types = [check(arg, depth+1) for arg in args]
        if op == "len":
            if types[0]["kind"] not in {"str", "list", "tuple", "dict"}:
                raise ValueError("len predicate requires a bounded container")
            return {"kind": "int"}
        if op in {"sum", "min", "max"}:
            type_ = types[0]
            children = [type_["items"]] if type_["kind"] == "list" else type_.get("items", []) if type_["kind"] == "tuple" else []
            if not children or any(not _numeric(child) for child in children):
                raise ValueError("aggregate predicate requires a numeric list/tuple")
            return {"kind": "float" if any(child["kind"] == "float" for child in children) else "int"}
        if any(not _numeric(type_) for type_ in types):
            raise ValueError("arithmetic predicate requires numeric operands")
        if op == "mod" and (type(args[1]) is not int or args[1] <= 0 or types[0]["kind"] != "int"):
            raise ValueError("mod predicate requires an integer and positive constant modulus")
        return {"kind": "float" if any(type_["kind"] == "float" for type_ in types) else "int"}

    if check(predicate)["kind"] != "bool":
        raise ValueError("predicate root must be Boolean")
    if len(canonical(predicate)) > 16000:
        raise ValueError("predicate serialized size exceeds limit")
    return deepcopy(predicate)


def predicate_roles(predicate):
    if isinstance(predicate, dict):
        if "var" in predicate:
            return {predicate["var"]}
        return set().union(*(predicate_roles(value) for value in predicate.values()))
    if isinstance(predicate, list):
        return set().union(*(predicate_roles(value) for value in predicate))
    return set()


def predicate_id(predicate):
    return "AST-" + digest(predicate)[:20]


def _interpret(node, by_role):
    if not isinstance(node, dict):
        return node
    if "var" in node:
        return by_role[node["var"]]
    op = node["op"]
    if op == "and":
        return all(_interpret(arg, by_role) for arg in node["args"])
    if op == "or":
        return any(_interpret(arg, by_role) for arg in node["args"])
    if op == "not":
        return not _interpret(node["args"][0], by_role)
    if op in COMPARISONS:
        a, b = _interpret(node["left"], by_role), _interpret(node["right"], by_role)
        return {"eq": lambda: a == b, "ne": lambda: a != b,
                "lt": lambda: a < b, "le": lambda: a <= b,
                "gt": lambda: a > b, "ge": lambda: a >= b}[op]()
    args = [_interpret(arg, by_role) for arg in node["args"]]
    if op in {"len", "abs", "sum", "min", "max"}:
        return {"len": len, "abs": abs, "sum": sum, "min": min, "max": max}[op](args[0])
    if op == "neg":
        return -args[0]
    a, b = args
    return {"add": lambda: a+b, "sub": lambda: a-b,
            "mul": lambda: a*b, "mod": lambda: a%b}[op]()


def predicate_holds(predicate, inputs, spec):
    clean = validate_predicate(predicate, spec)
    inputs = validate_inputs(inputs, spec)
    return predicate_value(clean, inputs, spec)


def predicate_value(predicate, inputs, spec):
    """Interpret already validated data. Undefined aggregate predicates abstain."""
    by_role = {item["role"]: decode_value(inputs[item["name"]],item["type"]) for item in spec["inputs"]}
    try:
        value = _interpret(predicate, by_role)
        return value if type(value) is bool else False
    except (ArithmeticError, ValueError, TypeError, KeyError, OverflowError):
        return False


def compile_guard(node, roles):
    """Translate a whitelisted AST expression; no source is executed or retained."""
    count = [0]
    def visit(item, depth=0):
        count[0] += 1
        if count[0] > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("guard exceeds expression budget")
        child = lambda n: visit(n, depth+1)
        if isinstance(item, ast.Constant) and type(item.value) in (int, float, str, bool):
            return item.value
        if isinstance(item, ast.Name) and item.id in roles:
            return {"var": roles[item.id]}
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, (ast.USub, ast.UAdd, ast.Not)):
            value = child(item.operand)
            if isinstance(item.op, ast.UAdd):
                return value
            if isinstance(item.op, ast.USub) and type(value) in (int, float):
                return -value
            return {"op": "not" if isinstance(item.op, ast.Not) else "neg", "args": [value]}
        if isinstance(item, ast.BinOp):
            op = {ast.Add:"add", ast.Sub:"sub", ast.Mult:"mul", ast.Mod:"mod"}.get(type(item.op))
            if op:
                return {"op": op, "args": [child(item.left), child(item.right)]}
        if isinstance(item, ast.BoolOp) and isinstance(item.op, (ast.And, ast.Or)):
            return {"op":"and" if isinstance(item.op, ast.And) else "or", "args":[child(v) for v in item.values]}
        if isinstance(item, ast.Compare):
            operators = {ast.Eq:"eq", ast.NotEq:"ne", ast.Lt:"lt", ast.LtE:"le", ast.Gt:"gt", ast.GtE:"ge"}
            operands = [item.left, *item.comparators]
            parts=[]
            for index, operator in enumerate(item.ops):
                if type(operator) not in operators:
                    raise ValueError("unsupported guard comparison")
                parts.append({"op":operators[type(operator)],"left":child(operands[index]),"right":child(operands[index+1])})
            return parts[0] if len(parts)==1 else {"op":"and","args":parts}
        if (isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                and item.func.id in {"len","abs","sum","min","max"}
                and item.func.id not in roles and len(item.args)==1 and not item.keywords):
            return {"op":item.func.id,"args":[child(item.args[0])]}
        raise ValueError("unsupported guard syntax or undeclared local dependency")
    return visit(node)


def validate_public_ir(ir, spec=None):
    """Strict public-data validation shared by evaluator and generator boundary.

    A hash only verifies consistency; source publicity and semantic roles remain
    the caller's explicitly approved contract. Raw source and Oracle channels
    have no accepted fields, including inside graphs and predicate nodes.
    """
    required = ("schema","source_sha256","function","parameters","return_annotation","semantic_roles",
                "graph","graph_signature","control","operators","calls","dependencies","state_effects",
                "exception_conditions","unsupported","status","claim")
    keys(ir, required, ("predicates","predicate_origins","predicate_rejections","constraint_graph"))
    if ir["schema"] != "tomolab-structural-ir-v1" or ir["status"] not in {"SUPPORTED_STATIC_IR","PARTIAL_STATIC_IR"}:
        raise ValueError("unsupported public IR schema/status")
    for name in ("source_sha256","graph_signature"):
        if not isinstance(ir[name],str) or not re.fullmatch(r"[a-f0-9]{64}",ir[name]):
            raise ValueError("public IR digest is invalid")
    def graph_digest(graph):
        import hashlib, json
        return hashlib.sha256(json.dumps(graph,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if graph_digest(ir["graph"]) != ir["graph_signature"]:
        raise ValueError("public IR graph digest mismatch")
    if not isinstance(ir["function"],str) or not ir["function"].isidentifier() or len(ir["function"])>160:
        raise ValueError("invalid public IR function")
    if ir["semantic_roles"] not in {"DECLARED","POSITIONAL_ONLY"}:
        raise ValueError("invalid semantic role provenance")
    def bounded_id(value):
        if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}",value):
            raise ValueError("invalid bounded IR identifier")
    def annotation(value,depth=0):
        if depth>4:
            raise ValueError("IR annotation exceeds depth")
        if isinstance(value,str) and value in {"UNKNOWN","int","float","str","bool","list","dict","tuple","None"}:
            return
        keys(value,("kind","items"))
        if value["kind"] not in {"list","dict","tuple"} or not isinstance(value["items"],list) or len(value["items"])>8:
            raise ValueError("unsupported IR annotation")
        for child in value["items"]:
            annotation(child,depth+1)
    annotation(ir["return_annotation"])
    if not isinstance(ir["parameters"],list) or not 1<=len(ir["parameters"])<=6:
        raise ValueError("public IR needs bounded parameters")
    for parameter in ir["parameters"]:
        keys(parameter,("name","role","annotation"))
        bounded_id(parameter["name"]); bounded_id(parameter["role"])
        annotation(parameter["annotation"])
    for name in ("name","role"):
        if len({p[name] for p in ir["parameters"]})!=len(ir["parameters"]):
            raise ValueError("duplicate IR parameter mapping")
    count=[0]
    def graph_node(node,depth=0):
        count[0]+=1
        if depth>64 or count[0]>10000:
            raise ValueError("IR graph exceeds bounded size")
        if isinstance(node,list):
            for child in node: graph_node(child,depth+1)
            return
        if not isinstance(node,dict):
            if node is not None and not (isinstance(node,str) and node in {"int","float","str","bool","NoneType","bytes","complex","Ellipsis","list","tuple","UNKNOWN"}):
                raise ValueError("IR graph contains nonstructural data")
            return
        kind=node.get("node")
        if kind=="Constant":
            keys(node,("node","type")); graph_node(node["type"],depth+1); return
        if kind=="Name":
            keys(node,("node","role","context")); bounded_id(node["role"])
            if node["context"] not in {"Load","Store","Del"}: raise ValueError("invalid IR name context")
            return
        if kind=="arg":
            keys(node,("node","role","annotation")); bounded_id(node["role"]); annotation(node["annotation"]); return
        cls=getattr(ast,kind,None) if isinstance(kind,str) else None
        if not isinstance(cls,type) or not issubclass(cls,ast.AST):
            raise ValueError("unknown public IR AST node")
        if set(node)-{"node"}-set(cls._fields):
            raise ValueError("public IR graph has unsupported fields")
        for name,value in node.items():
            if name=="node": continue
            if name=="annotation": annotation(value)
            elif name in {"attr","arg"}: bounded_id(value)
            else: graph_node(value,depth+1)
    graph_node(ir["graph"])
    keys(ir["control"],(),("If","IfExp","For","While","Try","Match"))
    if any(type(n) is not int or not 0<=n<=10000 for n in ir["control"].values()):
        raise ValueError("invalid control counts")
    for name in ("operators","calls","unsupported"):
        if not isinstance(ir[name],list) or len(ir[name])>128:
            raise ValueError("invalid IR label list")
        for label in ir[name]: bounded_id(label)
    for name in ("dependencies","state_effects","exception_conditions"):
        if not isinstance(ir[name],list) or len(ir[name])>1000:
            raise ValueError("invalid IR relation list")
    for relation in ir["dependencies"]:
        keys(relation,("writes","reads","kind")); bounded_id(relation["kind"])
        for field in ("writes","reads"):
            if not isinstance(relation[field],list) or len(relation[field])>128: raise ValueError("invalid dependency")
            for label in relation[field]: bounded_id(label)
    for effect in ir["state_effects"]:
        keys(effect,("kind","dependencies"),("operation",)); bounded_id(effect["kind"])
        if "operation" in effect: bounded_id(effect["operation"])
        if not isinstance(effect["dependencies"],list) or len(effect["dependencies"])>128: raise ValueError("invalid state relation")
        for label in effect["dependencies"]: bounded_id(label)
    for condition in ir["exception_conditions"]: graph_node(condition)
    if ir["claim"] != "syntactic correspondence only; constants omitted; no semantic or purity proof":
        raise ValueError("unsupported IR claim")
    predicates=ir.get("predicates",[])
    if not isinstance(predicates,list) or len(predicates)>64:
        raise ValueError("bounded public predicates required")
    if any(not predicate_roles(predicate) for predicate in predicates):
        raise ValueError("public query predicates must depend on declared input roles")
    if spec is not None:
        spec=validate_spec(spec)
        if {p["name"]:p["role"] for p in ir["parameters"]}!={p["name"]:p["role"] for p in spec["inputs"]}:
            raise ValueError("IR parameters do not match declared roles")
        from .transfer import _annotation_matches
        declared={item["name"]:item["type"] for item in spec["inputs"]}
        if any(not _annotation_matches(parameter["annotation"],declared[parameter["name"]]) for parameter in ir["parameters"]):
            raise ValueError("public IR annotation contradicts declared type")
        for predicate in predicates: validate_predicate(predicate,spec)
    else:
        # Syntax is recursively checked with the actual declared type contract
        # before engine construction; this stage still rejects hidden channels.
        def clean_node(value,depth=0):
            if depth>MAX_DEPTH: raise ValueError("predicate exceeds depth")
            if isinstance(value,dict):
                if "var" in value:
                    keys(value,("var",)); bounded_id(value["var"])
                elif value.get("op") in COMPARISONS:
                    keys(value,("op","left","right")); clean_node(value["left"],depth+1); clean_node(value["right"],depth+1)
                elif value.get("op") in ARITHMETIC|{"and","or","not"}:
                    keys(value,("op","args"))
                    if not isinstance(value["args"],list) or len(value["args"])>16: raise ValueError("invalid predicate args")
                    for child in value["args"]: clean_node(child,depth+1)
                else: raise ValueError("invalid predicate operation")
            elif type(value) not in (str,int,float,bool) or (isinstance(value,str) and len(value)>64):
                raise ValueError("invalid predicate literal")
        for predicate in predicates: clean_node(predicate)
    for name in ("predicate_origins","predicate_rejections"):
        if name in ir:
            if not isinstance(ir[name],list) or len(ir[name])>128: raise ValueError("invalid predicate provenance")
            for row in ir[name]:
                keys(row,("kind","line"),("index","reason")); bounded_id(row["kind"])
                if type(row["line"]) is not int or not 0<=row["line"]<=100000: raise ValueError("invalid source line")
                if "index" in row and (type(row["index"]) is not int or not 0<=row["index"]<64): raise ValueError("invalid predicate index")
                if "reason" in row and row["reason"]!="UNSUPPORTED_GUARD_SYNTAX": raise ValueError("invalid predicate rejection")
    if "constraint_graph" in ir:
        graph=ir["constraint_graph"]; keys(graph,("nodes","edges"))
        if not isinstance(graph["nodes"],list) or len(graph["nodes"])>64 or not isinstance(graph["edges"],list) or len(graph["edges"])>384:
            raise ValueError("invalid constraint graph")
        expected_nodes=[{"id":predicate_id(p),"kind":"public-ast-guard"} for p in predicates]
        expected_edges=[{"from":predicate_id(p),"to":role,"kind":"depends-on-role"} for p in predicates for role in sorted(predicate_roles(p))]
        if graph!={"nodes":expected_nodes,"edges":expected_edges}: raise ValueError("constraint graph is not derived from predicates")
    if len(canonical(ir))>262144:
        raise ValueError("public IR exceeds serialized size")
    return deepcopy(ir)
