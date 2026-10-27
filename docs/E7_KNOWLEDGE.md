# E7 구조적 지식의 증거 계약

추가적인 공개 사전조건이 typed domain보다 좁다면 stateless `run_knowledge(..., input_accepts=...)`의 검토된 호스트 predicate를 사용합니다. 입력 복사본에서 정확한 bool을 반환해야 하며 예외는 전파합니다. 거절 입력은 target·Oracle·학습 label·반증을 만들지 않습니다. `PRECONDITION_REJECTED` 시도 기록·guard 시간·native predicate 시도와 실제 호출 수를 구별합니다. 이 callback은 worker에 전달하지 않습니다. Stateful opaque guard는 지원하지 않으며 실행 전에 거부합니다. 기존 공개 EFSM preconditions와 native RBS 경로는 유지합니다.

E7은 실패 입력과 공개 모델에서 만든 **실패 소속 가설**을 보존하고, 독립 개발 증거와 적용 계약을 통과한 후보만 새 탐색에 사용합니다. 특정 관계가 참인 입력에서 같은 실패 계열이 관측될 것이라는 반증 가능한 예측을 검사합니다. 원인과 결함의 재현 여부는 계속 미확정입니다.

## 실제 데이터 흐름

`개발 실패 로그 → E5/E6 경쟁 가설 → 독립 개발 반증 → 범위 내 지지 → 적용 계약 검사 → 동결 계획 → 대상별 탐색`

| 모듈 | 역할 |
| --- | --- |
| `knowledge.py` | 기존 E5/E6 Version Space·typed feature·AST predicate·temporal interpreter를 재사용해 후보·지지·반증·적용 범위를 관리합니다. |
| `knowledge_store.py` | 신뢰된 호스트에서 append-only 지식 기록을 저장합니다. Generator 배포 코드에서 제외됩니다. |
| `knowledge_engine.py` | qualified 가설로 일부 후보 순서를 바꾸거나 정수 SMT witness를 제안하고 native Hypothesis 후보를 유지합니다. |
| `knowledge_service.py` | 검토된 대상과 독립 Oracle의 실제 실행·계수·native search/shrink·독립 replay를 담당합니다. |
| `knowledge_protocol/boundary/worker.py` | 공개 데이터 계약과 전송 전·수신 후 검증, 동결 후 수정 차단을 적용합니다. |

`KnowledgeArchive.from_failure_log()`는 관측한 입력과 최소 증거를 기존 엔진에 넣습니다. 추가 Oracle 호출 없이 경쟁 구조를 생성·제거합니다. `from_engine_snapshot()`은 검증된 **동결 E5/E6 snapshot**을 가져옵니다. 원본 후보가 반증돼도 같은 archive의 관계·근거·경쟁 그룹에서 삭제하지 않습니다.

공통 Typed IR은 역할·자료형·연산·전제조건·불변식과 AST 관계, 공개 EFSM의 전이 전후 상태·행동·순서·의존성·최초 실패 위치를 연결합니다. 숫자 좌표를 그대로 복사하는 관계와 임의 상수 AST, temporal 인자 좌표 조건은 자동 승격 대상에서 제외합니다. 경계·순서 관계도 독립 반증을 통과해야 합니다.

## 상태와 승격 근거

| 상태 | 실제 의미 |
| --- | --- |
| `HYPOTHESIS` | 관측에서 생성한 후보이며 독립적인 contrastive 근거가 부족합니다. |
| `SUPPORTED_WITHIN_SCOPE` | 같은 검토된 독립 구현·Oracle의 개발 자료에서 양성·음성 예측을 모두 맞췄고 관측한 반증이 없습니다. |
| `CONTRADICTED` | 예측과 Oracle 관측이 충돌했습니다. 반증은 보존하고 자동 적용을 차단합니다. |
| `APPLICABILITY_UNKNOWN` | 새 대상의 의미·자료형·계약·출처 또는 AST 대응 근거가 부족하거나 다릅니다. |
| `QUALIFIED_FOR_PROBING` | 범위 내 지지와 새 대상의 적용 계약을 만족해 탐색 후보 제안에 사용할 수 있습니다. |

양성과 음성을 서로 다른 구현에서 하나씩 모아도 승격하지 않습니다. 동일 입력에서 실패 계열·최초 실패 위치가 충돌하는 관측도 지지로 취급하지 않습니다. 좌표 이름·구문 유사성만으로 의미 대응을 인정하지 않으며, AST 가설은 승인된 공개 IR과 대응하는 연산 그래프를 추가로 요구합니다.

출처에는 `project`, `lineage`, `revision`, `oracle_id`, `semantics`를 선언합니다. 승격에 사용할 독립 증거는 실제 `implementation_sha256`, `oracle_sha256`, 검토 식별자 `independence_id`도 필요합니다. Source와 독립 구현·Oracle의 코드 해시, Oracle ID, 계보와 검토 식별자가 달라야 합니다. 문자열만 다르거나 해시가 없으면 후보 상태를 유지합니다.

이 값은 **검토된 호스트의 출처 확인**에 의존합니다. 해시는 파일 정체성과 기록 일관성을 묶지만, 의미적 독립성·실제 Oracle 실행·가설의 인과적 정확성을 암호학적으로 증명하지 않습니다. 호출자는 최소 증거를 생성하기 전에 실행 기록과 코드 버전·검토 범위를 확인해야 합니다. 자기 점수·LLM 확신·다수결로 승격하는 API는 없습니다.

## 공개 Python API 흐름

아래 코드는 저장소 루트에서 동봉된 공개 기능 예제를 읽습니다. `source-failures.json`과 `observations.json`은 검토된 예제 함수·Oracle에서 만든 개발 기록입니다. 이 예제의 성공을 독립 프로젝트 연구 성과로 계산하지 않습니다. 선택 의존성 `qa,solver`가 설치돼 있어야 합니다.

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from tomolab.discovery.knowledge import KnowledgeArchive
from tomolab.discovery.knowledge_engine import plan_knowledge
from tomolab.discovery.knowledge_store import KnowledgeStore

folder = Path("examples/knowledge")
def load(name):
    return json.loads((folder / name).read_text(encoding="utf-8"))

archive = KnowledgeArchive.from_failure_log(
    load("source-spec.json"), load("source-failures.json"),
    load("source-provenance.json"), public_ir=load("source-ir.json"),
)
# 이 승인 표시는 검토한 동봉 개발 기록에만 적용합니다.
for observation in load("observations.json"):
    archive.observe(observation, trusted_observation=True)
frozen = archive.freeze()

plan = plan_knowledge(
    frozen, load("target-spec.json"),
    target_provenance=load("target-provenance.json"),
    public_ir=load("target-ir.json"), budget=8, pool_size=16,
)
assert plan["oracle_calls"] == plan["target_calls"] == 0
assert plan["final_feedback_allowed"] is False

with TemporaryDirectory() as directory:
    store = KnowledgeStore(Path(directory) / "knowledge.jsonl")
    store.append(frozen, record_id="reviewed-development-v1")
    assert store.latest().snapshot() == frozen
    resumed = archive.fork("reviewed-development-v2")
    assert resumed.frozen is False
    assert resumed.snapshot()["journal"][:-1] == frozen["journal"]
    # 새로 검토한 개발 영수증은 resumed.observe(...)로 추가합니다.
    # 이 예제는 기존 근거를 보존하는 빈 다음 세대까지 확인합니다.
    next_frozen = resumed.freeze()
    store.append(next_frozen, record_id="reviewed-development-v2")
    assert store.latest().snapshot() == next_frozen
    assert archive.snapshot() == frozen
```

실제 새 개발 실행은 `make_observation(spec, evidence, origin, ...)`로 최소 영수증을 만듭니다. 최소 필드는 기존 E5의 `kind/evidence_id/inputs/invariant/category/signature`, temporal 실행은 `first_failure_index`를 추가합니다. 전체 envelope는 공개 명세·계약·승인 IR·출처·구현 해시·`split="development"`와 내용 해시를 묶습니다. raw actual/expected 상태·정답·소스·주관적 점수·임의 필드를 거부합니다.

`freeze()` 이후 `learn()`과 `observe()`는 거부됩니다. snapshot은 journal에서 후보·상태·경쟁 그룹·동결 여부를 다시 계산하며, 상태나 카운터를 바꾼 뒤 해시만 재계산해도 거부합니다. `qualify()`는 대상별 판정과 qualified claims를 반환합니다. `target_seen_in_development`는 최종 대상의 구현이 개발 자료에 이미 사용됐는지 검사하는 정보이며, 최종 평가 담당자는 새 Target 분리를 별도로 강제해야 합니다.

장기간 개발을 이어갈 때는 **동결 부모의 `fork(generation_id)`**로 새 복사본을 엽니다. 부모 객체·snapshot과 이전 journal 전체를 유지하고, 부모의 완전한 receipt 해시와 새 세대 ID를 묶은 명시적 `fork` 기록을 추가합니다. 새 세대 ID는 archive 전체 계보에서 유일해야 합니다. 새 복사본은 `observe()`로 검토된 개발 영수증만 추가하며, 새 source batch를 `learn()`으로 덧씌우는 것은 거부합니다. 새 Source 학습은 별도 archive 문맥에서 수행합니다.

새 세대에서도 과거 반증은 남으며 승격 상태를 초기화하지 않습니다. 최종 feedback은 세대와 관계없이 계속 거부합니다. 재생은 각 fork 직전의 동결 부모 해시, 세대 ID와 현재 동결 이벤트를 검증하므로, `frozen` 값만 바꾼 임의 재개와 부모·세대 기록의 불일치를 거부합니다. 이는 같은 최종 Target을 다시 학습용으로 소비해도 된다는 허가가 아닙니다.

## 영속 기록과 검증 캐시

`KnowledgeStore.append()`는 같은 `record_id`와 같은 snapshot의 반복 기록을 `ALREADY_COMMITTED`로 처리합니다. 같은 ID의 내용 변경을 거부합니다. 기록은 canonical JSONL과 이전 기록 해시를 연결하며, 같은 source/spec/temporal contract/public IR 문맥에서는 journal이 기존 prefix를 보존하며 확장돼야 합니다. 따라서 `이전 freeze → 명시적 fork → 새 개발 관측 → 새 freeze`는 누적 저장할 수 있고, 새 ID를 붙여 반증 이전 snapshot을 최신으로 되살리는 롤백은 거부합니다.

호스트 저장은 인접 lock 파일의 배타적 생성으로 **협조하는 writer**를 제어하고, append 뒤 `flush/fsync`를 호출합니다. 끊어진 마지막 행·변조·lock 충돌은 자동 삭제·재시도·덮어쓰기로 복구하지 않고 중단합니다. 원래 파일을 보존한 명시적 운영자 복구가 필요합니다. 분산 트랜잭션·적대적 호스트 보호·전원 장애에서의 완전한 원자성을 보장하는 저장소는 아닙니다.

동결 archive의 반복 검증은 **전체 canonical 내용 + 검증 버전**을 키로 캐시합니다. 키를 만든 JSON 문자열에서 독립 입력 복사본을 복원하고 같은 내용만 검증하므로, 검증 도중 호출자가 원래 사전을 바꿔 다른 archive를 이전 키에 저장하지 못합니다. 엄격한 journal 재생을 성공한 뒤에만 저장하며 읽기·쓰기 모두 복사본을 사용합니다. 최대4개 항목, 키 문자열 합계16MiB로 제한하고 동시 접근 lock을 사용합니다. 변경된 내용·재해시한 주장·다른 검증 버전은 이전 검증을 재사용하지 못합니다. 개발 중인 archive는 캐시하지 않습니다. 이 최적화는 반복 계산을 줄이며, 전체 연구 효율 개선 여부는 별도 평가로 판정합니다.

## 지원 범위와 평가 경계

- Archive는 source·독립 개발 관측을 각각 최대256개, 후보 최대4,096개·source 실패 계열 최대8개로 제한합니다. 총 관측 상한은 fork 뒤에도 초기화하지 않으며 최대32번의 명시적 세대 fork를 허용합니다. snapshot 검증은8MiB, host store는64MiB 상한을 적용합니다.
- 입력·AST·EFSM의 실제 표현 범위는 기존 E5/E6 유한 계약을 따릅니다. 임의 Python 객체 의미·무제한 trace·비정지 callback을 지원한다고 주장하지 않습니다.
- 기본 경로는 Hypothesis의 생성·Stateful Testing·축소를 재사용합니다. qualified Mold가 없으면 native 경로를 유지합니다. 모든 가설을 무효화한 뒤 기준선과 같아졌다는 결과는 추가 발견 가치로 인정하지 않습니다.
- 비용에는 가설·IR·갱신·solver·후보·IPC/직렬화·Oracle·native search/shrink·replay를 포함합니다. 겹치는 phase는 합산하지 않고, 미계측 항목은 미확정으로 남깁니다.
- Archive 내용 검증과 native 계획 snapshot의 이식성은 구별합니다. `KnowledgeEngine.from_snapshot()`은 native 후보·SMT 선택을 재생하므로 Hypothesis/Z3·제품 버전이 달라지면 유효한 과거 계획도 재생에서 거절될 수 있습니다. 동일 의존성·제품 버전을 보존하고 호환성을 확인해야 합니다.
- 기본 subprocess는 `LOGICAL_ISOLATION_ONLY`입니다. Docker의 Generator 접근 통제와 신뢰된 호스트 대상·Oracle 실행의 안전 범위를 구별합니다.
- 최종 Target 구현·정답·비밀 seed·최종 feedback을 같은 세대 학습으로 보내지 않습니다. 기존 E1~E6 소비 holdout도 재사용하지 않습니다. 새 평가의 범위와 판정 기준은 [E7 평가 계약](E7_EVALUATION_CONTRACT.json)에서 관리합니다.

이 문서는 구현 계약과 한계를 설명합니다. 함수 실행 수·가설 사용·테스트 수 자체를 일반화 성능이나 인과적 추가 발견으로 승격하지 않습니다.
