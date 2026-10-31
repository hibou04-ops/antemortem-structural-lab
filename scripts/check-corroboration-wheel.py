"""Execute reviewed CORR adapters from a genuinely installed candidate wheel.

This public seed-7 functional regression is separate from the once-only
research cohort. Raw inputs, target results, exceptions and warning messages
stay in the temporary evaluator workspace and are absent from this report.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import venv


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,allow_nan=False,
        sort_keys=True,separators=(",",":")).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel",type=Path,nargs="?")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reuse-approved-dependencies",action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3,12):
        raise RuntimeError("the reviewed SciPy/NumPy distribution profile requires Python >=3.12")
    project = Path(__file__).resolve().parents[1]
    if args.wheel:
        wheel = args.wheel.resolve(strict=True)
    else:
        version = tomllib.loads((project/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        matches = list((project/"dist").glob(f"antemortem_structural_lab-{version}-*.whl"))
        if len(matches) != 1:
            raise ValueError("exactly one current candidate wheel is required")
        wheel = matches[0].resolve(strict=True)
    if args.output.exists():
        raise FileExistsError("installed-wheel verification receipts must be new")
    env = dict(os.environ,PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH",None)
    records, reused, summaries = [], [], []
    implementation_ids = ("python-statistics-correlation","scipy-stats-pearsonr")
    with tempfile.TemporaryDirectory(prefix="e8r4-installed-wheel-") as temporary:
        external = Path(temporary).resolve()
        assert not external.is_relative_to(project)
        venv.EnvBuilder(with_pip=True).create(external/"env")
        python = external/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")

        def run(label,*arguments,success=True):
            tick = time.perf_counter()
            completed = subprocess.run([str(python),"-I","-X","utf8",*map(str,arguments)],
                cwd=external,env=env,text=True,encoding="utf-8",capture_output=True,timeout=240)
            records.append(dict(check=label,returncode=completed.returncode,expected_success=success,
                entire_process_wall_seconds=time.perf_counter()-tick))
            if (completed.returncode == 0) != success:
                raise RuntimeError(label+": "+(completed.stderr or completed.stdout)[-6000:])
            return completed

        def command(label,*arguments):
            output = external/(label+".json")
            run(label,"-m","tomolab",*arguments,"--output",output)
            value = json.loads(output.read_text(encoding="utf-8"))
            io = json.loads(Path(str(output)+".io.json").read_text(encoding="utf-8"))
            assert io["receipt_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
            assert io["receipt_bytes"] == output.stat().st_size
            return value,io,output

        run("base-wheel-offline-install","-m","pip","install","--no-index","--no-deps",wheel)
        run("base-pip-check","-m","pip","check")
        origin = json.loads(run("installed-r4-origin","-c",
            "import inspect,json;from importlib.metadata import version;"
            "from tomolab import e8r4_cli;from tomolab.discovery import corroboration_adapters,corroboration_service,corroboration_permit;"
            "print(json.dumps({'version':version('antemortem-structural-lab'),'files':"
            "[inspect.getfile(m) for m in (e8r4_cli,corroboration_adapters,corroboration_service,corroboration_permit)]}))").stdout)
        assert origin["version"] == wheel.name.split("-")[1]
        assert all(Path(value).resolve().is_relative_to(external/"env") for value in origin["files"])
        for name in ("corroboration-inspect","corroboration-plan","corroboration-approve","corroboration-run","corroboration-demo"):
            run("help-"+name,"-m","tomolab",name,"--help")
        if args.reuse_approved_dependencies:
            target = Path(run("fresh-library-path","-c","import sysconfig;print(sysconfig.get_paths()['purelib'])").stdout.strip()).resolve()
            assert target.is_relative_to(external/"env")
            for name in ("hypothesis","sortedcontainers","psutil","z3-solver","scipy","numpy"):
                installed = distribution(name)
                library = Path(installed.locate_file("")).resolve()
                inventory = {}
                for item in installed.files or []:
                    source = Path(installed.locate_file(item)).resolve()
                    if not source.is_relative_to(library) or not source.is_file():
                        continue
                    relative = source.relative_to(library)
                    destination = (target/relative).resolve()
                    if not destination.is_relative_to(target):
                        raise ValueError("approved dependency copy escaped the new library")
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,destination)
                    raw = destination.read_bytes()
                    assert raw == source.read_bytes()
                    inventory[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
                assert inventory
                reused.append(dict(distribution=name,version=installed.version,files=len(inventory),inventory_sha256=digest(inventory)))
        else:
            run("fresh-normal-qa-solver-corr-install","-m","pip","install",f"{wheel}[qa,solver,corr]")
        run("corr-pip-check","-m","pip","check")
        location = run("installed-example-location","-c","from tomolab.cli import EXAMPLES;print(EXAMPLES)").stdout.strip()
        examples = Path(location).resolve()
        assert examples.is_relative_to(external/"env")
        guide_folder = examples/"numerical"
        guide_names = ("source-guide.json","source-approval.json","source-guide.sha256")
        before = {name:hashlib.sha256((guide_folder/name).read_bytes()).hexdigest() for name in guide_names}
        pin = (guide_folder/"source-guide.sha256").read_text(encoding="ascii").strip()
        artifact = json.loads((guide_folder/"source-guide.json").read_text(encoding="utf-8"))
        approval = json.loads((guide_folder/"source-approval.json").read_text(encoding="utf-8"))
        assert artifact["artifact_digest"] == pin and artifact["applicability_scope"] == "SOURCE_DEVELOPMENT_ONLY"
        assert approval["transfer_authorized"] is False
        inspections = {}
        for identifier in implementation_ids:
            inspected,_,_ = command("inspect-"+identifier,"corroboration-inspect","--implementation",identifier)
            assert inspected["execution"] == "NOT_EXECUTED" and inspected["target_calls"] == inspected["oracle_calls"] == 0
            assert inspected["allow_release"] is False
            assert inspected["implementation"]["implementation_id"] == identifier
            # Physical import paths are local-only and intentionally omitted.
            inspections[identifier] = inspected["implementation"]
        common = ("--seed","7","--size","3","--max-examples","128")
        plan,_,plan_path = command("plan-B","corroboration-plan","--method","B",*common)
        assert plan["primary_generation_executions"] == 1 and plan["reference_generation_executions"] == 0
        assert plan["response_validation_status"] == "PASS"
        assert "artifact" not in plan["request"] and "approval_receipt" not in plan["request"] and "replay_inputs" not in plan["request"]
        assert plan["metrics"]["target_calls"] == plan["metrics"]["oracle_calls"] == 0
        authority = digest({"scope":"PUBLIC_INSTALLED_CORR_FUNCTIONAL","version":origin["version"]})
        host_state, ledger = external/"approved-host-state.json",external/"corr-usage.jsonl"
        approved,_,permit_path = command("approve-B","corroboration-approve","--plan",plan_path,
            "--implementation",implementation_ids[0],"--usage-ledger",ledger,"--authority-id",authority,
            "--approval-state",host_state,"--guide-digest",pin,
            "--review-digest",digest({"review":"PUBLIC_FUNCTIONAL_CONTRACT_NOT_QUALIFIED_RESEARCH"}),
            "--budget","12","--shrink-budget","0")
        context = approved["context"]
        assert context["scope"] == "INDEPENDENT_DEVELOPMENT_ONLY"
        assert context["feedback_to_generator"] is context["final_evaluation_authorized"] is context["publication_authorized"] is False
        run_args = ("corroboration-run","--plan",plan_path,"--permit",permit_path,
            "--approval-state",host_state,"--usage-ledger",ledger,"--authority-id",authority)
        denied = run("missing-execution-permission-denied","-m","tomolab",*run_args,"--output",external/"denied.json",success=False)
        assert "--allow-local-execution" in denied.stderr

        def summarize(label,value,io):
            assert value["schema"] == "tomolab-corroboration-cli-execution-v1" and value["status"] == "COMPLETE"
            execution = value["run"]
            assert value["allow_release"] is False and value["final_target_eligible"] is False
            assert execution["scope"] == "INDEPENDENT_DEVELOPMENT_ONLY"
            assert execution["primary_generation_executions"] == 1 and execution["reference_generation_executions"] == 0
            assert execution["generator_feedback_calls"] == 0 and execution["source_archive_modified"] is False
            assert execution["allow_release"] is execution["publication_authorized"] is execution["final_evaluation_authorized"] is False
            assert 0 < execution["target_calls"] == execution["actual_target_function_entries"] <= 12
            assert execution["target_calls"] == execution["oracle_calls"]
            assert execution["outcome"] in ("NO_CONFIRMED_FAILURE_WITHIN_BUDGET","CONFIRMED_CONTRACT_VIOLATION_WITHIN_BUDGET")
            if execution["outcome"] == "NO_CONFIRMED_FAILURE_WITHIN_BUDGET":
                assert execution["first_confirmed_failure"] is None
            result = dict(label=label,implementation_id=execution["implementation_id"],method=execution["method"],
                status=execution["status"],outcome=execution["outcome"],target_calls=execution["target_calls"],
                oracle_calls=execution["oracle_calls"],actual_target_function_entries=execution["actual_target_function_entries"],
                verification_profile="runtime",primary_generation_executions=execution["primary_generation_executions"],reference_generation_executions=0,
                normalized_state_counts=dict(Counter(row["normalized"]["computability"] for row in execution["rows"])),
                receipt_sha256=execution["receipt_sha256"],io=io,
                confirmed_contract_violation_inputs=execution["confirmed_contract_violation_inputs"],
                target_raw_values_disclosed=False)
            summaries.append(result)

        executed,io,_ = command("run-B",*run_args,"--allow-local-execution")
        summarize("standalone-inspect-plan-approve-run-B",executed,io)
        run("consumed-identity-reuse-denied","-m","tomolab",*run_args,"--allow-local-execution",
            "--output",external/"reused-denied.json",success=False)
        forged = deepcopy(approved)
        forged["context"]["final_evaluation_authorized"] = True
        forged["permit_digest"] = digest(forged["context"])
        forged_permit, forged_state = external/"forged-final.json",external/"forged-final-state.json"
        forged_permit.write_text(json.dumps(forged),encoding="utf-8")
        forged_state.write_text(json.dumps(forged["context"]),encoding="utf-8")
        run("corr-cannot-relabel-final-denied","-m","tomolab","corroboration-run","--plan",plan_path,
            "--permit",forged_permit,"--approval-state",forged_state,"--usage-ledger",ledger,
            "--authority-id",authority,"--allow-local-execution","--output",external/"final-denied.json",success=False)
        for identifier in implementation_ids:
            demo,io,_ = command("demo-D-"+identifier,"corroboration-demo","--workspace",external/("demo-"+identifier),
                "--implementation",identifier,"--method","D",*common,"--budget","12","--shrink-budget","0","--allow-local-execution")
            summarize("public-demo-D-"+identifier,demo,io)
            demo_plan = json.loads((external/("demo-"+identifier)/"plan.json").read_text(encoding="utf-8"))
            assert demo_plan["request"]["artifact"]["applicability_scope"] == "SOURCE_DEVELOPMENT_ONLY"
            assert demo_plan["request"]["approval_receipt"]["transfer_authorized"] is False
            assert demo_plan["request"]["expected_digest"] == pin
        after = {name:hashlib.sha256((guide_folder/name).read_bytes()).hexdigest() for name in guide_names}
        assert before == after
        report = dict(schema="tomolab-e8r4-installed-wheel-verification-v1",status="PASS",
            scope="PUBLIC_FUNCTIONAL_CORR_NOT_REGISTERED_RESEARCH_COHORT",wheel=wheel.name,
            wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),version=origin["version"],
            isolated_fresh_venv=True,outside_source_checkout=True,installed_module_origins_confirmed=True,
            implementations=inspections,runs=summaries,
            qa_dependency_installation="APPROVED_EXISTING_DISTRIBUTIONS_COPIED_AND_BYTE_VERIFIED_NOT_FRESH_INDEX_INSTALL"
                if args.reuse_approved_dependencies else "FRESH_NORMAL_INDEX_INSTALL",
            dependency_reuse=reused,source_guide_digest=pin,source_guide_files_sha256=before,
            source_guide_bytes_preserved=True,source_scope_preserved=True,
            source_archive_processing_calls=0,source_target_calls=0,
            actual_corr_target_calls=sum(row["target_calls"] for row in summaries),
            actual_oracle_calls=sum(row["oracle_calls"] for row in summaries),
            raw_inputs_or_target_outputs_in_public_report=False,
            research_cohort_reexecuted=False,independent_generalization_claimed=False,
            checks=records,pypi_uploads=0,allow_release=False,final_evaluation_authorized=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(report,stream,ensure_ascii=False,allow_nan=False,indent=2)
        stream.write("\n")
    print(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2))


if __name__ == "__main__":
    main()
