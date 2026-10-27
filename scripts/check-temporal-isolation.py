"""Verify E6's actual restricted container and integrated reviewed state machine."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tomolab.discovery.temporal_boundary import TemporalBoundary


def main():
    with tempfile.TemporaryDirectory(prefix="e6-host-sentinel-") as directory:
        marker = Path(directory)/"public-dummy"
        marker.write_text("non-sensitive E6 diagnostic",encoding="utf-8")
        os.environ["TOMOLAB_PRIVATE_SENTINEL"] = "public-dummy-not-a-secret"
        with TemporalBoundary(backend="docker") as generator:
            control = generator.request("diagnose",host_sentinel=str(marker))
            boundary = generator.receipt
            inspect = subprocess.check_output(["docker","inspect",generator.name,"--format","{{.HostConfig.NetworkMode}}"],text=True).strip()
        assert control=={"host_read":False,"code_write":False,"non_loopback_interfaces":[],
                         "uid":65534,"private_env_present":False},control
        assert inspect=="none"
        os.environ.pop("TOMOLAB_PRIVATE_SENTINEL")
    # Run the actual packaged-style CLI; only reviewed local target/model callbacks execute.
    import sys
    command = [sys.executable,"-m","tomolab","stateful-demo","--backend","docker","--budget","128",
               "--pool-size","12","--shrink-budget","64","--time-budget","30"]
    result = subprocess.run(command,capture_output=True,text=True,encoding="utf-8",check=True,timeout=120)
    discovery = json.loads(result.stdout)
    assert discovery["status"]=="COUNTEREXAMPLE_FOUND"
    assert discovery["snapshot"]["frozen"]
    assert discovery["snapshot"]["status"]=="HYPOTHESES_REMAIN"
    assert discovery["snapshot"]["temporal_metrics"]["activation_count"]==1
    assert discovery["metrics"]["guided_trace_calls"]>0
    assert discovery["counterexample"]["replay"]=="MATCHED_TWICE"
    print(json.dumps({"status":"PASS","access_control":control,"boundary":boundary,"docker_network_mode":inspect,
                      "external_connectivity":"NOT_TESTED_NO_THIRD_PARTY_PROBE",
                      "target_execution":"TRUSTED_HOST_CODE",
                      "end_to_end_transition_calls":discovery["metrics"]["model_transition_calls"],
                      "temporal_metrics":discovery["snapshot"]["temporal_metrics"],
                      "final_feedback_allowed":discovery["final_feedback_allowed"]},indent=2))


if __name__=="__main__":
    main()
