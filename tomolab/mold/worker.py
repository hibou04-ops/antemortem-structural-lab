"""JSON-lines generator endpoint. No target or reference modules are imported."""
from __future__ import annotations

import json
import sys

from . import MoldEngine, transfer
from .protocol import MAX_MESSAGE, validate_request


def main() -> int:
    engine = None
    while True:
        line = sys.stdin.readline(MAX_MESSAGE + 1)
        if not line:
            break
        try:
            if len(line) > MAX_MESSAGE or not line.endswith("\n"):
                print(json.dumps({"ok": False, "error": "ValueError: message too large or truncated"}), flush=True)
                return 2
            message = validate_request(json.loads(line), None if engine is None else engine.spec)
            action = message["action"]
            if action == "close":
                return 0
            if action == "init":
                if engine is not None:
                    raise ValueError("worker already initialized")
                engine = MoldEngine(message["spec"], seed=message.get("seed", 7),
                                    strategy=message.get("strategy", "mold"),
                                    solver=message.get("solver", "enumeration"))
                result = {"initialized": True}
            elif action == "transfer":
                if engine is not None:
                    raise ValueError("transfer requires a fresh worker")
                result = transfer(message["snapshot"], message["spec"],
                                  seed=message.get("seed", 7), budget=message.get("budget", 32),
                                  solver=message.get("solver", "enumeration"))
            elif action == "diagnose":
                # Public dummy sentinel only; never return file contents.
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
                    Path(__file__).with_name("write-probe").write_text("probe")
                    code_write = True
                except OSError:
                    code_write = False
                # Inspect this process's interfaces instead of probing a third-
                # party service. Docker's network=none should expose loopback
                # only; this does not claim an external connectivity experiment.
                interfaces = sorted(name for _, name in socket.if_nameindex() if name != "lo")
                result = {"host_read": host_read, "code_write": code_write,
                          "non_loopback_interfaces": interfaces, "uid": getattr(os, "getuid", lambda: None)(),
                          "private_env_present": "TOMOLAB_PRIVATE_SENTINEL" in os.environ}
            else:
                if engine is None:
                    raise ValueError("init required")
                if action == "propose":
                    result = engine.propose()
                elif action == "observe":
                    engine.observe(message["evidence"])
                    result = {"accepted": True}
                elif action == "freeze":
                    result = engine.freeze()
                else:
                    result = engine.snapshot()
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
