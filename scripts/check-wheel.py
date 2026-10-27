"""Install a wheel in a fresh environment and exercise its bundled CLI fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import venv

qa = "--qa" in sys.argv
arguments = [arg for arg in sys.argv[1:] if arg != "--qa"]
if arguments:
    wheel = Path(arguments[0]).resolve(strict=True)
else:
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    matches = list(Path("dist").glob(f"antemortem_structural_lab-{version}-*.whl"))
    if len(matches) != 1:
        raise SystemExit("Expected exactly one wheel for the current project version")
    wheel = matches[0].resolve(strict=True)
env = dict(os.environ, PYTHONIOENCODING="utf-8")
env.pop("PYTHONPATH", None)
with tempfile.TemporaryDirectory(prefix="structural-wheel-") as folder:
    root = Path(folder)
    venv.EnvBuilder(with_pip=True).create(root / "env")
    python = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def run(*args):
        result = subprocess.run([str(python), *args], cwd=root, env=env,
                                text=True, encoding="utf-8", capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout

    run("-m", "pip", "install", "--no-index", "--no-deps", str(wheel))
    if qa:
        run("-m", "pip", "install", f"{wheel}[qa,solver]")
    run("-m", "pip", "check")
    version = run("-c", "from importlib.metadata import version; print(version('antemortem-structural-lab'))").strip()
    assert version == wheel.name.split("-")[1]
    run("-m", "tomolab", "--help")
    demo = json.loads(run("-m", "tomolab", "demo", "--mode", "cross", "--budget", "12"))
    assert demo["status"] == "ORACLE_CONTRADICTION_FOUND"
    claim = "Swapping the two integer inputs does not change the result"
    compiled = json.loads(run("-m", "tomolab", "claim-compile", "--claim", claim))
    assert compiled["claim"]["kind"] == "swap"
    examples = run("-c", "from tomolab.cli import EXAMPLES; print(EXAMPLES)").strip()
    temporal_contract = str(Path(examples)/"temporal"/"stack-contract.json")
    inspected = json.loads(run("-m","tomolab","stateful-inspect","--contract",temporal_contract))
    assert inspected["execution"] == "NOT_EXECUTED"
    knowledge_folder = Path(examples)/"knowledge"
    inspected = json.loads(run("-m","tomolab","knowledge-inspect","--spec",str(knowledge_folder/"target-spec.json")))
    assert inspected["execution"] == "NOT_EXECUTED"
    evidence = root / "claim.json"
    target = str(Path(examples) / "claim_only" / "symmetry_bug.py")
    run("-m", "tomolab", "claim-run", target, "--claim", claim,
        "--allow-local-execution", "--output", str(evidence))
    found = json.loads(evidence.read_text(encoding="utf-8"))
    assert found["status"] == "CLAIM_REFUTED"
    replay = json.loads(run("-m", "tomolab", "claim-replay", str(evidence), "--allow-local-execution"))
    assert replay["status"] == "REPRODUCED"
    bench = root / "bench.json"
    run("-m", "tomolab", "claim-bench", "--seeds", "2", "--budget", "12", "--output", str(bench))
    assert len(json.loads(bench.read_text(encoding="utf-8"))["records"]) == 56
    run("-c", "from tomolab.mold import MoldEngine, transfer")
    mold = root / "mold.json"
    run("-m", "tomolab", "mold-demo", "--budget", "32", "--output", str(mold))
    learned = json.loads(mold.read_text(encoding="utf-8"))
    assert learned["target_calls"] == 32
    assert learned["isolation"] == "LOGICAL_ISOLATION_ONLY"
    planned = json.loads(run("-m", "tomolab", "mold-plan", "--snapshot", str(mold),
                              "--spec", str(Path(examples) / "mold" / "renamed-spec.json"), "--budget", "12"))
    assert len(planned["candidates"]) == 12
    assert planned["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert planned["final_feedback_allowed"] is False
    checked = json.loads(run("-m", "tomolab", "constraints-check", "--spec",
                             str(Path(examples) / "mold" / "spec.json"),
                             "--expression", "x + y == 0", "--expression", "x > 0"))
    assert checked["status"] == "SAT"
    if qa:
        pbt = json.loads(run("-m", "tomolab", "pbt-demo", "--budget", "32"))
        assert pbt["schema"] == "tomolab-property-run-v1"
        assert pbt["snapshot"]["frozen"] is True
        checked = json.loads(run("-m", "tomolab", "constraints-check", "--spec",
                                 str(Path(examples) / "mold" / "spec.json"),
                                 "--expression", "x + y == 0", "--solver", "z3"))
        assert checked["status"] == "SAT"
        unified = json.loads(run("-m", "tomolab", "discovery-demo", "--budget", "12", "--pool-size", "32",
                                 "--shrink-budget", "16", "--solver", "z3"))
        assert unified["status"] == "COUNTEREXAMPLE_FOUND"
        assert unified["snapshot"]["frozen"] is True
        assert unified["snapshot"]["query_metrics"]["solver_calls"] > 0
        state = json.loads(run("-m", "tomolab", "discovery-demo", "--case", "state", "--budget", "16",
                               "--pool-size", "32", "--shrink-budget", "32"))
        assert state["status"] == "COUNTEREXAMPLE_FOUND"
        temporal = json.loads(run("-m","tomolab","stateful-demo","--budget","128","--pool-size","12",
                                  "--shrink-budget","64"))
        assert temporal["status"] == "COUNTEREXAMPLE_FOUND"
        assert temporal["snapshot"]["status"] == "HYPOTHESES_REMAIN"
        assert temporal["snapshot"]["frozen"] and temporal["final_feedback_allowed"] is False
        assert temporal["metrics"]["guided_trace_calls"] > 0
        assert temporal["counterexample"]["replay"] == "MATCHED_TWICE"
        temporal_source = root/"temporal-source.json"
        temporal_source.write_text(json.dumps(temporal),encoding="utf-8")
        temporal_plan = json.loads(run("-m","tomolab","stateful-plan","--snapshot",str(temporal_source),
                                      "--contract",str(Path(examples)/"temporal"/"renamed-contract.json"),
                                      "--budget","8","--pool-size","12"))
        assert temporal_plan["gate"]["status"] == "APPLICABLE_FOR_PROBING"
        assert temporal_plan["final_feedback_allowed"] is False
        knowledge = json.loads(run("-m","tomolab","knowledge-demo","--budget","16","--guidance-budget","4",
                                   "--pool-size","16","--shrink-budget","16"))
        assert knowledge["status"] == "COUNTEREXAMPLE_FOUND" and knowledge["snapshot"]["frozen"]
        assert knowledge["gate"]["status"] == "QUALIFIED_FOR_PROBING"
        assert knowledge["metrics"]["guided_prefix_calls"] > 0
        assert knowledge["counterexample"]["replay"] == "MATCHED_TWICE"
        knowledge_file = root/"knowledge.json"
        knowledge_file.write_text(json.dumps(knowledge),encoding="utf-8")
        planned = json.loads(run("-m","tomolab","knowledge-plan","--archive",str(knowledge_file),
            "--spec",str(knowledge_folder/"target-spec.json"),"--target-provenance",str(knowledge_folder/"target-provenance.json"),
            "--public-ir",str(knowledge_folder/"target-ir.json"),"--budget","8","--guidance-budget","4","--pool-size","16"))
        assert planned["gate"]["status"] == "QUALIFIED_FOR_PROBING"
        assert planned["oracle_calls"] == planned["target_calls"] == 0 and planned["final_feedback_allowed"] is False
    print(f"Wheel {version}: install, dependency check, bundled demo, claim and replay passed")
