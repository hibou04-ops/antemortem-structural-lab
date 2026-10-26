"""Explicit generator process/container boundary. Targets stay in the evaluator."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

# Only these reviewed modules enter the generator workspace. No evaluator, target,
# reference, credentials, repository checkout, evidence folder or Docker socket.
GENERATOR_FILES = ("__init__.py", "engine.py", "relations.py", "schema.py", "worker.py")


class GeneratorBoundary:
    def __init__(self, backend="subprocess", image="python:3.12-slim", timeout=60):
        if backend not in ("subprocess", "docker"):
            raise ValueError("backend must be subprocess or docker")
        self.backend, self.timeout = backend, timeout
        self.folder = tempfile.TemporaryDirectory(prefix="tomolab-generator-")
        self.root = Path(self.folder.name)
        self.name = "tomolab-generator-" + uuid.uuid4().hex
        self.process = None
        package = self.root / "tomolab" / "mold"
        package.mkdir(parents=True)
        (package.parent / "__init__.py").write_text("", encoding="utf-8")
        self.code_hashes = {}
        for name in GENERATOR_FILES:
            source = Path(__file__).with_name(name)
            if not source.is_file():
                self.folder.cleanup()
                raise ValueError(f"generator module missing: {name}")
            data = source.read_bytes()
            (package / name).write_bytes(data)
            self.code_hashes[name] = hashlib.sha256(data).hexdigest()
        # -I ignores ambient Python paths; only the reviewed public package is added.
        bootstrap = "import sys;sys.path.insert(0,sys.argv[1]);from tomolab.mold.worker import main;raise SystemExit(main())"
        self.image_id = None
        if backend == "docker":
            executable = shutil.which("docker")
            if executable is None:
                self.folder.cleanup()
                raise ValueError("Docker unavailable; no automatic weaker fallback")
            inspect = subprocess.run([executable, "image", "inspect", image, "--format", "{{.Id}}"],
                                     capture_output=True, text=True, timeout=30)
            if inspect.returncode or not inspect.stdout.strip().startswith("sha256:"):
                self.folder.cleanup()
                raise ValueError("Docker image unavailable: explicitly pull a trusted image first")
            self.image_id = inspect.stdout.strip()
            command = [executable, "run", "--rm", "-i", "--pull=never", "--name", self.name,
                       "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--user=65534:65534", "--pids-limit=32", "--memory=256m", "--cpus=1",
                       "--tmpfs=/tmp:rw,noexec,nosuid,size=16m", "--workdir=/tmp",
                       "--mount", f"type=bind,src={self.root},dst=/opt/public,readonly",
                       "--entrypoint=python", self.image_id, "-I", "-B", "-u", "-c", bootstrap, "/opt/public"]
            # TemporaryDirectory is mode 0700 on Unix; allow the container's nobody
            # user to traverse ONLY this disposable tree of public code.
            for item in [self.root, self.root / "tomolab", package]:
                item.chmod(0o755)
            for item in self.root.rglob("*.py"):
                item.chmod(0o644)
        else:
            command = [sys.executable, "-I", "-B", "-u", "-c", bootstrap, str(self.root)]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "DOCKER_HOST", "DOCKER_CONTEXT")}
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
                                        cwd=self.root, bufsize=1)
        self.messages = queue.Queue()
        self.errors = []
        def read_output():
            for line in self.process.stdout:
                self.messages.put(line)
            self.messages.put(None)
        def read_errors():
            for line in self.process.stderr:
                if sum(map(len, self.errors)) < 16000:
                    self.errors.append(line)
        threading.Thread(target=read_output, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()

    @property
    def receipt(self):
        return {"isolation": "CONTAINER_BOUNDARY" if self.backend == "docker" else "LOGICAL_ISOLATION_ONLY",
                "backend": self.backend, "generator_sha256": self.code_hashes,
                "container_image_id": self.image_id,
                "target_execution": "TRUSTED_EVALUATOR_HOST_NOT_SANDBOXED"}

    def request(self, action, **fields):
        payload = json.dumps({"action": action, **fields}, ensure_ascii=True)
        if len(payload) > 8_000_000:
            raise ValueError("generator message exceeds size limit")
        sent = queue.Queue()
        def write_request():
            try:
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
                sent.put(None)
            except (OSError, ValueError) as exc:
                sent.put(exc)
        threading.Thread(target=write_request, daemon=True).start()
        try:
            error = sent.get(timeout=self.timeout)
            if error is not None:
                raise error
            line = self.messages.get(timeout=self.timeout)
        except (OSError, ValueError, queue.Empty) as exc:
            self.close()
            raise ValueError("generator failed or timed out: " + "".join(self.errors)[-2000:]) from exc
        if line is None:
            raise ValueError("generator terminated: " + "".join(self.errors)[-2000:])
        response = json.loads(line)
        if not response.get("ok"):
            raise ValueError(response.get("error", "generator rejected request"))
        return response["result"]

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                # No blocking pipe write during shutdown: a stuck child may no
                # longer be reading stdin. State has already been returned.
                self.process.terminate()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        if self.backend == "docker":
            try:
                subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for stream in (getattr(self.process, "stdin", None), getattr(self.process, "stdout", None), getattr(self.process, "stderr", None)):
            if stream:
                stream.close()
        self.folder.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
