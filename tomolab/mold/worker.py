"""JSON-lines generator endpoint. No target or reference modules are imported."""
from __future__ import annotations

import json
import sys

from . import MoldEngine, transfer

MAX_MESSAGE = 8_000_000


def main() -> int:
    engine = None
    for line in sys.stdin:
        try:
            if len(line) > MAX_MESSAGE:
                raise ValueError("message too large")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("request must be an object")
            action = message.get("action")
            fields = {
                "init": {"action", "spec", "seed", "strategy", "solver"},
                "propose": {"action"}, "observe": {"action", "evidence"},
                "freeze": {"action"}, "snapshot": {"action"},
                "transfer": {"action", "snapshot", "spec", "seed", "budget", "solver"},
                "diagnose": {"action", "host_sentinel"}, "close": {"action"},
            }
            if action not in fields or set(message) - fields[action]:
                raise ValueError("unknown action or forbidden request field")
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
                with socket.socket() as connection:
                    connection.settimeout(1)
                    network = connection.connect_ex(("1.1.1.1", 53)) == 0
                result = {"host_read": host_read, "code_write": code_write,
                          "network_connected": network, "uid": getattr(os, "getuid", lambda: None)(),
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
