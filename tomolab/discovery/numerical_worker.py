"""Data-only compact guide execution; targets and Oracle modules are absent."""
import json
import sys

from .compact_guidance import MAX_MESSAGE, in_process_candidate_plan, validate_numerical_request
from .schema import canonical, digest


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
        Path(__file__).with_name("write-probe").write_text("public R2 diagnostic")
        code_write = True
    except OSError:
        code_write = False
    forbidden = ("tomolab.discovery.knowledge", "tomolab.discovery.oracle", "tomolab.discovery.service",
                 "tomolab.discovery.numerical_source")
    return {"host_read": host_read, "code_write": code_write,
        "non_loopback_interfaces": sorted(n for _, n in socket.if_nameindex() if n != "lo"),
        "uid": getattr(os, "getuid", lambda: None)(),
        "private_env_present": "TOMOLAB_PRIVATE_SENTINEL" in os.environ,
        "forbidden_modules_loaded": [name for name in forbidden if name in sys.modules]}


def main():
    planned = None
    while True:
        line = sys.stdin.readline(MAX_MESSAGE+1)
        if not line:
            return 0
        try:
            if len(line.encode("utf-8")) > MAX_MESSAGE or not line.endswith("\n"):
                raise ValueError("oversized or truncated numerical request")
            request = validate_numerical_request(json.loads(line))
            action = request.pop("action")
            if action == "close":
                return 0
            if action == "diagnose":
                result = _diagnose(request["host_sentinel"])
            elif action in ("plan", "baseline"):
                if planned is not None:
                    raise ValueError("frozen numerical worker rejects replacement parameters and learning")
                if action == "plan":
                    result = in_process_candidate_plan(**request)
                    planned = {k:v for k,v in result.items() if k != "generation"}
                else:
                    from .numerical_guidance import generate_numerical_candidates
                    result = generate_numerical_candidates(**request)
                    planned = {"candidate_digest": digest(result["candidates"]), "frozen": True,
                               "learning_allowed": False, "final_feedback_allowed": False}
                planned["request_digest"] = digest(request)
            elif action in ("freeze", "snapshot"):
                if planned is None:
                    raise ValueError("an approved frozen numerical plan is required")
                result = planned
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        rendered = canonical(response)
        if len(rendered.encode("utf-8"))+1 > MAX_MESSAGE:
            rendered = canonical({"ok": False, "error": "ValueError: numerical response exceeds bound"})
        print(rendered, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
