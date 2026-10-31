# E8 공개 기능 예제

이 폴더는 `AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH`다. 직접 작성한 정수 항등 함수와 0에서만 잘못된 예제로 수집 경로를 확인한다. 실제 프로젝트의 결함, 독립 Corroboration, 전이 성과를 입증하지 않는다.

저장소 루트 또는 설치한 예제 경로에서 실행한다. `--allow-local-execution`은 검토한 Python 코드를 현재 host에서 실행하는 동의이며 OS 격리가 아니다. Oracle 검토 영수증의 해시는 코드·명세·비교 정책의 식별을 결속한다. 검토 내용의 진실을 암호학적으로 증명하지 않는다.

```powershell
$EvidenceRoot = Join-Path $env:TEMP 'tomolab-e8-authored-example'
New-Item -ItemType Directory -Force $EvidenceRoot | Out-Null
python -m tomolab evidence-collect examples/evidence/target.py `
  --oracle-file examples/evidence/oracle.py `
  --spec examples/evidence/spec.json `
  --provenance examples/evidence/provenance.json `
  --oracle-validation examples/evidence/oracle-validation.json `
  --function-identity authored-identity --generation-id E8-AUTHORED-DEMO `
  --allow-local-execution --budget 8 --max-calls 16 `
  --output "$EvidenceRoot/collection.json"
python -m tomolab evidence-inspect --bundle "$EvidenceRoot/collection.json"
$Origin = Get-Content examples/evidence/provenance.json | ConvertFrom-Json
$Review = Get-Content examples/evidence/oracle-validation.json | ConvertFrom-Json
python -m tomolab evidence-learn --bundle "$EvidenceRoot/collection.json" `
  --implementation-hash $Origin.implementation_sha256 `
  --spec-hash $Review.public_spec_hash --output "$EvidenceRoot/source.json"
python -m tomolab readiness-demo
```

`max-calls`는 재현을 포함한 Target와 Oracle 호출의 합이다. 실행 결과와 증거 bundle은 host 전용으로 보관하고 공개 배포물에 넣지 않는다. 수집은 정확한 `EXACT_CANONICAL_JSON` 계약만 지원한다. 수치 허용 오차나 정상 예외를 요구하는 계약은 이 개발 수집기에 넣지 않는다.

외부 도구에서 가져오는 공통 기록은 `evidence-import --records COMMON.json --generation-id ... --parent-generation ... --approve-execution-receipts`로 연결한다. `evidence-inspect`에서 격리 이유와 실제 새 실행 비용을 확인한다. 캐시 재사용은 새 실행으로 세지 않는다.

실제로 별도로 검토한 C가 있으면 `evidence-corroborate --archive ... --bundle ... --implementation-hash ... --spec-hash ... --approve-development-evidence --output ...`로 연결한다. 이 명령은 관측을 연결하고 동결할 뿐, 독립성을 선언하지 않는다. Source와 같은 구현의 관측이나 같은 함수의 수정 버전만으로 독립 C를 충족하지 않는다.

`readiness-check`는 `--evidence --knowledge --lineage --targets --protocol --usage-ledger --authority-id` 또는 host 권한을 제외한 constructor JSON `--bundle`을 읽는다. 부족하거나 잘못된 자료는 `NOT_EXECUTED_READINESS_BLOCKED`와 종료 코드 3을 반환한다. `readiness-demo`는 Source/C/T가 모두 비었을 때 최종 평가가 시작되지 않는 기능 예제다.
