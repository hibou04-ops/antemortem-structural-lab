"""Validate saved v8 CI evidence; no provider, upstream source or target calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET

from tomolab.discovery.schema import digest
from tomolab.discovery.workflow_audit import audit_workflow


def load(path):
    return json.loads(Path(path).read_bytes())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["functional","control"],required=True)
    args=parser.parse_args()
    branch=os.environ.get("GITHUB_HEAD_REF") or os.environ["GITHUB_REF_NAME"]
    audit=audit_workflow(".github/workflows/tests.yml",branch=branch)
    Path("workflow-conditions-audit.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf8")
    runtime={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("tomolab").rglob("*.py"))}
    result=dict(schema="tomolab-post-v8-ci-readback-v1",mode=args.mode,
        head=subprocess.check_output(["git","rev-parse","HEAD"]).decode().strip(),pr_head=os.environ["POST_V6_PR_HEAD"],
        platform=platform.system(),python=platform.python_version(),runtime=runtime,runtime_digest=digest(runtime),
        workflow_audit=audit,additional_github_api_gets=0,paid_api_calls=0,release_actions=0)
    if args.mode=="functional":
        xml=ET.parse("harvester-regressions.xml").getroot()
        result["pytest"]=dict(total=len(xml.findall(".//testcase")),failures=len(xml.findall(".//failure")),errors=len(xml.findall(".//error")),skipped=len(xml.findall(".//skipped")))
        assert result["pytest"]["total"]>=575 and result["pytest"]["failures"]==result["pytest"]["errors"]==result["pytest"]["skipped"]==0
        summary=load("work/structural-example/summary.json")
        assert summary["status"]=="FUNCTIONAL_COMPLETE" and summary["reset_symmetry_verified"] is True
        assert summary["actual"]["reset_calls"]==summary["actual"]["target_calls"]+summary["actual"]["oracle_calls"]
        result["probe"]={k:v for k,v in summary.items() if k not in ("cases","wall_seconds")}
        result["artifact_checks"]=[]
        for path in ["historical-preservation.json","product-runtime.json","harvester-installed.json","qualification-installed.json"]:
            value=load(path)
            assert value["status"]=="PASS"
            result["artifact_checks"].append(dict(path=path,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),status=value["status"]))
    else:
        control=load("work/oci-control/oci-probe.json")
        assert control["status"]=="PASS"
        assert not Path("work/sequence-qualification").exists() and not Path("work/public-qualification").exists()
        result.update(oci_control=control,external_target_calls=0,external_oracle_calls=0,external_reset_calls=0,
            qualification_execution="NOT_REQUESTED_NO_KNOWN_WITNESS_REPLAY")
    result.update(status="PASS",m0="HOLD",utility="NOT_ESTABLISHED",oos="NOT_ESTABLISHED")
    result["sha256"]=digest(result)
    path=Path("post-v8-"+args.mode+"-readback.json")
    path.write_text(json.dumps(result,ensure_ascii=True,indent=2)+"\n",encoding="utf8")
    compact={k:v for k,v in result.items() if k not in ("runtime","oci_control","workflow_audit")}
    compact["raw_readback_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
    compact["expected_run_jobs"]=audit["expected_run_jobs"]
    compact["expected_skip_jobs"]=audit["expected_skipped_jobs"]
    with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf8") as output:
        output.write("## Post-v8 verified readback\n\n```json\n"+json.dumps(compact,indent=2)+"\n```\n")
    print(json.dumps(compact))


if __name__=="__main__":
    main()
