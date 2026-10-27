"""E6 JSON endpoint: public contracts and minimal development labels only."""
import json
import sys
import time

from .temporal_engine import TemporalEngine
from .temporal_protocol import MAX_MESSAGE, validate_request


def main():
    engine = None
    transferred = False
    metrics = {"schema":"tomolab-temporal-worker-cost-v1","requests":0,
               "wall_seconds":0.0,"cpu_seconds":0.0,"actions":{},
               "scope":"VALIDATION_COMPUTATION_JSON_ENCODING; EXCLUDES_STDIN_WAIT_AND_STDOUT_FLUSH"}
    while True:
        line = sys.stdin.readline(MAX_MESSAGE+1)
        if not line:
            break
        started,cpu = time.perf_counter(),time.process_time()
        action = "invalid"
        try:
            if len(line)>MAX_MESSAGE or not line.endswith("\n"):
                raise ValueError("oversized or truncated temporal message")
            message = validate_request(json.loads(line),None if engine is None else engine.spec,
                                       None if engine is None else engine.temporal_contract)
            action = message.pop("action")
            if action == "close":
                return 0
            if action == "metrics":
                from copy import deepcopy
                result = deepcopy(metrics)
            elif action == "init":
                if engine is not None or transferred:
                    raise ValueError("temporal worker already initialized")
                engine = TemporalEngine(**message)
                result = {"initialized":True}
            elif action == "transfer":
                if engine is not None or transferred:
                    raise ValueError("temporal transfer requires a fresh worker")
                from .temporal_transfer import transfer_temporal
                message["target_spec"] = message.pop("spec")
                result = transfer_temporal(**message)
                transferred = True
            elif action == "diagnose":
                import os
                import socket
                from pathlib import Path
                try:
                    with open(message["host_sentinel"],"rb"):
                        pass
                    host_read = True
                except OSError:
                    host_read = False
                try:
                    Path(__file__).with_name("write-probe").write_text("public temporal probe")
                    code_write = True
                except OSError:
                    code_write = False
                result = {"host_read":host_read,"code_write":code_write,
                          "non_loopback_interfaces":sorted(n for _,n in socket.if_nameindex() if n!="lo"),
                          "uid":getattr(os,"getuid",lambda:None)(),
                          "private_env_present":"TOMOLAB_PRIVATE_SENTINEL" in os.environ}
            else:
                if engine is None:
                    raise ValueError("temporal init required")
                if action == "propose":
                    result = engine.propose()
                elif action == "register":
                    result = engine.admit_native(message["inputs"])
                elif action == "observe":
                    result = engine.observe(message["evidence"])
                elif action == "freeze":
                    result = engine.freeze()
                else:
                    result = engine.snapshot()
            response = {"ok":True,"result":result}
        except Exception as error:
            response = {"ok":False,"error":f"{type(error).__name__}: {error}"}
        rendered = json.dumps(response,ensure_ascii=True,allow_nan=False,separators=(",",":"))
        if len(rendered)+1>MAX_MESSAGE:
            rendered = json.dumps({"ok":False,"error":"ValueError: temporal response exceeds bound"})
        if action != "metrics":
            elapsed,used = time.perf_counter()-started,time.process_time()-cpu
            metrics["requests"] += 1
            metrics["wall_seconds"] += elapsed
            metrics["cpu_seconds"] += used
            row = metrics["actions"].setdefault(action,{"calls":0,"wall_seconds":0.0,"cpu_seconds":0.0})
            row["calls"] += 1
            row["wall_seconds"] += elapsed
            row["cpu_seconds"] += used
        print(rendered,flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
