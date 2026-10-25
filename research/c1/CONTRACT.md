# C1 유한 계약과 논리적 권한

연구용 API이며 v0.2.0의 배포 패키지·명령·의미 해석기를 변경하지 않는다.
이 검사는 사람이 제공한 형식 주장 `C`와 생성된 의무 `O`를 비교한다.
`claim_text`와 `C`의 의미 동치는 검증하지 않는다. `reviewed`는 제공자의
검토 상태를 기록하는 값이며 엔진이 자연어 정확성을 인증했다는 뜻이 아니다.

## 계약

`contract.schema.json`은 저장 형식을 정의한다. 실제 허용 연산과 타입·범위·자원
제한은 `authority.py`가 추가 검사한다. JSON의 필수 필드는 다음과 같다.

| 필드 | 의미 |
| --- | --- |
| `schema`, `id`, `claim_text` | 버전, 사례 식별자, 원문 주장 |
| `variables` | 닫힌 정수 구간 또는 불리언 입력·상태 공간 |
| `assumptions` | 모든 조건이 참이어야 하는 전제·전이 관계 |
| `quantifier`, `obligation_quantifier` | `forall` 또는 `exists`; 의무는 기본적으로 주장과 동일 |
| `exceptions` | 하나라도 참이면 제외하는 입력·상태 |
| `time` | 단일 상태(`state`, horizon 0) 또는 한 단계 전이(`transition`, horizon 1) |
| `claim`, `obligation` | 독립 출처의 형식 주장과 생성된 검증 의무 |
| `evidence_scope` | `finite` 및 지원 범위 설명 |
| `interpretation` | `reviewed`, `ambiguous`, `out_of_scope`와 출처 |
| `metadata` | 선택적 출처·작성자·계보 JSON 기록, 논리 의미를 추가하지 않음 |

전이의 이전·이후 상태는 별도 변수로 명시하고 허용 전이는 `assumptions`에
인코딩한다. `time`은 DSL에 없는 시간 논리를 만들어 주지 않는다. 긴 trace,
무한 시간, fairness, 확률, 부동소수점, 임의 함수 호출은 지원하지 않는다.
입력 범위 밖의 실수나 예외 조건을 자연어 설명으로만 쓰면 검증되지 않는다.
검증에 영향을 주는 모든 조건은 DSL에도 명시해야 한다.

DSL은 정수·불리언 상수, 선언된 변수 문자열, 연산 목록 `[op, arg, ...]`만
허용한다. 연산은 `and`, `or`, `not`, `implies`, `==`, `!=`, `<`, `<=`, `>`,
`>=`, `+`, `-`, `*`이다. 불리언을 정수로 취급하지 않는다. `eval`·`exec`·임의
모듈·사용자 Python 코드를 사용하지 않는다.

최대 입력 상태 100,000개, 변수 16개, 식 깊이 32, 전체 식 노드 4,096,
JSON 256 KiB, 정수 리터럴·구간 경계 절댓값 10^9, 중간 정수 128 bit이다.
전체 식 노드 수와 입력 상태 수의 곱도 5,000,000 이하로 제한한다.
한도를 넘거나 형식이 잘못되면 `UNKNOWN`이며 일부 탐색 결과를 증명으로 쓰지 않는다.

## 관계의 방향

공통 지원 영역 `A`는 선언된 입력 공간, 모든 전제, 예외의 부정을 결합한 것이다.
엔진은 `A ∧ C ∧ ¬O`와 `A ∧ O ∧ ¬C`의 만족 여부를 유한 전수 열거로 확인한다.

| 관계 | `C ⇒ O` | `O ⇒ C` | 가능한 결과 승격 |
| --- | --- | --- | --- |
| `EQUIVALENT` | 참 | 참 | 유효 실패로 반증, 전수 성공으로 유한 증명 |
| `NECESSARY_ONLY` | 참 | 거짓 | 의무 실패로 주장 반증 가능 |
| `SUFFICIENT_ONLY` | 거짓 | 참 | 의무 전수 성공으로 주장 유한 증명 가능 |
| `INCOMPARABLE` | 거짓 | 거짓 | 승격 불가 |
| `AMBIGUOUS` | 미부여 | 미부여 | 해석 확인 필요 |
| `OUT_OF_SCOPE` | 미부여 | 미부여 | 지원 범위 밖 |
| `UNKNOWN` | 미부여 | 미부여 | 형식 오류·자원 제한·혼합 양화사·불일치 전제 등 |

이 관계는 **점별 술어 관계**이다. 동일 양화사를 적용했을 때 함의가 보존되는
충분한 근거이며, 고정된 한 모델에서 양화된 명제의 진릿값만 비교하는 방식이 아니다.
따라서 모든 가능한 양화 명세 함의를 완전하게 분류한다고 주장하지 않는다.
서로 다른 양화사는 `UNKNOWN`으로 남긴다. 지원 영역이 비면 공허한 참을 이용한
권한 부여를 막고 `UNKNOWN / INCONSISTENT_OR_EMPTY_PREMISES`로 반환한다.

## API와 증거

```python
from research.c1.authority import analyze, adjudicate

relation = analyze(contract)
decision = adjudicate(contract, {"status": "FAIL", "witness": {"x": -1}})
bounded_proof = adjudicate(contract, {"status": "PASS_EXHAUSTIVE"})
```

`analyze`는 관계, 함의 두 방향, 반대 방향의 분리 witness, 입력/지원 영역 상태 수,
전제 만족 여부, 계약 SHA256, 시간을 반환한다. `formal_anchor_only=True`가 항상 붙는다.

`adjudicate`는 evidence를 신뢰하지 않고 다시 검증한다. 실패 witness는 모든 변수의
정확한 타입·범위·전제·예외를 만족하고 실제로 의무를 위반해야 한다. `forall` 주장과
`C ⇒ O`가 있을 때만 `REFUTED`로 승격한다. `exists` 주장에는 한 실패가 반증 권한을
갖지 않는다. `PASS_EXHAUSTIVE`는 전체 지원 영역에서 의무의 양화 진릿값을 재계산한
다음 `O ⇒ C`가 있을 때만 `PROVED_BOUNDED`를 반환한다. 표본 성공은 증명이 아니다.

증거에 `contract_sha256`을 제공하면 계약과 반드시 일치해야 한다. 생략 시에도
현재 계약에서 증거를 다시 계산하므로 외부 과거 실행을 인증하는 의미는 없다.
이 경로는 제한된 DSL의 논리적 권한 실험이다. 실제 프로그램 실행 결과·소스 동일성,
자연어의 정확한 의미·실세계 요구사항 충족을 입증하지 않는다.
