"""Data-only search worker. No target, reference, benchmark or evaluator import."""
import json
import sys

from .schema import canonical
from .online_schema import validate_online_config, validate_online_observation

MAX_MESSAGE = 8_000_000


def _read():
    line = sys.stdin.readline(MAX_MESSAGE+1)
    if not line or not line.endswith("\n") or len(line.encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("missing, truncated or oversized online message")
    return json.loads(line)


def _write(message):
    payload = json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":"))+"\n"
    if len(payload.encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("online response exceeds existing transport bound")
    sys.stdout.write(payload); sys.stdout.flush()


def main():
    try:
        request = _read()
        if type(request) is not dict or set(request) != {"action", "config"} or request["action"] != "run":
            raise ValueError("one immutable online run configuration required")
        config = validate_online_config(request["config"])
        from .online_engine import _run_online_core
        from .recursive_policy import PolicyReallocationRequired
        counter = 0
        def execute(point, *, phase, reference, policy_id=None):
            nonlocal counter
            request_id = counter
            message = dict(action="evaluate", request_id=request_id, input=point, phase=phase, reference=reference)
            if config["method"] == "D":
                if policy_id not in ("C", "D"):
                    raise ValueError("mixed evaluation requires an explicit policy identity")
                message["policy_id"] = policy_id
            _write(message)
            response = _read()
            if response.get("action") == "reallocate":
                if config["method"] != "D" or policy_id != "D" or set(response) != {"action", "request_id", "reason", "circuit_breaker_triggered"} or response["request_id"] != request_id or type(response["reason"]) is not str or type(response["circuit_breaker_triggered"]) is not bool:
                    raise ValueError("invalid no-execution policy reallocation")
                raise PolicyReallocationRequired(response["reason"], response["circuit_breaker_triggered"])
            if type(response) is not dict or set(response) != {"action", "request_id", "observation"} or response["action"] != "feedback" or response["request_id"] != request_id:
                raise ValueError("online feedback envelope or sequence mismatch")
            observation = validate_online_observation(response["observation"], request_id=request_id,
                                                      point=point, contract=config["contract"])
            counter += 1
            return observation
        result = _run_online_core(execute=execute, **config)
        _write(dict(action="complete", result=result, inventory=sorted(sys.modules)))
        return 0
    except Exception as error:
        _write(dict(action="error", error_type=type(error).__name__))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
