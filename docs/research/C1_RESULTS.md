# C1 개발 결과: 조건부 승격 오류는 감소, 일반 의미 정확성은 미입증

관측일: 2026-10-26 (Asia/Seoul). 자료: 이 브랜치의
[dev_results.json](../../research/c1/results/dev_results.json),
[Z3 결과](../../research/c1/results/smt_crosscheck.json).

**핵심 판단 — INFERENCE [82%]:** 제공된 형식 anchor를 기준으로, 의도적으로
변형한 의무의 결과를 무조건 올리는 정책보다 방향·범위·전제 검사가 잘못된
반증을 줄였다. 실제 blind LLM 후보에는 잘못된 REFUTED가 없어 **LLM의 허위
반증 감소는 입증하지 못했다**. 자연어 의미 정확성은 모든 결과에서 UNKNOWN이다.

## 자료와 비교 조건

공개 개발 46건 / 12 family, 새 합성 자료다. 별도 평가 역할이 수학 predicate와
truth membership로 정답을 만들고 `d067dd1`에서 core 결과를 보기 전에 고정했다.
후보 생성 역할에는 원문과 선언된 맥락만 제공했다. 인간 의미 검토 0건, 외부
벤치마크 자료 0건이다. 같은 모델 계열의 역할 분리이며 통계적 독립이나 외부
정답 권위를 뜻하지 않는다. [출처와 절차](../../research/c1/EVALUATION.md).

두 종류의 비교를 구분한다. curated unsafe/gated는 **완전히 같은 O와 제출 증거**를
사용하는 정책 ablation이다. 실제 LLM은 별도 생성한 O를 사용하며, 그 O에 대한
유한 양화사 검증 후 기본 승격 정책과 authority 정책을 비교한다. 생성기가 받지
못한 참조 C를 checker가 제공받는 정보 비대칭도 있다. arm 간 서로 다른 O에서
반례 분모가 14와 23으로 달라지므로 절대 반례 수를 우열로 읽으면 안 된다.

## 기준선별 관측

`잘못된 REFUTED`는 전수 영역에서 형식 C가 참인 경우만 센다. `무권한 REFUTED`는
유효 영역·양화사·제출 반례·C⇒O 조건을 갖추지 못한 선언이다. C가 다른 입력에서
거짓이더라도 무권한일 수 있다. 비율은 각각 선언 수를 분모로 표시했다.

| arm | 잘못된 REFUTED / 선언 | 무권한 REFUTED | 유효 반례 / 해당 O의 정답 대상 | 관계 분류 | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| 의도적 unsafe 승격 ablation | 12/38 | 24 | 14/14 | 20/46 | 0 |
| 동일 curated O + authority | 0/14 | 0 | 14/14 | 46/46 | 27 |
| 실제 C0 template + 관측값 adapter | 0/6 | 0 | 6/14 | 8/46 | 40 |
| blind LLM 직접 생성 | 0/23 | 0 | 23/23 | 40/46 | 5 |
| 같은 LLM 자기검토 | 0/23 | 0 | 23/23 | 40/46 | 5 |
| 동일 LLM 직접 O + authority | 0/23 | 0 | 23/23 | 41/46 | 6 |
| 동일 자기검토 O + authority | 0/23 | 0 | 23/23 | 41/46 | 6 |

C0는 실제 기존 `compile_claim`를 호출해 6/46 문장만 수용했다. target 프로그램의
bug-finding 성능이 아니라 symbolic output observation adapter의 결과다.
LLM relation은 생성 O의 새 정답 관계에 비교하며 UNKNOWN 출력도 분모에 포함했다.
이 분류 정확도는 **원문 의미 정확도**가 아니다.

curated의 UNKNOWN precision/recall은 각각 27/27, 27/27이며 판정 coverage는
19/46이다. C0는 27/40, 27/27이다. LLM은 5/5, 5/6에서 gate 후 6/6, 6/6으로
변했다. 전부 UNKNOWN으로 만든 결과는 아니며 각 arm의 유효 반례를 유지했다.
작은 개발 자료에서 설계된 gate를 검사한 결과이므로 일반화 추정치는 아니다.

LLM 직접 생성 46건 중 FORMALIZED 41 / UNKNOWN 5였다. 별도 turn 자기검토에서
후보 변경 0건이었다. 직접 생성 약 60.2초, 자기검토 추가 약 31.3초이며 token과
금전 비용은 실행 인터페이스에서 제공되지 않아 UNKNOWN이다. 실제 외부 모델
API와 Jev 호출은 0회다. 이것을 계산 비용 0원으로 해석하지 않는다. 유한 검사
자체는 한 번의 로컬 실행에서 curated 약 2ms, LLM arm 약 3ms였으며 성능
벤치마크로 일반화하지 않는다. 정확한 실행 시간은 JSON receipt에 있다.

## 잘못된 승격의 구체적 사례

1. **B01 경계 조건:** x∈[0,2], C=`x>=0`, O=`x>0`, witness x=0.
   O는 실패하지만 C는 참이다. O는 충분조건일 뿐이고 C⇒O가 성립하지 않아
   gate는 UNKNOWN이다. unsafe 승격은 거짓 REFUTED를 선언한다.
2. **Q02 존재 양화사:** C=`exists x in [-1,1]: x>=0`에서 x=-1만 실패했다.
   x=0이 있으므로 존재 C는 참이다. curated 제출의 한 실패로는 반증하지 못한다.
   실제 LLM의 정확한 존재 후보는 양화사대로 전수 검사하여 이 오류로 세지 않았다.
3. **P03 모순 전제:** 유효 영역이 비어 공허한 O 통과가 생긴다. LLM 기본 정책의
   PROVED_BOUNDED 1건을 gate는 UNKNOWN으로 보류했다. C의 truth가 미정이므로
   이 건을 `wrong_proved_count`에 넣지 않는다. 근거 없는 입증 선언의 차단이다.
4. **P05/P06/P08/T04:** 영역·전제·예외 밖 witness는 O의 실패를 보여도
   원래 계약의 반례가 아니다. 반례 유효 영역 gate가 이를 거절한다.

## 구현 검증과 수정 이력

전체 **192 tests PASS**: 기존 45 + C1 147. 별도 bitmask oracle로 가능한
Boolean C/O 조합 2,560개 결론을 대조했고 잘못된 형식 결론 0건이었다. 이
soundness 점검은 해당 네 상태에만 해당하며 completeness나 NL 의도를 증명하지 않는다.
Z3 독립 visitor는 46/46 관계·전제·방향이 일치했다. 40개 case에서 실제
SAT/UNSAT 질의를 했고 6개는 경계 보류, solver UNKNOWN은 0개였다.

리뷰 중 존재 후보를 단일 실패로 채점하던 harness 오류를 고쳤다. 생성 baseline은
양화사를 보존하고, 의도적 unsafe 정책만 별도 ablation으로 유지한다. 원문 상태
필드 누락, witness 용어, 시간 receipt 연결, oracle의 자원 상한도 수정했다.
정답 내용과 frozen LLM 출력은 변경하지 않았다. [검토 기록](C1_REVIEW.md).

초기 16개 기존 테스트 setup 오류와 추가 평가의 임시 폴더 오류는 환경 제한이었다.
workspace 임시 경로 지정으로 해결했고 해당 원인으로 소스를 바꾸지 않았다.
빌드의 임시 경로 오류도 같은 방식으로 해결했다. sdist/wheel 빌드 및 별도
wheel 설치·의존성·demo·claim·replay 검사를 통과했다. runtime 10개, package
version, README, 기존 tests/examples와 공개 태그는 그대로다. 기존 파일 변경은
새 연구 모듈·JSON이 sdist에서 빠지지 않게 한 `MANIFEST.in`의 1줄뿐이다.
새 버전이나 릴리스를 게시하지 않는다.

## 봉인, 남은 UNKNOWN과 다음 실험

미사용 v2 자료 12건 / 1개의 별도 개념 family는 비공개 archive로 보존하며 공개에는
[nonce 포함 commitment](../../research/c1/fixtures/holdout_commitment.json)만 둔다.
평가 0회다. 초기 v1도 보존했다. v2는 preliminary dev 관측 뒤 설계를 고친
prospective 자료이므로 사전 등록된 확인 평가라고 주장하지 않는다.

남은 핵심 UNKNOWN은 인간 의도와 anchor의 일치, 새로운 family에서의 효과,
비합성 실제 요구사항, 강한 외부 시스템 대비 성능, 무한 시간·확률·실수 영역,
Jev의 독립 판단 및 탐사 우선순위 기여다. curated 27건/LLM 6건의 보류 원인은
JSON에 case별로 남겼다.

다음 우선순위는 (1) 인간이 원문/anchor를 독립 판정한 disjoint family 자료,
(2) frozen prompt로 외부 모델별 직접 생성/자기검토와 같은 O의 paired gate,
(3) Monty·BPF·SAE 계열 도구 또는 외부 test oracle의 재현 가능한 대조,
(4) 동일 예산 Jev on/off 사전 등록이다. 이번에는 Jev 실 API를 호출하지 않았다.

가장 강한 반론은 참조 C를 제공받은 작은 합성 문제에서 gate가 이기는 것은
당연하다는 것이다. 맞다. 이번 결과는 그 **제한된 오류 기제**를 구현·검사한
기반이며, LLM의 일반 의미 정확성 또는 실제 허위 버그 감소를 입증한 결과가 아니다.
