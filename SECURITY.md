# Security model / 보안 모델

## E6 Stateful Mold 경계

E6의 공개 EFSM은 수치 상태·행동·전제조건·동시 갱신·불변식을 담은 data-only 계약입니다. 임의 Python 표현식 실행이나 import를 허용하지 않습니다. Native stateful의 rule 선택·전제조건·Bundle 인자는 공개 계약으로만 결정합니다. 실제 대상·Model 상태는 호스트 평가 비교에만 사용하며 worker에 보내지 않습니다.

E6 생성기는 승인된 공개 입력을 실제 평가 전에 등록하고, 최소 개발 failure/refutation과 첫 실패 전이 위치만 받습니다. 부모 전송 전과 worker 수신 후에 검증합니다. 원시 actual/expected state·Oracle source·비공개 final label·주관적 점수는 금지하며, 동결 후 `register`·`observe`를 전송 전에 차단합니다. 전이 snapshot도 부모에서 상태를 재계산해 검증합니다.

허용된 생성기 파일은 명시적 allowlist입니다. `temporal_service.py`, `native_stateful.py`, 대상·Oracle 파일, source-reading analysis와 CrossHair 평가기는 mount하지 않습니다. native shrinking과 두 번의 독립 재실행은 Generator 동결 뒤 평가기에서 수행합니다. Replay는 임의 프로그램의 결정론성 증명이 아닙니다.

```bash
docker build -f containers/e6-generator.Dockerfile -t tomolab-e6-generator:local containers
python -m tomolab stateful-demo --backend docker --budget 128 --pool-size 12 --shrink-budget 64 --output results/e6-container.json
```

기본 subprocess는 호스트 파일 권한을 공유하는 LOGICAL_ISOLATION_ONLY입니다. Docker는 network none·read-only·uid65534·권한 축소로 Generator를 제한하며 실제 CI 검사 결과로 판정합니다. 대상과 Model의 실행 위치·권한은 바꾸지 않습니다. 로컬 Docker 실행 불가는 컨테이너 경계 통과로 기록하지 않습니다.

Native stateful은 선언된 초기 상태의 일치, 정수 행동 인자 최대129값, trace min_size0/최대16단계를 요구합니다. Oracle·projection 오류는 finding으로 승격하지 않습니다. 내부 예산 중단이 Hypothesis 오류로 감싸진 경우에는 해당 run의 실제 중단 예외 chain을 확인한 경우만 RESOURCE_BUDGET으로 기록합니다. 무관한 nondeterminism은 전파하며 미완료 축소를 성공으로 포장하지 않습니다. 제품 callback 시간 한도는 협력적 검사이고 비정지 함수를 강제 종료하는 격리가 아닙니다.

최종 평가는 별도 source·코드·계약·source molds를 먼저 동결하고 1회 ledger를 사용합니다. Final 실행 baseline 경로도 manifest에 고정합니다. Family/expected-fault label은 공개 Generator 명세에 포함하지 않습니다. Private final source·정답·raw 기록·molds와 기존 소비된 홀드아웃은 공개하지 않습니다. [E6 기록](docs/E6_INTEGRATION.md)을 확인하세요.


## 신뢰하는 코드만 실행

대상 Python 코드와 Oracle은 평가기 호스트에서 현재 사용자 권한으로 실행됩니다. `--allow-local-execution`은 사용자가 실행을 허용했다는 표시이며 **보안 샌드박스가 아닙니다**. 직접 작성했거나 독립적으로 검토한 코드에만 사용하세요. 임의 저장소, 적대적 코드, 권한 없는 시스템을 검사하는 용도로 사용하지 마세요.

기존 `run`, `replay`, `claim-run`, `claim-replay`의 실행 모델도 같습니다. 새 Docker 선택은 **생성기의 정보 접근**을 제한하는 기능이며 대상 함수의 실행 위치를 바꾸지 않습니다.

## Generator와 Oracle의 경계

E4는 허용 필드 검증을 부모 전송 전과 worker 수신 후에 모두 수행하고 동결 후
feedback은 전송 전에 차단합니다. Hypothesis 실행·반례 축소와 정답 출력은 평가기에만
있습니다. 두 번의 반례 재실행은 임의 함수의 순수성·결정론성 증명이 아닙니다.
Docker 경계 검사는 외부 서비스에 접속하지 않고 실제 network mode와 인터페이스를
확인합니다. 외부 연결 실행 검사는 `NOT_TESTED`입니다.

| Backend | 실제 경계 | 기록되는 수준 |
| --- | --- | --- |
| `subprocess` | JSON 메시지를 주고받는 별도 프로세스. 호스트 파일 권한 공유 | `LOGICAL_ISOLATION_ONLY` |
| `docker` | 공개 패키지 코드만 읽기 전용 mount, 표준입력의 공개 명세·허용된 증거, 비루트 사용자, 네트워크 차단·읽기 전용 root·권한 축소 | `CONTAINER_BOUNDARY` |

생성기 메시지에는 대상 소스, Oracle 소스, 비공개 정답, 임의 실행 코드가 필요하지 않습니다. 최종 후보는 평가 전에 동결하고 최종 평가 결과를 생성기로 전달하지 않습니다. 동결은 학습 상태 변경을 차단하며 Python 대상의 악의적 동작까지 막는 기능은 아닙니다.

Snapshot의 SHA-256과 상태 재계산은 내용의 일관성을 검사합니다. Oracle 증거의 작성자나 진실성을 보증하는 디지털 서명이 아니므로 외부 snapshot은 호출자가 출처를 확인하고 승인한 자료만 사용해야 합니다.

Docker Engine이 사용 가능하고 기본 이미지를 미리 받은 환경에서 다음과 같이 실행합니다.

```bash
docker pull python:3.12-slim
python -m tomolab mold-demo --backend docker --solver enumeration --budget 32 --output results/mold-container.json
```

이미지 다운로드는 위의 명시적 단계입니다. 런타임이 실패한 Docker 실행을 일반 subprocess로 조용히 바꾸거나 이미지를 자동으로 받지 않습니다. 기본 이미지는 Z3를 포함하지 않습니다. 이미지와 Docker 호스트도 신뢰 경계에 포함됩니다. 컨테이너는 완벽한 보안 증명이 아닙니다. 실제 접근 거부 검증은 [릴리스 검증 기록](docs/RELEASE_VALIDATION.md)과 해당 Actions 결과를 확인하세요.

## E5의 공개 IR과 실행 경계

E5 생성기는 승인된 공개 명세·IR과 개발 증거만 받아 native Hypothesis Strategy로
새 입력을 만들고, 지원되는 제약에 한해 Z3 후보를 구합니다. 이 후보 생성은
생성기 안에서 수행됩니다. 대상·Oracle 실행, 기대 반환값, Oracle을 호출하는
Hypothesis 반례 축소와 CrossHair 실행은 평가기에 남습니다. 생성기에 복사하는
모듈 목록은 명시적으로 제한하며, 소스 파일을 읽는 AST 분석기, 서비스,
평가기와 CrossHair 모듈을 포함하지 않습니다. 별도 프로세스만으로 이 파일들을
읽을 권한까지 없어지는 것은 아니므로 subprocess는 계속 `LOGICAL_ISOLATION_ONLY`입니다.

`--public-source`와 `discovery-inspect`의 입력은 호출자가 공개를 승인한 소스입니다.
분석은 이 소스를 import하거나 실행하지 않습니다. 비공개 대상·Oracle을 이 경로에
넣지 마세요. 공개 IR은 타입·역할·그래프 해시·지원 predicate·출처를 검사하며,
중첩된 임의 필드와 원시 소스, 임의 실행 코드를 거부합니다. 명세의 `UNKNOWN`
그래프 서명은 승인 IR에 연결하고 기존 서명이 다르면 거부합니다. 프로토콜 검사는
부모 전송 전과 worker 수신 후에 적용됩니다. 이 검사는 공개 계약의 일관성을
확인하며 소스가 실제로 공개 가능한지, 선언한 계약이 참인지까지 판단하지 않습니다.

Oracle 예외는 기본적으로 호출자에게 전파됩니다. 검토한 계약이 예외를 허용할
때만 `--expected-exception`으로 CLI의 허용 목록 중 정확한 범주를 명시하세요.
명세·함수 서명 오류와 직렬화할 수 없는 결과는 대상의 반례로 바꾸지 않습니다.
결과 비교는 canonical JSON 계약을 사용하며, 모든 Python 반환 자료형의 의미적
동등성을 보증하지 않습니다. 두 번의 재실행도 결정론성 증명은 아닙니다.

`--time-budget`은 호출 사이에 확인하는 협력적 실행 예산입니다. 실행 중인 대상이나
Oracle 함수를 강제로 중단하는 제한이 아니므로, 무한 루프나 외부 효과가 없는
검토된 함수에만 사용하세요. 상태 예제는 길이가 제한된 trace 입력을 실행하는
방식이며 임의의 장기 실행 상태 시스템에 대한 격리를 제공하지 않습니다.
`discovery-plan`은 새 worker에서 동결된 후보를 만들고 최종 feedback을 차단합니다.
`--target-evidence`에는 승인된 개발 반증만 넣으며 최종 검증 정답을 재사용하지 않습니다.

E5 Docker 생성기에는 Hypothesis와 선택할 Z3의 의존성이 필요합니다. 저장소의
의존성 전용 Dockerfile은 버전을 고정하며 대상·Oracle·비공개 평가 자료를
이미지에 복사하지 않습니다. 신뢰한 Docker 호스트에서 명시적으로 준비합니다.

```bash
docker pull python:3.12-slim
docker build -f containers/e5-generator.Dockerfile -t tomolab-e5-generator:local containers
python -m tomolab discovery-demo --case sequence --backend docker --solver z3 --budget 32 --output results/discovery-container.json
```

E5 CLI는 `tomolab-e5-generator:local` 이미지를 사용합니다. 호스트에도 `qa` extra와
Z3 선택 시 `solver` extra를 설치하세요. 이미지 준비 실패나 실행 실패를 의존성 없는
이미지 또는 subprocess 실행으로 자동 대체하지 않습니다. Docker 경계의 실제 검증
상태와 평가의 범위는 [E5 통합 기록](docs/E5_INTEGRATION.md)과 해당 CI 결과를 확인하세요.

## 자료와 비밀정보

실행 결과에는 로컬 경로, 입력, 반환값, 소스 해시가 포함될 수 있습니다. 공유 전에 확인하세요. `results/`, 비공개 연구 디렉터리, `PRIVATE_*`, 이전 E1/E2 증거 ZIP, 원시 홀드아웃과 인증정보를 Git·wheel·sdist·Release 자산에 넣지 않습니다.

API 키는 환경변수로만 전달하고 코드, 로그, 이슈, 지원 요청에 쓰지 마세요. Jev는 선택적 외부 연결이며 사용 시 비용이 발생할 수 있습니다. 기본 Mold와 Claim 실행에는 유료 호출이 없습니다.

이 도구는 무제한 입력에 대한 정확성, 임의 자연어 주장의 참·거짓, LLM 안전성 또는 현실의 진실을 독립적으로 증명하지 않습니다. `UNKNOWN`과 유한 예산 내 미발견은 성공 판정이 아닙니다.

## 취약점 보고

[GitHub 이슈](https://github.com/hibou04-ops/antemortem-structural-lab/issues)에 인증정보나 개인 자료 없는 최소 재현을 작성하세요. 민감한 취약점은 저장소에서 비공개 취약점 보고가 제공되는지 먼저 확인하세요. 유효한 인증정보를 게시하지 마세요.

## English summary

E7의 지식 승격은 검토된 호스트가 확인한 별도 구현·Oracle의 positive/negative 개발 영수증과 명시적 계약에 의존합니다. 해시는 그 확인의 신원·일관성을 결속하며 의미적 독립성을 인증하지 않습니다. `HYPOTHESIS`와 `QUALIFIED_FOR_PROBING`은 검증된 원인이나 대상 결함의 증명이 아닙니다.

E7 Generator allowlist는 실행 서비스·파일 저장소·예제·CrossHair·대상·Oracle 모듈을 포함하지 않습니다. 입력은 한 번 캡처한 JSON을 전송 전과 worker에서 검증하며 raw Oracle 결과·주관적 점수·최종 split을 거부합니다. 동결 후 feedback, 재해시한 상태 조작, 과거 snapshot 복귀와 검증 캐시 경합을 검사합니다. 검증 캐시는 전체 내용·검증 버전에 묶이며 별도 복사본만 반환합니다.

영속 저장은 협력 writer의 exclusive lock·fsync·해시 체인·전체 journal prefix를 사용합니다. 기존 반증·동결 부모를 보존한 명시적 새 세대만 개발 영수증으로 확장합니다. final split은 새 세대에서도 허용하지 않습니다. 깨진 append나 남은 lock은 자동 삭제하지 않습니다. 호스트가 거짓으로 선언한 Oracle 독립성이나 적대적 파일시스템 전체를 보장하지 않습니다.

실제 프로젝트 평가의 private source·입력·정답·raw records·학습 archive·holdout ledger는 공개 저장소와 배포 자산 밖에 보존합니다. CrossHair는 평가기의 별도 source-aware tier이며 그 결과를 final Generator에 피드백하지 않습니다. 공개 참조 모델 IR을 비공개 대상에서 추출한 구조라고 표현하지 않습니다.

Only run authored or independently trusted targets and Oracles. They execute with evaluator-host privileges; consent flags are not a hostile-code sandbox. The default subprocess generator has logical isolation only. The optional Docker generator limits its filesystem, network and privileges, but does not isolate target execution. Pre-pull the trusted image explicitly. Inspect actual validation and CI boundary tests rather than inferring isolation from a process name. Snapshot hashes and state reconstruction check consistency, not authorship or the truth of Oracle evidence; callers must approve external snapshots. Review evidence before sharing, keep private research and credentials out of artifacts, and preserve `UNKNOWN` and bounded-search limitations.

E5 runs native candidate generation and supported Z3 checks inside the generator; Oracle execution, shrinking and CrossHair stay in the evaluator. Only explicitly approved public source is converted to validated IR. Unknown nested fields and unsupported protocol data are rejected before transport and again in the worker. These checks do not turn a host subprocess into an access-control boundary. Oracle exceptions propagate unless their category is explicitly approved. Time budgets are cooperative and cannot interrupt a running trusted function. Prepare the dependency image with `containers/e5-generator.Dockerfile` before selecting the E5 Docker backend; runtime failures do not trigger an automatic backend fallback.
