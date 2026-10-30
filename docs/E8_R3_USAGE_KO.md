# E8-R3 실행 경로 — 미발행 연구 후보

실패 입력을 그대로 저장하는 기능과, 실패가 발생한 수치 구조를 보존하면서 새로운 입력을 생성하는 기능을 구분합니다. R3는 R2의 레시피·Source domain·Oracle·생성 정책을 바꾸지 않고 실행 비용과 검증 경로를 분리합니다. PyPI `0.7.0a1`에는 R1·R2·R3가 없습니다. 아래 명령은 후보 wheel `0.8.0a1`을 별도 환경에 설치한 뒤 사용합니다.

```powershell
python -m pip install --no-deps ./dist/antemortem_structural_lab-0.8.0a1-py3-none-any.whl
python -m tomolab numerical-prepare-guide --help
python -m tomolab numerical-runtime --help
python -m tomolab numerical-audit --help
```

승인된 `[qa]` 의존성이 필요합니다. 실제 독립 설치 검사는 `scripts/check-numerical-r3-wheel.py`이며 후보 wheel 밖에서 새 환경을 만들고 다음 경로를 검증합니다.

```powershell
# 기존 승인 archive를 가진 신뢰된 host에서만 실행. 출력 경로는 새 경로여야 합니다.
python -m tomolab numerical-prepare-guide --archive approved-source.json --prepared-dir prepared-guide --approval-state host-current-approval.json --output prepare-receipt.json

# D와 동일한 공개 수치 지식을 사용하는 기본 B. D guide/archive/recipe를 읽지 않습니다.
python -m tomolab numerical-runtime --method B --seed 7 --size 4 --max-examples 128 --budget 16 --shrink-budget 0 --allow-local-execution --output baseline-receipt.json

# prepare-receipt의 승인된 artifact_digest를 신뢰된 host에서 확인해 사용합니다.
python -m tomolab numerical-runtime --method D --prepared-dir prepared-guide --approval-state host-current-approval.json --expected-digest APPROVED_ARTIFACT_DIGEST --seed 7 --size 4 --max-examples 128 --budget 16 --shrink-budget 0 --allow-local-execution --output runtime-receipt.json
python -m tomolab numerical-audit --method D --prepared-dir prepared-guide --approval-state host-current-approval.json --expected-digest APPROVED_ARTIFACT_DIGEST --seed 7 --size 4 --max-examples 128 --budget 16 --shrink-budget 0 --allow-local-execution --output audit-receipt.json
```

`APPROVED_ARTIFACT_DIGEST`는 설명용 자리표시자입니다. 준비 명령은 원본 검증·보정·컴파일과 외부 승인 상태 작성을 수행합니다. 재사용은 작은 guide·approval·manifest와 외부 현재 승인 상태만 읽습니다. R2도 매 실행마다 전체 archive를 재생하지 않았습니다. R3의 확인된 최적화 대상은 D의 두 번째 후보 생성입니다.

`numerical-runtime`은 A/B/C/D 모두 주 생성 1회, 기준 생성 0회입니다. D runtime은 전체 구조·실제 수신 후보 digest·domain·중복·제외·출처·입력 특징·요청 identity·동결 상태를 검증한 뒤 Source/Oracle를 호출합니다. `equivalence_check_status=NOT_RUN_IN_RUNTIME`이며 동등성 감사를 수행했다고 주장하지 않습니다. `numerical-audit --method D`는 주 생성 1회와 별도 기준 생성 1회로 순서·입력·출처·recipe·transform·contract 전체를 비교합니다. Docker 감사는 동일한 resolved image를 기준 생성에도 사용합니다. A/B/C에 불필요한 두 번째 생성을 추가하지 않습니다. 기존 `numerical-run` 및 Python API의 기본 D는 R2 호환 감사 수준을 유지합니다.

전체 archive는 host 감사·재현용이며 worker로 보내지 않습니다. 경량 guide는 원본 content digest, validation version/코드, 의미 버전, recipe/parameters, 공개 입력 계약, 반증 상태, compiler bytes, schema, 승인된 digest와 결속합니다. 외부 승인 상태는 신뢰된 host의 권한 입력입니다. bundle 안에서 새 해시를 계산하는 것만으로 재승인되지 않습니다. 새로운 증거·반증·컴파일러·정책이 생기면 host가 현재 승인 상태를 갱신해야 하며, 파일 이름·mtime으로 최신성을 추측하지 않습니다. 정상 실행에서 전체 archive 검증 0회, 보정 0회, 컴파일 0회이며 Oracle 결과나 후보를 캐시하지 않습니다.

준비 디렉터리와 실행 영수증은 기존 경로를 덮어쓰지 않습니다. 불완전한 준비 파일은 로드하지 않습니다. 실행 아티팩트는 1MiB, 전체 요청은 기존 8,000,000바이트 상한을 유지합니다. 학습·파라미터 교체는 동결 후 차단합니다. C에만 검토된 재생 입력을 전달하고, A/B는 D의 archive·가이드·비공개 실패 자료를 받지 않습니다.

영수증의 API 시간은 API 진입 이후 import·검증·worker·평가를 포함합니다. 후보 최초 불일치 관측과 2회 재현 후 확인된 실패 시점을 분리합니다. CLI `.io.json`은 실제 기록된 영수증 bytes의 SHA-256과 직렬화·write/flush 시간을 별도로 결속합니다. Python 시작·CLI module import·companion 자체 쓰기는 별도 외부 process stopwatch로 측정합니다. 중첩 구간을 합산해 총시간으로 만들지 않습니다. 과거 최초 수집 비용은 `UNKNOWN`이며 0으로 두지 않습니다.

공개 Track1은 직접 작성한 평가 callback으로 실행하는 소프트웨어 비용 검사이며 실제 Source/Oracle 호출은 0회입니다. 새 Source Track2는 사전 동결한 6 seed×4방법의 개발 검증입니다. 기존 R2 결과의 `NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR` 판정은 그대로 보존합니다. 입력 수·같은 기전 재현·새 기전·실행 최적화·독립 C·외적 일반화·발행은 별도 상태입니다. 신규 결과와 B/C 대비 비용·추가 가치는 `E8_R3_RESULTS.json`에 기록합니다. 독립 C와 미소비 Target이 없으므로 PR #8은 draft, `allow_release=false`이며 병합·tag·Release·PyPI upload를 실행하지 않습니다.
