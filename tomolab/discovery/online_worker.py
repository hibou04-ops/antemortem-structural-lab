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
        counter = 0
        def execute(point, *, phase, reference):
            nonlocal counter
            request_id = counter
            _write(dict(action="evaluate", request_id=request_id, input=point, phase=phase, reference=reference))
            response = _read()
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
