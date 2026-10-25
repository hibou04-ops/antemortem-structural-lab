# Phase C1 선행연구와 연구 경계

조사 기준일: 2026-10-26 (Asia/Seoul). 아래는 1차 출처의 관련 절을 읽고 정리한 연구 지도다. 논문별 성능 수치는 저자 보고이며 재현하지 않았다. 서로 다른 자료·모델·판정 기준의 수치를 순위표로 합치지 않는다. 이 조사는 최고 성능의 전 분야 완전 검색이나 C1의 독창성 증명이 아니다.

**핵심 판단 — INFERENCE [82%]:** 의미가 다른 명세를 정확히 검증하는 문제, 양방향 함의 검사, 모호함의 보류, 독립 평가와 최소쌍은 이미 선행연구의 중심 주제다. C1의 정당한 첫 실험은 이 개념들의 발명이 아니라, 명시된 유한 계약에서 **의무의 실패가 원래 주장의 반증으로 잘못 승격되는 비율**을 낮추는지 분리해 측정하는 것이다.

## 확인된 사실, 가정, 미지수

- FACTS: 아래 연구는 검증 성공과 의미 충실도를 구별하며, Anthropic 연구는 실제 잘못된 버그 보고와 의도 모호함을 보고한다. C1은 이를 무시한 새 번역기·퍼저로 시작할 근거가 없다.
- ASSUMPTIONS: 초기 C1에서는 생성 역할과 분리된 평가 역할이 참조 predicate, 변수의 역할, 전제와 입력·시간 영역을 수작업으로 구성한다. 이번 인간 검토는 0건이며 역할 분리는 외부 인간 검토나 통계적 독립성을 뜻하지 않는다. 이것은 **자연어 의미가 자동으로 해결됐다는 가정이 아니다**.
- UNKNOWNS: 일반 자연어에 대한 참조 계약의 정확성, 독립 인간 평가와의 일치, 신뢰 구간이 좁아질 만큼 큰 미사용 자료에서의 효과, 강한 외부 시스템보다 나은지, LLM 직접 생성·자기검토가 실제로 만드는 오류 분포는 이번 구조 실험만으로 정해지지 않는다.

## 직접적인 중복과 차이

각 행의 사실 신뢰도는 출처에서 방법을 확인했다는 의미이며, 저자 성능 주장의 독립 검증을 뜻하지 않는다.

| 연구·읽은 버전 | 확인한 방법과 C1 중복 | C1에서의 제한과 재사용 판단 |
|---|---|---|
| **BEq+ / Reliable Evaluation and Benchmarks for Statement Autoformalization**, arXiv:2406.07222v3, 2025-10-29, EMNLP 2025. CONSENSUS [91%] | 참조 Lean 문장과 후보 사이의 symbolic proof 기반 평가. ProofNetVerif는 3,752 annotated pairs. 컴파일 성공만으로 의미 정확도를 판단하지 않는다. Appendix A.6은 서로 다른 참 명제의 사소한 증명으로 발생하는 false positive와 proof search 부족의 false negative를 설명한다. [원문](https://arxiv.org/html/2406.07222v3) | 참조 기반 독립 판정은 직접 중복이다. C1은 열린 predicate의 동일 변수·역할·유한 영역을 고정해야 한다. Lean으로 범위를 넓힐 때 CPU proof 기반 대조군 후보이며 이번 실행 결과로 가장하지 않는다. |
| **FormalAlign**, arXiv:2410.10135v1, 2024-10-14; ICLR 2025 공개본도 확인. CONSENSUS [90%] | 생성 loss와 representation alignment loss를 함께 학습한 reference-free semantic alignment 평가. 양성·의도적 misalignment 자료로 학습·평가하며 compiler와 LLM judge를 대조한다. [원문](https://arxiv.org/html/2410.10135v1), [ICLR 공개본](https://eleanor-h.github.io/publication/2024-lu-formalalign/2024-lu-formalalign.pdf) | semantic score는 bounded implication certificate와 다르다. 학습 평가기의 출처 분리·분포 이동·calibration을 기록해야 한다. C1 논리 gate가 자연어 자체를 판정한다는 근거로 사용하면 안 된다. |
| **The Faithfulness Gap / BPF**, arXiv:2606.16541v1, 2026-06-15, preprint. INFERENCE [84%] | forward/backward consequence fingerprint, counterfactual drift probe와 twin, probe budget allocation, unknown proof query를 사용한다. DriftBench는 저자 보고 2,183 NL/Lean pairs다. §8의 보장은 probe witnessability와 선택 probe에서의 complete entailment oracle을 전제한다. §12는 원문 모호함·probe label correctness를 인증하지 않는다고 명시한다. [원문](https://arxiv.org/html/2606.16541v1) | **양방향 함의 + 적대적 최소쌍 자체는 차별점이 아니다.** C1은 정해진 유한 모델에서 직접 함의 반례와 영역 증거를 반환하는 좁은 실험으로 설명한다. 이 논문의 인증 표현이나 성능을 자연어 전체에 대한 무조건 보장으로 인용하지 않는다. |
| **Monty / Faithful Autoformalization of Natural Language Assertions**, arXiv:2607.13303v2, 2026-07-16, preprint. CONSENSUS [92%] | 실행 validity와 NL-formal conformance를 분리하고, roundtrip·bidirectional clausal coverage 점수와 active learning을 결합한다. 22 Java classes의 541 tasks. §6에서 direct generation, conformance ablations, precision/recall을 구분한다. §3–4는 입력이 assertion의 참을 보장한다고 가정하지 않고 valid/invalid 후보를 함께 고려한다. [원문](https://arxiv.org/html/2607.13303v2) | C1의 실패한 의무/부정확한 의미를 분리하는 목표와 매우 가깝다. 차이는 LLM conformance 점수 대신 검토된 유한 reference 아래 strict necessary/sufficient/incomparable와 결론 승격 gate를 측정하는 것. Monty precision을 C1 수치와 바로 비교할 수 없다. |
| **SAE / ACE — Structure-Aware Equivalence for Evaluating Autoformalized Statements**, arXiv:2610.25018v3, 2026-10-22, preprint. INFERENCE [84%] | whole-statement logical equivalence가 무관한 참 정리를 같게 만들 수 있음을 지적하고, binder correspondence·premise/conclusion 역할·relational structure를 보존한다. certificate가 없으면 Inconclusive. §5는 normalization/alignment와 bounded proof search의 한계를 명시한다. [원문](https://arxiv.org/html/2610.25018v3) | 최신의 강한 직접 반론이다. C1의 `EQUIVALENT`는 지정된 열린 predicate 모델의 동치다. 원문 전체의 linguistic fidelity로 확대하지 않는다. 전제/결론 역할이나 변수 대응이 검증되지 않으면 보류한다. 향후 reference evaluator 대조군으로 유력하나 Lean integration은 별도 실험이다. |
| **Validating Autoformalized Specifications via Contrapuntal Languages**, arXiv:2610.30059v1, 2026-10-21, preprint. INFERENCE [83%] | 독립적으로 서로 다른 task-specific formal languages에 formalize하고 solver가 두 결과의 동치를 증명할 때 수용한다. 같은 모델의 반복 합의도 correlated mistakes일 수 있다는 문제를 다룬다. §7은 behavioral evaluation의 sound/complete 판단이 테스트한 행동에만 상대적이라고 명시한다. [원문](https://arxiv.org/html/2610.30059v1) | 독립 판단·solver gate의 조합은 이미 존재한다. representation diversity ablation은 C1 후속 후보다. 다른 생성 경로가 일치해도 원문 의도까지 보장되는 것은 아니다. 논문도 모호함 해결에 requirement author 확인이 필요하다고 설명한다. |
| **SpecGen**, arXiv:2401.08807v5, 2025-02-25. CONSENSUS [90%] | Java program에서 대화형 LLM·verifier feedback·명세 mutation을 사용하여 verifiable specification을 생성한다. 저자 보고 385 programs 중 279 성공. [원문](https://arxiv.org/html/2401.08807v5) | 구현을 잘 설명하는 명세를 찾는 것과 독립 원문의 반증 권한은 다르다. 잘못된 구현을 따라 명세를 약화하면 verifier 통과와 의도 보존이 갈라진다. feedback repair를 쓸 때 원문 계약은 고정해야 한다. |
| **Automatic Generation of Formal Specification and Verification Annotations Using LLMs and Test Oracles**, arXiv:2601.12845v1, 2026-01-19, preprint. CONSENSUS [89%] | TESTDAFNY110의 110 programs에서 NL comments·tests·Dafny verifier로 annotation을 생성·수정한다. static test assertion을 method body 대신 pre/postcondition만으로 검증하여 약한 명세를 탐지한다. [원문](https://arxiv.org/html/2601.12845v1) | 별도 test oracle이 약한 명세를 잡는 좋은 대조다. 유한한 test oracle 통과는 전체 의도 동치의 증명이 아니다. C1에서 `O 통과`와 `C 입증`을 분리해야 하는 근거다. |
| **Can LLMs Write Correct TLA+ Specifications?**, arXiv:2606.05792v1, 2026-06-04, preprint. INFERENCE [82%] | TLA+ Examples에서 205 specifications를 수집하고 project 단위로 분할한다. usable test는 26. SANY syntax와 TLC checking을 구분한다. [원문](https://arxiv.org/html/2606.05792v1) | 상태 전이의 도구 baseline은 TLC 같은 기존 모델 검사기를 재사용할 수 있다. TLC가 지정된 모델·설정에서 요구 속성을 만족하는 것과 NL 원문을 모두 보존하는 것은 다른 gate다. 논문의 `semantic correctness`는 그 실험의 operational definition으로 읽는다. |

## PBT-Bench와 Anthropic 연구를 구별해야 하는 이유

**PBT-Bench — CONSENSUS [93%].** 최신 확인본은 arXiv:2605.15229v4 (2026-10-06)다. 100 problems / 40 Python libraries / 365 injected semantic bugs를 사용한다. 문서에서 invariant와 target input strategy를 도출하며, agent container와 독립 eval container에서 bug별 fail-to-pass로 발견 여부를 평가한다. baseline과 PBT prompt의 차이는 모델의 절대 능력 순위가 아니라 scaffold 진단으로 설명한다. v4는 `.orig` 누출과 별도 harness 종료 결함·제외·재채점도 공개한다. [방법·construct validity·integrity 원문](https://arxiv.org/html/2605.15229v4)

**차이 — INFERENCE [83%].** PBT-Bench는 문서에 근거한 숨은 버그 발견과 알려진 주입 버그 recall을 측정한다. C1은 *후보 의무를 실패시킨 결과를 원래 주장에 올려도 되는지*를 측정한다. F→P는 잘못된 속성으로 인한 허위 버그를 줄이는 강한 통제지만, F→P 자체가 원문 의미와 동치라는 논리 증명은 아니다. C1은 PBT-Bench 대체재나 개선판으로 홍보하지 않고, 향후 외부 복잡도 평가 대상으로 남긴다. 현재 C1 합성 자료는 PBT-Bench 행을 가져왔다는 뜻이 아니다.

**Anthropic / Agentic PBT — CONSENSUS [94%].** 2025-10-10 paper v1은 100 popular Python packages의 실제 bug finding을 다룬다. 코드를 읽고 속성을 제안한 뒤 Hypothesis 테스트·반영·보고를 반복한다. 저자 수동 검토에서 보고의 56%가 valid bugs였으며, §5는 모든 984 reports를 검토하지 않았고 intentional behavior와 bug를 구분하지 못하는 intent ambiguity를 한계로 둔다. `LookupDict`가 이름·상속만 보고 dict처럼 동작해야 한다고 추론한 사례와 Julian calendar 사례는 C1 오류 유형에 직접적이다. [paper](https://arxiv.org/html/2510.09907v1)

2026-01-14 Anthropic 연구 글은 self-reflection과 문서 grounding, 높은 우선순위 결과의 전문가 검토를 설명한다. 생성한 property가 실패했다는 이유만으로 버그를 확정한 접근이 아니다. [Anthropic 연구 글](https://www.anthropic.com/research/property-based-testing)

## C1에서 고정할 판정 의미

**AXIOM [99%]:** 같은 해석과 영역에서 `A ⇒ (C ⇒ O)`이면 `A ∧ ¬O`는 `¬C`를 함의한다. 반대로 `A ⇒ (O ⇒ C)`만 있으면 의무 실패를 주장 실패로 올릴 수 없다. 필요조건·충분조건 명칭은 **O가 C에 대해 어떤 조건인가**를 기준으로 고정한다.

| 관계 | 방향 | O 실패에서 C 반증 | O 성공에서 C 입증 |
|---|---|---|---|
| EQUIVALENT | C⇒O 및 O⇒C | 유효 반례와 적용 영역을 확인한 경우 가능 | 해당 양화사·완전 증거 범위에서 가능 |
| NECESSARY | C⇒O만 | 위 조건에서 가능 | 불가 |
| SUFFICIENT | O⇒C만 | 불가 | 완전한 O 증거와 적용 영역에서 가능 |
| INCOMPARABLE | 양쪽 모두 아님 | 이 관계만으로 불가 | 이 관계만으로 불가 |
| AMBIGUOUS | C 해석이 미확정 | UNKNOWN | UNKNOWN |
| OUT_OF_SCOPE | 지원 논리·영역 밖 | UNKNOWN | UNKNOWN |

`C`와 `O`가 이미 양화된 닫힌 문장인지, 입력별 predicate인지 고정해야 한다. 보편 명제에는 유효한 한 반례가 충분하지만, 존재 명제에는 실패한 한 입력이 충분하지 않다. finite exhaustive proof는 표시한 domain과 horizon에만 유효하다. bounded transition safety 결과를 unbounded temporal liveness로 올리지 않는다. 전제가 모순이면 공허한 함의가 성립하므로 `assumptions_consistent=false`는 결론 승격을 막아야 한다.

**리스크 — INFERENCE [84%]:** 이 gate가 완벽해도 reference contract가 원문을 잘못 해석했다면 같은 오류를 정확히 인증할 수 있다. 따라서 초기 성과는 “검토된 계약에서 잘못된 승격 감소”이며 “자연어 의미 정확도 해결”이 아니다. SAE의 반론을 받아 변수 역할·premise/conclusion·exception·time 해석을 계약에 보존하고 참조 작성자와 생성 후보 작성자를 구분한다.

## 가능한 두 경로와 이번 권고

1. **유한 계약 + 직접 권한 검사:** 제한된 정수·불리언·짧은 상태 trace에서 exhaustive model checking 또는 SMT로 A의 일관성, 두 함의, witness의 domain을 검사한다. 장점은 원인과 반례가 감사 가능하다는 점이다. 약점은 사람이 제공한 참조 해석에 대한 조건부 결과라는 점이다. **이번 권고, INFERENCE [83%].**
2. **범용 NL 생성 + learned/probe/representation-diverse 평가:** Monty, FormalAlign, BPF, contrapuntal validation 같은 강한 기존 방법을 연결한다. 적용 폭은 넓지만 오염·비용·공유 오류·인간 정답 품질 때문에 초기 오류 감소의 원인을 분리하기 어렵다. **후속 비교 후보, INFERENCE [77%].**

가장 강한 반론은 1번이 정답 계약을 이미 제공받은 쉬운 문제라는 것이다. 타당하다. 이 실험은 NL 해석 난도를 해결했다고 주장하지 않는다. 역할은 **의미 관계를 알고도 결과를 잘못 승격하는 판정 오류가 실제로 존재하며, 그것을 얼마나 줄일 수 있는지** 먼저 측정하는 것이다. 1번이 실패하거나 단순한 결론 정책과 차이가 없다면 범용 생성으로 확장할 근거가 약해진다. 반대로 주된 오류가 참조 해석에서 발생한다면 2번의 독립 표현·요구자 확인 실험이 우선이 된다.

## 기준선과 오염 통제 권고

- C0 template는 기존 구현으로 실제 생성한 결과만 C0라고 부른다. 새 heuristic을 만든 경우 별도 이름과 출처를 준다.
- 일반 LLM 직접 생성과 동일 후보의 LLM self-review는 별도 receipt를 보존한다: model/revision, prompt hash, 원시 응답 hash, sample index, seed/temperature 설정, input/output tokens, 실제 또는 UNKNOWN 비용, 시간, 실패/timeout. 실행하지 않은 칸은 `NOT_RUN`이다. 사람이 만든 proxy를 LLM 성능으로 표시하지 않는다.
- 논리 authority 방식은 **동일 생성 후보**에 적용해 관계·승격 gate의 기여를 paired comparison한다. oracle reference를 LLM baseline에만 숨기고 checker에 제공했다면 정보 비대칭도 명시한다.
- 평가 정답은 후보 생성기·코어 평가기와 분리된 truth table/전이 명세에서 작성한다. 별도 에이전트 검토는 같은 시스템/작업공간이라면 외부 인간 독립성과 동등하지 않다.
- family와 최소쌍은 split 경계를 넘지 않게 한다. 미사용 평가 자료는 private artifact로 봉인하고 공개 저장소에는 salted commitment·count·protocol만 둔다. 작은 Boolean 자료는 단순 hash만으로 비밀성을 주지 못하므로 salt도 비공개로 보존한다.
- `false REFUTED / all REFUTED`와 `false REFUTED / non-refutable cases`를 구분한다. valid counterexample recall, relation accuracy, UNKNOWN recall/precision·selective coverage, cost/time를 각각 보고한다. 전건 UNKNOWN으로 false REFUTED를 줄이는 방식은 성공이 아니다.
- Jev는 네트워크 호출 없이 `NO_JEV` 조건을 유지한다. 향후 독립 판단·탐사 우선순위·비용의 ablation은 동일 후보/동일 예산 paired run으로 설계한다.

## 이번 조사로 결정하지 않은 것

외부 논문 코드를 설치·실행하거나 benchmark 원자료를 복사하지 않았다. 논문 수치를 C1 실험의 재현 결과로 사용하지 않는다. 전체 prior art에 대한 우월성, 사람 의도에 대한 자동 인증, 임의 코드의 안전 실행, 비유한 수학·실수·확률·실시간·무한 trace 지원은 미검증이다. Firecrawl 검색은 계정 credit 부족으로 실행되지 않아 웹 검색·원문 열람으로 전환했다. 검색 질의에는 공개 연구 주제만 사용했다.
