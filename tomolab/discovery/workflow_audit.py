"""Bounded static audit of the repository's checked-in GitHub job conditions."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Sequence

from .schema import digest


@dataclass(frozen=True)
class JobCondition:
    name: str
    line: int
    condition_line: int
    condition: str
    matrix_size: int
    needs: Sequence[str]


def condition_value(expression: str, context: dict[str, Any]) -> bool:
    text = expression.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    text = re.sub(r"\btrue\b", "True", text)
    text = re.sub(r"\bfalse\b", "False", text)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text).strip()
    node = ast.parse(text, mode="eval")

    def value(item: ast.AST) -> Any:
        if isinstance(item, ast.Constant) and type(item.value) in (str, bool):
            return item.value
        if isinstance(item, ast.Name) and item.id in context:
            return context[item.id]
        if isinstance(item, ast.Attribute) and not item.attr.startswith("_"):
            parent = value(item.value)
            if type(parent) is dict and item.attr in parent:
                return parent[item.attr]
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            return not value(item.operand)
        if isinstance(item, ast.BoolOp):
            values = [value(n) for n in item.values]
            if isinstance(item.op, ast.And):
                return all(values)
            if isinstance(item.op, ast.Or):
                return next((n for n in values if n), values[-1])
        if isinstance(item, ast.Compare) and len(item.ops) == len(item.comparators) == 1:
            left, right = value(item.left), value(item.comparators[0])
            if isinstance(item.ops[0], ast.Eq):
                return left == right
            if isinstance(item.ops[0], ast.NotEq):
                return left != right
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and not item.keywords:
            args = [value(arg) for arg in item.args]
            if item.func.id == "startsWith" and len(args) == 2 and all(type(v) is str for v in args):
                return args[0].lower().startswith(args[1].lower())
            if item.func.id in ("success", "always") and not args:
                return True
        raise ValueError("unsupported workflow expression; no evaluation fallback")

    return bool(value(node.body))


def job_conditions(text: str) -> list[JobCondition]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == "jobs:"), None)
    if start is None:
        raise ValueError("literal checked-in jobs block required")
    headers = [(i, re.fullmatch(r"  ([A-Za-z][A-Za-z0-9_-]*):", line)) for i, line in enumerate(lines) if i > start]
    headers = [(i, match.group(1)) for i, match in headers if match is not None]
    jobs = []
    for offset, (begin, name) in enumerate(headers):
        end = headers[offset + 1][0] if offset + 1 < len(headers) else len(lines)
        condition, condition_line, matrix, needs = "true", begin + 1, 1, ()
        for index in range(begin + 1, end):
            line = lines[index]
            if line.startswith("    if: "):
                condition, condition_line = line[8:].strip(), index + 1
            if line.startswith("    needs: "):
                needs = tuple(n.strip(" '\"") for n in line[11:].strip("[]").split(","))
            match = re.fullmatch(r"        [A-Za-z0-9_-]+: \[([^]]+)\]", line)
            if match:
                matrix *= len(match.group(1).split(","))
        jobs.append(JobCondition(name, begin + 1, condition_line, condition, matrix, needs))
    if len({job.name for job in jobs}) != len(jobs):
        raise ValueError("duplicate job definitions")
    return jobs


def audit_workflow(path: str | Path, *, branch: str, event: str = "pull_request") -> dict[str, Any]:
    if type(branch) is not str or not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", branch):
        raise ValueError("bounded literal branch identity required")
    if event not in ("pull_request", "push", "workflow_dispatch"):
        raise ValueError("explicit supported event required")
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 131072:
        raise ValueError("bounded checked-in workflow required")
    context = dict(github=dict(head_ref=branch if event == "pull_request" else "", ref_name=branch,
        ref="refs/heads/" + branch, event_name=event, repository="hibou04-ops/antemortem-structural-lab"),
        inputs=dict(run_real_qualification=False, run_sequence_qualification=False))
    rows = []
    states: dict[str, bool] = {}
    for job in job_conditions(raw.decode("utf8")):
        active = condition_value(job.condition, context) and all(states.get(name, False) for name in job.needs)
        states[job.name] = active
        rows.append(dict(name=job.name, definition_line=job.line, condition_line=job.condition_line,
            expression=job.condition, expected="RUN" if active else "SKIP", configured_matrix_size=job.matrix_size,
            expected_expanded_jobs=job.matrix_size if active else 1))
    result = dict(schema="tomolab-workflow-condition-audit-v1", workflow=path.name,
        workflow_sha256=hashlib.sha256(raw).hexdigest(), branch=branch, event=event, definitions=len(rows), jobs=rows,
        expected_run_jobs=sum(r["expected_expanded_jobs"] for r in rows if r["expected"] == "RUN"),
        expected_skipped_jobs=sum(r["expected_expanded_jobs"] for r in rows if r["expected"] == "SKIP"),
        source_class="STATIC_CHECKED_IN_CONDITIONS_NOT_ACTUAL_PLATFORM_RESULTS", runtime_execution=0, network_requests=0)
    result["sha256"] = digest(result)
    return result
