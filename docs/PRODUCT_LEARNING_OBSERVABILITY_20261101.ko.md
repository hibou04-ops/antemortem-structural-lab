# 기존 E9-R1 경험 경로와 한계 기여의 관측 가능성

작성일: 2026-11-01 (Asia/Seoul). 이번 작업은 기존 코드와 보존 JSON의 읽기 전용 분석이다. Source 수집, Mold 재학습, 연구 Target/Oracle 호출, 384회 비교 재실행은 모두 0회다.

**핵심 판단 — 기존 D는 제한된 구조 슬롯에서만 개입한다. 그러나 현재 Source 학습 입력은 공통 후보 대비 개입의 추가 기여를 직접 가르치지 않는다.** 같은 상태로 대응 가능한 기존 실행 55개에서 국소 이득 0, 손실 8, 상태값 차이 없음 47을 확인했다. 나머지 185개는 같은 상태의 대응 결과가 없어 UNKNOWN이다. 이는 해당 기록의 제한된 진단이며 typed edit 가설족 전체의 반증이나 미래 효용 부재 증명이 아니다. 이 해석의 신뢰는 `INFERENCE [80%]`이며, 원본 필드·집계는 아래 직접 대조 범위로 제한한다.

## 1. 원문·출처와 보존

서로 다른 세 revision을 구분한다.

- 연구 실행 구현: `6cbe985e77c482cda6413250a9a270924e648c0d`.
- 보고서 동결: `591f802dea6f8ac88a27af3ffd89bd6e1396b318`의 `docs/HISTORICAL_REPORT_KO.md`, `HISTORICAL_PROFILE.json`, `HISTORICAL_RESULTS.json`.
- 이번 제품 시작점: `3ece4df3bd01abe6aae58ef8a01bf4b01515f689`.

실행 revision과 제품 시작점의 `online_engine.py`, `online_learning.py`, `online_mold.py`, `online_observe.py`를 비교했다. 네 파일의 차이는 공개 `run_online` 기본 방법이 C에서 A로 바뀐 한 줄뿐이며, 아래 분석한 제어·학습 경로는 같다. 이 제품 기본값을 과거 연구의 실행 방법으로 소급하지 않았다.

직접 읽은 보존 자료는 기존 복호화 디렉터리의 `results.json`, `prepared.json`, `registration.json`, `results.public.json`, `events.jsonl`이다. `events.jsonl`은 run 단위 JSONL이며 `results.json.runs`와 함께 보존돼 있다. 이번에는 `results.json`의 전체 384 run과 `prepared.json`의 88 Source record를 파싱했다. 원본 다섯 파일의 분석 전후 SHA256이 일치했다. 원시 입력·Oracle 출력·개인 경로는 이 문서와 공개 PR에 복사하지 않았다.

| 원본 파일 | SHA256 |
|---|---|
| `results.json` | `d1cdea50e8a0fb9ea7459c346971f3b63b4f6ca61b22694669756e83e98a25e7` |
| `prepared.json` | `c6159e46e4dd2c738c7c85f388da128e7ac05a192fd4a4961e361d27b9fc42eb` |
| `registration.json` | `f33eb29eb0c3a56eaae1300d80ddf867e14d3b86fe4419bce750d3f248e0eb5a` |
| `results.public.json` | `13e214974bd826181fc897d543b056b7b576521d02cded605fc5d65b2aa955b3` |
| `events.jsonl` | `4ed73eafc458f9defe57844998be074266d32f657b1472babd7fcced4944e89b` |

`HISTORICAL_RESULTS.json.raw_results_sha256`가 위 `results.json` SHA와 일치한다. 384 run의 정체성·상태·탐지·Target/Oracle 호출·비용·scheduler·오류·새 입력·중복 필드와 전체 summary를 원시 결과와 대조해 일치함을 확인했다. 공개 보고서 JSON은 원시 payload를 축약한 별도 형식이므로 파일 자체의 byte hash가 원시/중간 공개 JSON과 같아야 한다고 가정하지 않았다.

원격 artifact ZIP `13047714141`의 신규 다운로드·복호화·ZIP byte 재검증은 이번 분석에서 하지 않았다. 기존 공개 보고서에 기록된 ZIP SHA는 과거 인계 증거이며 이번 새 원격 readback으로 표현하지 않는다. 로컬 원시 자료는 접근 가능했고, 아래 UNKNOWN의 주원인은 파일 접근 실패가 아니라 대응 관측 부재다.

## 2. D의 정확한 제어와 계수 단위

근거: [온라인 정책](../tomolab/discovery/online_engine.py), 특히 `OnlinePolicy.__init__` 28–40행, `propose` 157–181행, `_guided_structure_choice` 113–155행, `search` 286–319행, `confirm` 256–281행, scheduler 392–412행. 줄 번호는 제품 시작점 기준이다.

| 단위 | 실제 동작 |
|---|---|
| 후보 제안 | `propose(base)`마다 `attempts`가 증가한다. `(attempts-1)%10`의 0·1은 replay 후보 슬롯, 2·3·4는 구조 후보 슬롯이다. 거절·중복으로 실행되지 않아도 제안 횟수는 이미 증가한다. |
| replay 상한 | `policy_budget // 5`. C/D만 승인된 replay를 받는다. `used.replay + 3 <= cap`일 때만 replay 슬롯을 사용한다. |
| 구조 상한 | `3 * policy_budget // 10`. A를 제외한 B/C/D가 공통 구조 경로를 쓴다. `used.structure + 3 <= cap`일 때만 사용한다. D만 그 슬롯의 제안자를 바꾼다. |
| 실제 예산 | `policy_budget = total_budget - shrink_budget`. 과거 총예산24·축소6이면 발견18, replay3·structure5다. 총48·축소6이면 발견42, replay8·structure12다. 이 값은 새 실험 예산의 근거가 아니다. |
| 실제 호출 | `evaluate`가 host 영수증의 `target_calls`/`oracle_calls`를 각각 더한다. 제안 수, Hypothesis example 수, 실제 호출 수는 같지 않다. |
| 확인 | 초기 FAILURE 뒤 같은 입력을 추가 2회 실행하여 semantic digest가 일치해야 확인된다. 추가 확인 호출은 원래 lane의 `used`에 청구한다. 실제 예산 검사는 worker와 host 양쪽에 있다. |
| 축소 | 별도 예약된 축소 예산 안에서 native/delta shrink와 최종 2회 확인을 수행한다. 총 호출 예산에 포함하며 native predicate의 중복 cache hit는 새 호출이 아니다. 불완전 축소를 최소성 증명으로 표시하지 않는다. |

D는 먼저 **C와 동일한 공통 후보를 계산**한다. Mold 없음, 적용 규칙 없음, 실행 불가, invalid 결과, 이미 본 결과에서는 그 공통 후보로 돌아간다. 손상된 Mold는 예외이며 정상 fallback으로 숨기지 않는다. 선택된 학습 스크립트를 실행하고 입력 계약에 맞으며 이미 본 입력이 아닐 때만 실제 후보를 교체한다. 공통 후보와 같은 유효 결과도 `APPLIED`일 수 있으므로 `learned_valid_proposals`와 `learned_changed_common_executions`를 구분해야 한다.

규칙 조회에는 seed에서 별도로 만든 `rule_rng`를 사용한다. 공통 편집의 RNG를 소비해 fallback 경로가 달라지도록 만들지 않는다. 따라서 “D가 전체 예산의 후보를 무조건 덮어쓴다”, “fallback/스케줄/RNG 분리가 없다”는 설명은 코드와 다르다. 반대로 유효성·중복 검사는 그 편집이 공통 후보보다 유용한지 검사하지 않는다.

## 3. native 입력·anchor·후보의 정체성

실제 호출 순서는 다음과 같다.

```text
native_candidate = Hypothesis가 이번에 공급한 base
anchor = archive의 최근 FAILURE 입력; 없으면 최근 관측 입력;
         archive도 없으면 native_candidate
common_candidate = checked(common_edit(copy(anchor), target_MRI))
learned_candidate = learned_edit_1/2(copy(anchor), target_MRI)
D 선택 = 유효하고 중복 아닌 learned_candidate, 아니면 common_candidate
```

`checked`에서 공통 편집이 무효/중복이면 `common_candidate`는 원래 native 후보로 돌아갈 수 있다. 따라서 native 후보, archive anchor, 검증 후 공통 후보를 같은 `base_candidate` 변수 하나로 설명하면 잘못된다. 현재 알고리즘은 `learned_edit(anchor)`와 `common_edit(anchor)`의 대안 선택이다. `learned_edit(common_edit(anchor))`로 바꾸면 별도 알고리즘 변경이다.

학습 시 `learn_mold`는 같은 Source 정체성·입력 계약의 실제 PASS 입력을 기준으로 공통 연산자 1/2개를 적용하고, 그 결과 입력이 실제 기록된 안정적 FAILURE/PASS인지 조회한다. 충돌한 반복 라벨과 오류/UNKNOWN은 부정 사례로 강제 변환하지 않는다. 학습의 `_apply`는 MRI 인자를 넘기지 않는다. 적용 시에는 새 Target의 MRI를 `apply_edit`에 넘기므로 동일 연산자도 `boundary`/`append`의 pivot 등이 Target 공개 literal의 영향을 받을 수 있다. 이는 Source의 원시 값을 복사하는 규칙이 아니며, 학습 입력과 적용 anchor가 같은 역할이라고 보장하지 않는다.

근거: [학습](../tomolab/discovery/online_learning.py) 34–46, 94–153행; [공통 편집과 MRI pivot](../tomolab/discovery/online_schema.py) 193–264행.

## 4. MRI와 세 종류 점수

MRI는 AST의 분기·반복 위치, 호출 이름, 상수, 대입 위치, 읽는 이름을 기록한다. 일반 Python 의미 해석이나 path predicate를 구축하지 않는다. 비교 distance를 `SUPPORTED`로 표시하는 범위는 단일 builtin 정수/실수 인자와 숫자 literal 사이의 단일 `==`, `!=`, `<`, `<=`, `>`, `>=` 비교다. 실제 distance는 각 지원 literal까지의 `abs(input-literal)` 최솟값으로, 분기 방향별 참/거짓 distance가 아니다. adapter가 원래 인자로 어떻게 매핑되는지 모르면 해당 비교를 UNKNOWN으로 낮춘다.

`len(xs) == 0`은 비교의 왼쪽이 단순 입력 이름이 아니어서 의미 distance가 UNKNOWN이다. `if not xs`는 분기 위치만 기록하며 “빈 입력을 유지하라”는 정책 predicate가 되지 않는다. `is_boundary_critical`/`destroys_boundary`는 현재 경로에 구현돼 있지 않다.

Mold 전제조건은 `size_class`, `all_equal`, `has_negative`뿐이다. 학습 PASS 입력에서 `_features`를 계산하고 Source 반증을 실제로 제외하는 제한을 고른다. 적용 때는 **anchor**의 `_features`와 비교한다. MRI 의미 문맥을 이 전제조건에 직접 결합하는 필드는 없다. MRI는 모든 방법의 native 전략과 편집 실행에 공통 prior로 들어간다.

| 점수 | 계산과 한계 |
|---|---|
| local operator reward | 초기값1에 `FAILURE` 여부와 **이번 coverage가 비어 있지 않은지**를 더한다. 새 line 획득의 차집합을 계산하지 않으며 유용한 Source 개입의 한계 기여 점수도 아니다. |
| Hypothesis 탐색 점수 | `len(current_coverage) + 1/(1+distance)`이다. 현재 호출의 root-line 수와 단순 literal 근접도다. 전체 방문 coverage나 새 coverage 증가분과 다르다. |
| Mold 지지·반증 | 기록된 PASS→편집 결과의 쌍과 적용 가능한 반증을 세어 `support/(support+applicable_counterevidence+1)`로 순위를 정한다. 공통 정책이 같은 상태에서 실패를 이미 찾았는지 빼지 않는다. |

근거: [MRI와 관측](../tomolab/discovery/online_observe.py) 28–108, 220–226행; [온라인 점수·보상](../tomolab/discovery/online_engine.py) 73–86, 184–186행; [Mold 특성](../tomolab/discovery/online_mold.py) 22–44, 126–140행; [학습 순위](../tomolab/discovery/online_learning.py) 160–195행.

## 5. 같은 상태의 국소 대응 결과

사용한 외부 run 키는 `(evaluation, fold, case.id, seed, budget)`다. C/D의 `case` 전체 metadata(구현·Oracle SHA 포함), `result.contract`, MRI, routing이 모두 일치하는 96 run 쌍만 사용했다. 분석 분모는 그중 D의 `rule_id`가 있고 `source_selection.source_changed_common=true`인 실제 실행 이벤트 240개다. 확인·축소 이벤트를 새 제안으로 중복 계수하지 않았다.

엄격한 국소 대응 키는 다음과 같다.

```text
C.common_policy_state_before == D.common_policy_state_before
C.base_input_digest == D.base_input_digest
C.feedback.input_digest == D.source_selection.common_candidate_digest
```

각 검색 이벤트의 `observation_id`/`index`, `phase`, `operator`, `rule_id`, `feedback.status`, `feedback.input_digest`, `source_selection`, 앞뒤 policy digest가 존재한다. `common_policy_state_before`는 계약, 공통 RNG, archive, 직전 feedback, lane cap/used, attempts, operator reward, seen을 묶는다. method/Mold·rule RNG·조회 통계는 의도적으로 제외한다. anchor는 이벤트의 별도 필드로 저장되지 않는다. 같은 공통 상태와 같은 native 입력, 같은 결정적 구현이면 해당 슬롯에서 anchor가 같다는 코드상 추론이 가능하지만 전체 상태 snapshot을 복구하는 필드는 아니다.

| 평가 | D의 다른 후보 실제 실행 | 국소 이득: C PASS / D FAILURE | 국소 손실: C FAILURE / D PASS | 상태값 차이 없음 | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| 구현 전이 | 128 | 0 | 0 | 31 | 97 |
| EMPTY LOMO | 112 | 0 | 8 | 16 | 88 |
| 합계 | 240 | 0 | 8 | 47 | 185 |

47개 중 41개는 양쪽 PASS, 6개는 양쪽 FAILURE다. “중립”은 이진 상태가 같다는 뜻이며 입력·시간·후속 경로가 같다는 뜻이 아니다. 8개 손실은 windowed와 accumulate 각각 seed4201·4211, 예산24·48의 한 슬롯이다. 모두 C의 `delete` 실패 후보를 D의 `append` 정상 후보가 대체했다. 이는 **2개 고유 역사 결함, 1개 기전군, 2개 프로젝트의 반복 슬롯 관측 8개**이며 독립 결함 8개가 아니다. 기존 대표 사례의 기전을 더 많은 기존 로그에서 확인했지만 전체 미검출의 유일한 원인으로 일반화하지 않는다.

UNKNOWN185개를 추가로 나누면 다음과 같다.

| 관측 범주 | 수 | 해석 |
|---|---:|---|
| 같은 상태와 두 후보 결과를 실제 대응 | 55 | 위 표의 0/8/47. |
| 같은 C run의 다른 상태에서 공통 입력 결과를 관측 | 49 | 입력 단위 두 결과는 존재하나 같은 상태의 개입 대응이 아니다. 강한 pure/deterministic 가정을 추가하면 상태값상 손실2·차이없음47이며 이득0이다. 엄격한 국소 표에는 합치지 않았다. |
| 대응 C/D run에서 공통 후보 입력 결과를 관측하지 못함 | 136 | D 결과만 있다. 누락 결과를 실행하거나 다른 계약·구현의 라벨로 채우지 않았다. |
| 파일 접근 실패 | 0 | 이번 분모를 만드는 원시 파일은 접근 가능했다. 원격 ZIP 신규 readback 부재는 별도로 위에 적었다. |

서로 다른 예산/seed/run의 입력 일치까지 확장해 전수 반사실 표를 만들지 않았다. 실제 Target/Oracle가 입력 외 숨은 상태에 의존하면 입력 digest만으로 결과를 옮길 수 없다. 기존 계약은 reviewed pure/reset adapter를 요구하고 해당 역사 함수의 adapter는 그 가정에 맞춰 작성됐지만, 이번에는 재실행으로 결정성을 새 검증하지 않았다. 공통 hash는 Hypothesis 내부 탐색 상태를 포함하지 않으므로 한 슬롯의 결과가 같아도 이후 모든 후보·호출을 복원하지 못한다.

## 6. 정책 수준 비교와 학습 가능성의 경계

기존 실제 정책 결과는 별도로 보존한다. buggy Target seed run 기준 구현 전이는 두 예산에서 A/B/C/D 모두 15/18, 고유 결함5/6이었다. bytes2human은 전 방법 미검출이다. EMPTY LOMO는 예산24에서 A/B6/6, C4/6, D0/6이고 예산48에서 A/B/C6/6, D0/6이다. C/D 공동 탐지30쌍의 최초 확인 호출은 같았다. 고정된 실제 정책 비교에서 추가 발견 이득이 관측되지 않았다는 결론과, 누락된 모든 국소 반사실 결과를 알 수 없다는 결론은 함께 성립한다.

Source 실제 호출은 Target/Oracle 각각88회였고 `prepared.records`도88개다. 보존 source run은 interpose43회, bucket45회다. learner의 실제 입력 필드는 `input`, `status`, `contract`, `source_identity`, `source_axis`, `source_mechanism`, `source_project`, `input_digest`이며 `_clean_observations` 뒤에는 입력·상태·계약·출처/관측 digest만 남는다. ALL의 기록 편집 지지쌍9개에서 규칙3개, EMPTY Source 제외45개 기록의 지지쌍2개에서 규칙2개를 얻었다. 이는 공통 정책 대비 추가 기여 라벨9/2개가 아니다.

현재 학습 입력에는 slot, archive anchor, 공통 상태, 선택된 common/learned 후보의 동시 결과, 공통 정책의 기존 탐지 여부가 없다. 따라서 `support_without_baseline_hit`를 **동일 상태에서 공통 탐색이 놓친 실패를 학습 개입이 찾은 수**로 정의한다면 현재 `learn_mold(observations)` 입력에서 일반적으로 산출할 수 없다. 단순히 D 실패 입력이 C의 입력 목록에 없다는 novelty를 이 점수로 대체하면 의미가 달라진다. 기존55쌍도 평가 자료를 읽은 개발 진단으로 소비되었으므로 새 블라인드 학습/평가 표본으로 재사용할 수 없다.

가능한 다음 경로는 (a) 현행 정책을 고정한 채 같은 anchor에서 common/learned 결과를 쌍으로 계측하거나, (b) 현재 지지점수만으로 곧바로 gate를 학습하는 것이다. 현재 Source 정보는 (b)의 추가 기여 정답을 제공하지 않으므로 (a)가 더 작은 식별 단계다. 반론은 pure Target의 기존 입력 라벨을 더 넓게 재사용하면 추가 계측을 줄일 수 있다는 것이다. 그런 재사용은 관측된 입력에 한해 비용을 절약할 수 있지만, 결정성·reset 조건을 명시하고 누락 후보/상태 선택 편향을 남겨야 하며 전체 정책 효용이나 새 경험의 세대 간 개선을 대신 입증하지 못한다. 구체적 실행 조건과 종료 기준은 [최소 후속 계약](MINIMAL_RECURSIVE_RESEARCH_CONTRACT_20261101.ko.md)에 연결한다.
