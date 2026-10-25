# C1 개발 평가: 절차, 분모, 해석 경계

이 평가는 **제공된 형식 주장 C**에 대한 잘못된 결론 승격을 측정한다. 자연어 원문을 올바르게 해석했다는 검증은 아니다. 모든 결과는 `conclusion_target=SUPPLIED_FORMAL_CLAIM`, `natural_language_status=UNKNOWN`, `semantic_fidelity=NOT_ESTABLISHED`를 유지한다.

## 자료와 동결 순서

공개 개발 자료는 46건, 12개 개념 family다. 새로 만든 합성 자료이며 외부 벤치마크 사례 0건, 독립 인간 검토 0건이다. 개발 자료이므로 확인 평가나 일반화 성능으로 보고하지 않는다. 같은 의미의 영어·한국어 C0 문장 6건을 포함하며 서로 독립적인 결함 46개가 아니다.

- `fixtures/dev_contracts.json`: 원문, 제공된 형식 anchor C, 적대적 후보 O, 전제·범위·예외·시간, 제출 증거. 정답은 넣지 않았다.
- `fixtures/dev_gold.json`: 별도 평가 역할이 수작업 수학 predicate로 만든 참 집합과 관계·판정 정답. production DSL interpreter나 solver 결과에서 만들지 않았다.
- `fixtures/blind_generation_prompts.json`: LLM 생성 역할에 제공한 유일한 과제 입력. 원문과 선언된 맥락만 있고 형식 C, curated O, 증거와 gold가 없다.
- `fixtures/provenance.json`: 출처, 절차적 독립의 범위, 동결 커밋과 내용 해시.
- `baselines/llm_direct.json`, `baselines/llm_self_review.json`: 실제 역할 기반 생성과 그 후 자기검토 기록. 각각 `e24945f`, `734700f`에서 점수 산출 전에 동결했다. 자기검토에서 후보 변경은 0건이었다.

Gold는 `d067dd1`에서 core 결과 열람 전에 동결했다. 구현 역할과 평가 역할, 생성 역할을 분리했지만 같은 모델 family와 세션을 공유하므로 외부 모델이나 인간 정답과 독립이라는 뜻은 아니다. 데이터 바이트의 Git LF/CRLF 차이를 피하기 위해 결과에 정렬 키·공백 없는 UTF-8 JSON의 SHA-256도 남긴다. 규칙은 `provenance.json`에 있다.

Gold 분포는 EQUIVALENT 20, NECESSARY_ONLY 5, SUFFICIENT_ONLY 10, INCOMPARABLE 4, AMBIGUOUS 2, OUT_OF_SCOPE 3, UNKNOWN 2다. 경계 연산자, and/or, if/only-if, 전제, 입력 구간, 예외, 양화사, before/after와 시간 범위를 한 조건씩 바꾸는 최소쌍을 포함한다.

## 관계와 결론의 의미

`C ⇒ O`이면 O는 C의 필요조건이다. `O ⇒ C`이면 O는 C의 충분조건이다. 두 방향 모두 성립할 때 동치, 어느 방향도 성립하지 않을 때 비교 불가능으로 분류한다.

여기서 관계 분류는 **동일한 유한 admissible valuation에서의 점별 predicate 함의**다. 동일 양화사를 보존하는 데 충분한 검사이며, 임의의 양화된 문장 사이 함의를 완전히 결정하는 체계는 아니다. 서로 다른 양화사는 UNKNOWN, 모순 전제는 공허한 동치 대신 UNKNOWN이다. 한 valuation의 실패로 존재 주장을 반증하지 않는다. 전수 확인의 통과만 PROVED_BOUNDED로 승격할 수 있으며 무한 입력·외부 환경·원래 자연어의 증명이 아니다.

## 기준선과 정보 접근 차이

| Arm | 실제로 하는 일 | 추가 정보와 경계 |
| --- | --- | --- |
| C0 templates | 기존 `compile_claim`을 그대로 호출한다. 정확히 인식하는 6문장만 연구용 symbolic-output 관측치에 매핑한다. | 실제 target 실행은 없다. 나머지는 UNKNOWN이다. |
| LLM direct | blind 역할이 원문·선언 맥락에서 만든 O를 유한 fixture에서 검사하고 결과를 바로 승격한다. | 형식 C와 gold를 생성 시 보지 않았다. 독립 모델 API 반복 실험은 아니다. |
| LLM self-review | 동결 direct 후보를 같은 역할이 다시 검토한다. | 같은 모델·맥락의 자기검토이며 독립 판정자가 아니다. |
| direct/self-review with authority | 각 LLM arm과 **동일한 O와 증거**에 권한 검사를 추가한다. | checker는 별도로 제공된 형식 C를 본다. 이 정보 비대칭을 포함한 시스템 비교다. |
| logical authority | curated O와 제출 증거를 전제·범위·함의 방향으로 검사한다. | 독립 공급된 형식 C가 필요하다. NL-to-formal 생성 성능이 아니다. |
| unsafe lifting ablation | 같은 curated O·증거를 검증 없이 C의 결과로 승격한다. | 의도적으로 제거한 안전장치다. 실제 LLM이나 최상위 도구의 성능으로 부르지 않는다. |

핵심 인과 비교는 두 가지 paired comparison이다. curated authority와 unsafe arm은 같은 O·증거를 쓰며, 각 LLM의 guarded/unguarded arm도 같은 후보와 증거를 쓴다. 서로 다른 O를 만든 arm 사이에서는 후보별 독립 gold를 계산하고 동일 입력 성능이라고 주장하지 않는다. LLM이 만든 O가 이미 충실하면 gate의 오류 감소가 0일 수 있으며 그대로 보고한다.

생성 arm은 prompt의 양화사를 유지한다. curated Q03의 의도적 `obligation_quantifier` 변이는 새 LLM 후보에 상속하지 않는다. 존재 O는 유한 영역의 **any true**를 통과로 처리한다. 단일 valuation 실패를 이용해 LLM 생성 오류를 인위적으로 만들지 않는다. 이 두 공정성 수정은 gold 수정 없이 점수 산출 경로에 적용했고 회귀 테스트를 추가했다.

## 지표의 분모

- **Wrong REFUTED**: 제공된 형식 C가 선언된 유한 양화 영역에서 참인데 REFUTED라고 한 건수. `오류/전체 REFUTED`와 `오류/반증 불가능한 참 C`를 모두 보고한다. 전제가 모순되어 해석이 정의되지 않은 사례는 참 C 분모에서 뺀다.
- **Unsupported REFUTED**: 제출 반례가 유효 영역에 없거나 C의 predicate를 깨지 않거나, 양화사·C⇒O 권한이 없는 선언. C가 다른 지점에서 거짓일 수도 있으므로 wrong conclusion과 구분한다.
- **올바른 반례 발견률**: 후보별 gold가 REFUTED로 허용하는 사례 중 유효한 REFUTED를 반환한 비율. abstention과 함께 보고한다.
- **관계 정확도**: 점별 관계와 AMBIGUOUS/OUT_OF_SCOPE/UNKNOWN 분류가 후보별 gold와 맞는 비율. LLM은 별도 relation을 선언하지 않으면 faithful formulation의 주장인 EQUIVALENT로 점수화한다.
- **UNKNOWN precision/recall**: 제출 증거를 원래 형식 C로 승격할 수 없는 사례를 정답으로 삼는다. 임의 자연어 모호함을 판정하는 일반 성능이 아니다.
- **비용·시간**: 결정적 평가 시간과 역할 생성 시간을 분리한다. provider API 호출은 0이지만 agent 추론 자체의 token·금액 receipt는 관측 불가하므로 null이다. guarded arm은 기존 생성 비용을 공유하며 새 생성 1회로 중복 계산하지 않는다.

`witness_violates_claim_predicate`는 점별 predicate 위반만 뜻한다. `quantified_claim_refutation_valid`는 forall 조건과 유효 영역을 추가로 요구한다. 자연어 결론은 항상 UNKNOWN이다.

## 관측된 실패 예와 개발 결과의 한계

초기 curated paired 비교에서 unsafe arm은 38건을 REFUTED로 선언했고 그중 참인 C를 잘못 반증한 사례가 12건이었다. gate는 이 12건을 차단하고 허용된 반례 14/14를 유지했다. 이것은 작은 설계 자료에서의 기능 검증이다. 최종 LLM arm 수치와 실행 시간은 `results/dev_results.json`을 기준으로 읽는다.

- **B01**: x∈[0,2], C는 x≥0, O는 x>0. x=0은 O만 깨므로 참인 C의 반증이 아니다.
- **B04**: C는 x≥0, O는 x≤0. x=1은 O를 깨지만 C는 만족한다. C가 x=-1에서 거짓이라는 사실과 제출 반례의 타당성은 다르다.
- **P05/P06**: 제외된 예외 값이나 입력 구간 밖 값을 반례로 제출하면 승격할 수 없다.
- **Q02**: x=-1이 실패해도 ∃x∈[-1,1]: x≥0을 반증하지 않는다.
- **T01**: after=before+1이라는 전제에서 after≥before는 참이다. after>before+1로 바뀐 O의 실패를 원래 주장으로 올릴 수 없다.

독립 공급된 형식 C가 잘못되면 이 gate도 원래 자연어의 진실을 보증하지 못한다. 다음 확인 실험은 외부 정답 작성자, unseen 개념 family, 독립 모델/반복 샘플, 사람의 anchor 판정과 원문 모호함 adjudication이 필요하다. Jev의 독립 판단·탐사 우선순위 기여는 별도 ablation으로 남겼으며 실 API 호출은 없다.

## 미사용 봉인 자료

private archive v1 12건은 개발과 같은 개념 family였으므로 **DEVELOPMENT_RELATED_UNUSED_ONLY**로 보존했다. 첫 dev 비교 후 이 설계 한계를 발견하여 v2 12건을 개발에 없는 resource-conservation 개념 family로 새로 작성했다. 내용이나 정답은 Git에 넣지 않았으며 각각 nonce를 포함한 ZIP의 SHA-256만 공개한다. v1·v2 평가 실행은 모두 0이다.

v2 작성 시점은 **preliminary dev 결과 열람 후, 최종 여러 기준선 평가 전**이다. 이를 사전등록 확인 평가로 부르지 않는다. 같은 curator·모델과 연산자를 공유하고 family도 하나뿐이다. `holdout_commitment.json`에 v1 hash lineage와 교체 이유를 남겼다. 봉인은 무결성 commitment이며 암호화나 완전한 접근 통제가 아니다.

## 재현과 실행 경계

```powershell
python -m research.c1.evaluate --output research/c1/results/dev_results.json --llm-direct research/c1/baselines/llm_direct.json --llm-self-review research/c1/baselines/llm_self_review.json
python -m pytest tests/test_c1_authority.py tests/test_c1_evaluation.py -q
python -m pytest -q
```

신뢰된 데이터 fixture만 다루고 사용자 Python, eval/exec, 동적 target import를 실행하지 않는다. 별도 Python 환경은 의존성과 프로세스를 분리하며 OS 보안 sandbox라고 주장하지 않는다. 임의 사용자 코드 실행을 승인하거나 대신하는 경로는 없다.

평가기 입력 파일은 2 MB, oracle expression은 4096 nodes/깊이 32, 정수 literal 절댓값은 10^9, 중간 정수는 128 bits, 상태 수는 100,000, node×state 작업량은 5,000,000으로 제한한다. production validator를 재사용하지 않고 별도로 구현한 수락 경계다. 비정상 후보·미지원 연산·자원 초과는 UNKNOWN으로 닫는다. 개발 gold는 이 제한 내의 작은 정수·불리언·한 단계 전이만 사용한다.

테스트 실패·환경 실패·미실행은 구분한다. 초기 평가 테스트 101개 중 1개가 OS 임시 폴더 생성 권한 때문에 setup ERROR였다. workspace 안의 `--basetemp`를 지정해 같은 소스로 101개가 통과했다. 이후 양화사 공정성·receipt·자원경계 회귀 검사를 더해 이 파일의 최종 테스트 수는 103개다. 전체 기존 테스트와 최종 CI 상태는 최종 실행 기록에서 확인한다.
