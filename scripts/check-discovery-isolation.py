"""Exercise the real E5 container boundary using public dummy sentinels only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tomolab.cli import EXAMPLES
from tomolab.discovery.boundary import DiscoveryBoundary
from tomolab.discovery.service import prepare_public_contract, run_discovery
from tomolab.mold.service import _load


def main():
    with tempfile.TemporaryDirectory(prefix="e5-private-sentinel-") as folder:
        sentinel = Path(folder)/"private-answer.txt"
        sentinel.write_text("public dummy canary, never a real answer",encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "not-forwarded"
        with DiscoveryBoundary(backend="docker") as generator:
            diagnostic = generator.request("diagnose",host_sentinel=str(sentinel))
            assert diagnostic == {"host_read":False,"code_write":False,"non_loopback_interfaces":[],
                                  "uid":65534,"private_env_present":False},diagnostic
            network = subprocess.run(["docker","inspect",generator.name,"--format","{{.HostConfig.NetworkMode}}"],
                                     capture_output=True,text=True,check=True,timeout=30).stdout.strip()
            assert network == "none"
            assert not (generator.root/"tomolab/discovery/service.py").exists()
            receipt = generator.receipt
        public = EXAMPLES/"discovery"
        spec = json.loads((public/"sequence-spec.json").read_text(encoding="utf-8"))
        spec, ir = prepare_public_contract(spec,public/"sequence_target.py")
        target,_ = _load(public/"sequence_target.py","implementation")
        oracle,_ = _load(public/"sequence_oracle.py","reference")
        result = run_discovery(target,oracle,spec,public_ir=ir,budget=12,pool_size=32,shrink_budget=16,
                               solver="z3",backend="docker",time_budget=30,trusted_execution=True)
        assert result["status"] == "COUNTEREXAMPLE_FOUND"
        assert result["isolation"] == "CONTAINER_BOUNDARY"
        assert result["snapshot"]["frozen"] is True
        assert result["snapshot"]["query_metrics"]["solver_calls"] > 0
        assert result["final_feedback_allowed"] is False
        print(json.dumps({"status":"PASS","access_control":diagnostic,"boundary":receipt,
                          "docker_network_mode":network,"external_connectivity":"NOT_TESTED_NO_THIRD_PARTY_PROBE",
                          "end_to_end_calls":result["metrics"]["oracle_calls"],
                          "query_metrics":result["snapshot"]["query_metrics"]},indent=2))


if __name__ == "__main__":
    main()
