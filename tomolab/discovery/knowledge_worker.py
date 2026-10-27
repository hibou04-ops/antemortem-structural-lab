"""E7 JSON endpoint: no target imports, callbacks, storage or final labels."""
from copy import deepcopy
import json
import sys
import time

from .knowledge_engine import KnowledgeEngine, plan_knowledge
from .knowledge_protocol import MAX_MESSAGE, validate_request


def _diagnose(path):
    import os
    import socket
    from pathlib import Path
    try:
        with open(path, "rb"):
            pass
        host_read = True
    except OSError:
        host_read = False
    try:
        Path(__file__).with_name("write-probe").write_text("public E7 diagnostic")
        code_write = True
    except OSError:
        code_write = False
    return {"host_read": host_read, "code_write": code_write,
            "non_loopback_interfaces": sorted(n for _, n in socket.if_nameindex() if n != "lo"),
            "uid": getattr(os, "getuid", lambda: None)(),
            "private_env_present": "TOMOLAB_PRIVATE_SENTINEL" in os.environ}


def main():
    engine = None
    planned = False
    metrics = {"schema": "tomolab-knowledge-worker-cost-v1", "requests": 0,
               "wall_seconds": 0.0, "cpu_seconds": 0.0, "actions": {},
               "scope": "VALIDATION_COMPUTATION_JSON_ENCODING; EXCLUDES_STDIN_WAIT_AND_STDOUT_FLUSH"}
    while True:
        line = sys.stdin.readline(MAX_MESSAGE+1)
        if not line:
            return 0
        tick, cpu = time.perf_counter(), time.process_time()
        action = "invalid"
        try:
            if len(line) > MAX_MESSAGE or not line.endswith("\n"):
                raise ValueError("oversized or truncated knowledge message")
            message = validate_request(json.loads(line), None if engine is None else engine.spec,
                                       None if engine is None else engine.temporal_contract,
                                       None if engine is None else engine.target_provenance)
            action = message.pop("action")
            if action == "close":
                return 0
            if action == "metrics":
                result = deepcopy(metrics)
            elif action == "diagnose":
                result = _diagnose(message["host_sentinel"])
            elif action in ("init", "plan"):
                if engine is not None or planned:
                    raise ValueError("knowledge worker already initialized")
                if action == "plan":
                    archive = message.pop("archive")
                    spec = message.pop("spec")
                    result = plan_knowledge(archive, spec, **message)
                    planned = True
                else:
                    engine = KnowledgeEngine(**message)
                    result = {"initialized": True}
            else:
                if engine is None:
                    raise ValueError("knowledge init required")
                if action == "observe":
                    result = engine.observe(message["evidence"])
                else:
                    result = getattr(engine, action)()
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        rendered = json.dumps(response, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        if len(rendered)+1 > MAX_MESSAGE:
            rendered = json.dumps({"ok": False, "error": "ValueError: knowledge response exceeds bound"})
        if action != "metrics":
            elapsed, used = time.perf_counter()-tick, time.process_time()-cpu
            metrics["requests"] += 1
            metrics["wall_seconds"] += elapsed
            metrics["cpu_seconds"] += used
            row = metrics["actions"].setdefault(action, {"calls": 0, "wall_seconds": 0.0, "cpu_seconds": 0.0})
            row["calls"] += 1
            row["wall_seconds"] += elapsed
            row["cpu_seconds"] += used
        print(rendered, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
