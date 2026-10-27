"""Public-data-only E5 endpoint; evaluator and target code are never imported."""
import json
import sys

from .engine import DiscoveryEngine, transfer
from .protocol import MAX_MESSAGE, validate_request


def main():
    engine = None
    transferred = False
    while True:
        line = sys.stdin.readline(MAX_MESSAGE + 1)
        if not line:
            break
        try:
            if len(line) > MAX_MESSAGE or not line.endswith("\n"):
                raise ValueError("oversized or truncated discovery message")
            message = validate_request(json.loads(line), None if engine is None else engine.spec)
            action = message.pop("action")
            if action == "close":
                return 0
            if action == "init":
                if engine is not None or transferred:
                    raise ValueError("worker already initialized")
                engine = DiscoveryEngine(**message)
                result = {"initialized": True}
            elif action == "transfer":
                if engine is not None or transferred:
                    raise ValueError("transfer requires a fresh worker")
                message["target_spec"] = message.pop("spec")
                result = transfer(**message)
                transferred = True
            elif action == "diagnose":
                import os
                import socket
                from pathlib import Path
                try:
                    with open(message["host_sentinel"], "rb"):
                        pass
                    host_read = True
                except OSError:
                    host_read = False
                try:
                    Path(__file__).with_name("write-probe").write_text("public probe")
                    code_write = True
                except OSError:
                    code_write = False
                result = {"host_read":host_read,"code_write":code_write,
                          "non_loopback_interfaces":sorted(n for _,n in socket.if_nameindex() if n != "lo"),
                          "uid":getattr(os,"getuid",lambda:None)(),
                          "private_env_present":"TOMOLAB_PRIVATE_SENTINEL" in os.environ}
            else:
                if engine is None:
                    raise ValueError("init required")
                if action == "propose":
                    result = engine.propose()
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
        if len(rendered)+1 > MAX_MESSAGE:
            rendered = json.dumps({"ok":False,"error":"ValueError: response exceeds bound"})
        print(rendered,flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
