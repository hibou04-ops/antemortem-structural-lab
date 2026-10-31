"""Duplex online RPC on the existing reviewed disposable process boundary.

The search process gets public data only. Target/Oracle execution stays in the
trusted host. This is logical isolation, not protection against hostile code.
"""
import json
import queue
from pathlib import Path

from ..mold.boundary import GeneratorBoundary
from ..mold.protocol import MAX_MESSAGE
from .schema import canonical
from .online_schema import validate_online_config, validate_online_observation, validate_input

GENERATOR_FILES = ("__init__.py", "schema.py", "online_schema.py", "online_mold.py",
                   "online_engine.py", "online_worker.py")


def bounded_message(value):
    # JSON object insertion order can affect a trusted Python mapping target.
    # Canonical sorting belongs to integrity hashes, not execution transport.
    payload = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))+"\n"
    if len(payload.encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("online message exceeds existing 8,000,000 byte boundary")
    return payload


class OnlineBoundary(GeneratorBoundary):
    module_root = Path(__file__).parent
    package_name = "discovery"
    generator_files = GENERATOR_FILES
    worker_entry = "tomolab.discovery.online_worker"
    protocol_name = "tomolab-online-duplex-v1"

    def __init__(self, *, timeout=60):
        super().__init__(backend="subprocess", timeout=timeout)

    def run(self, config, execute):
        """Validate envelope before transport and retain host actual-call state."""
        validate_online_config(config)
        self.process.stdin.write(bounded_message(dict(action="run", config=config)))
        self.process.stdin.flush()
        self._accepted_requests = 1
        request_count = 0
        while True:
            try:
                line = self.messages.get(timeout=self.timeout)
            except queue.Empty as error:
                raise ValueError("online generator timed out") from error
            if line is None or len(line.encode("utf-8")) > MAX_MESSAGE or not line.endswith("\n"):
                raise ValueError("online generator terminated or sent an oversized response")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("invalid online response")
            action = message.get("action")
            if action == "evaluate":
                if set(message) != {"action", "request_id", "input", "phase", "reference"} or message["request_id"] != request_count:
                    raise ValueError("unexpected online evaluation envelope or sequence")
                if type(message["request_id"]) is not int or message["phase"] not in ("base", "structure", "replay", "confirmation", "native_shrink", "delta_shrink", "shrink_confirmation") or not validate_input(message["input"], config["contract"]):
                    raise ValueError("invalid generated domain, phase or actual request counter")
                if message["reference"] is not None and (type(message["reference"]) is not int or not 0 <= message["reference"] < request_count):
                    raise ValueError("a reproduction reference must name a prior observation")
                response = execute(message["input"], phase=message["phase"], reference=message["reference"])
                validate_online_observation(response, request_id=request_count, point=message["input"], contract=config["contract"])
                self.process.stdin.write(bounded_message(dict(action="feedback", request_id=request_count, observation=response)))
                self.process.stdin.flush()
                request_count += 1
                self._accepted_requests += 1
            elif action == "complete":
                if set(message) != {"action", "result", "inventory"}:
                    raise ValueError("invalid online completion")
                self.process.wait(timeout=3)
                if self.process.returncode:
                    raise ValueError("online generator failed after its completion envelope")
                return message["result"], dict(imported_modules=message["inventory"],
                    rpc_evaluations=request_count, worker_exit_code=self.process.returncode)
            elif action == "error":
                raise ValueError("online worker error: "+str(message.get("error_type", "UNKNOWN")))
            else:
                raise ValueError("unsupported online response action")
