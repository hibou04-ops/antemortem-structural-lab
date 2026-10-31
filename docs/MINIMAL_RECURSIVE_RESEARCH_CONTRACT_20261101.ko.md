# 최소 재귀 연구 계약 — 2026-11-01

상태: `DESIGN_ONLY / NOT_EXECUTED`. 이 문서는 다음 연구의 실행 허가가 아니다. 이번 작업에서는 신규 Source·Target·Oracle 호출, Mold 재학습, 정책 갱신을 하지 않는다. 제품 검증 fixture의 실행과 이 연구를 구분한다.

## 핵심 판단과 선택한 질문

**다음 한 단계는 게이트 구현보다 동일 상태의 양쪽 결과를 남기는 계측이다.** 현재 Source 학습 입력으로는 공통 편집 대비 한계 기여 점수를 일반적으로 만들 수 없다. ■ INFERENCE [82%]: Source schema와 실행 로그의 직접 대조에 근거하며, 전체 가설족의 효용 부재를 뜻하지 않는다.

- 사실: 제품 기준 `3ece4df3bd01abe6aae58ef8a01bf4b01515f689`, 연구 실행 `6cbe985e77c482cda6413250a9a270924e648c0d`, 보고서 기준 `591f802dea6f8ac88a27af3ffd89bd6e1396b318`을 구별한다.
- 사실: 기존 D의 실제 changed-common 관측 240개 중 엄격한 C 대응이 있는 55개는 국소 이득 0, 손실 8, 중립 47이었다. 나머지 185개는 대응 결과가 없어 UNKNOWN이다. 이 55개는 새 블라인드 표본이 아니다. 상세 키·분모·보존 해시는 [관측 가능성 보고서](PRODUCT_LEARNING_OBSERVABILITY_20261101.ko.md)를 따른다.
- 사실: Source 88개 행의 공개 입력·관측 status·contract·source identity는 있으나, 동일 정책 상태에서의 anchor·common 후보·learned 후보·양쪽 결과는 학습 입력에 없다. 기존 PASS→편집→FAILURE 지지는 공통 정책 대비 추가 기여와 다르다.
- 가정: 계약에 맞는 pure callable 또는 검토된 완전 reset adapter에서, 동일 입력·코드·Oracle·환경의 결과를 재현할 수 있다. 위반 시 paired label을 UNKNOWN으로 둔다.
- 미확인: Source 경험이 **공통 경로에서 유용한 개입을 구별할 정보**를 갖는지, 그 정보로 배운 선택이 새 과제의 동일 총비용 성과를 개선하는지.

단일 검증 가설 `H_local`: **동결된 기존 Mold의 유효한 변경 후보에는, 고정 C 상태에서 공통 후보는 재현 가능한 PASS이고 학습 후보는 재현 가능한 FAILURE인 국소 추가 발견이 둘 이상의 독립 개발 계보에서 존재하며, 계보별 동일 가중 평균의 이득이 손실보다 크다.** 이는 작은 진단의 진행 기준이다. 효과 크기·성공확률의 추정치가 아니다. 이 가설의 참 여부는 현재 UNKNOWN이다. ■ EXPLORATION [<40%]: 환각 가능성 있음. 아래 실측 전에는 유용한 게이트를 배울 수 있다고 주장하지 않는다.

고려한 경로는 (1) 기존 점수에 즉시 게이트를 더하는 정책 변경과 (2) 양쪽 결과를 먼저 수집하는 계측이다. (1)은 공통 정책 대조가 없는 점수를 인과적 보상으로 잘못 사용할 위험이 있어 보류한다. (2)를 선택한다. 가장 강한 반론은 계측 자체가 비용을 추가하고 C 상태에만 조건부인 자료를 만든다는 것이다. 따라서 비용을 모두 기록하고, 이 진단의 성공을 전체 정책 우월성으로 올리지 않는다.

## M0: 이번에 설계하는 다음 실행의 한 가지 변경

변경은 **기존 Source 개발 운반 경로에 같은 상태의 두 후보를 기록·검사하는 paired 계측 한 가지**다. 구현 구성은 worker의 제안 직전 bounded data-only snapshot, completion trace 반환, host의 종료 후 검증·paired 실행으로 나뉜다. 호스트 계측만으로 현재 worker의 full state를 얻을 수 있다고 가정하지 않는다. 기존 Mold 점수·규칙 수·슬롯 배분·빈 입력 보호·MRI 특성·E7 승격은 바꾸지 않는다. 이번 PR은 이 계측을 구현하거나 실행하지 않는다.

고정 요소:

1. 동결 Mold는 기존 `prepared.json.molds.ALL`, `artifact_digest=8524b488e51ad145e9c9d544522a54a2bc2f4371b3baebf0d51108bfd998e24e`의 3규칙이다. private prepared 파일 SHA-256은 `c6159e46e4dd2c738c7c85f388da128e7ac05a192fd4a4961e361d27b9fc42eb`이며 semantic preparation digest와 구별한다. 이 규칙의 지원 kind는 `sequence_int`이므로 M0 자격 Source도 이 kind로 제한한다. common operator grammar와 편집 depth, preconditions `size_class/all_equal/has_negative`, `select_edit`의 가중치와 별도 rule RNG를 동결한다. MRI 의미 특성·`destroys_boundary`·빈 입력 특별 규칙을 추가하지 않는다.
2. replays는 동결 Source records의 FAILURE를 새 Source의 kind와 validate_input 계약으로 필터한 후 input_identity로 순서 보존 중복 제거한다. 기존 `benchmarks/online.py:_replays` 규칙을 사용하고 정확 replay 목록 digest를 사전 등록한다. Source별 MRI는 기존 방식으로 생성하고 평가 결과를 보기 전에 bytes와 digest를 등록하며 common/learned에 공유한다. 운반 정책은 현행 C이며, 네이티브 Hypothesis·archive·replay·budget 계수·확인·축소·피드백 규칙을 보존한다. `common_edit(anchor)`와 `learned_edit(anchor)`를 비교한다. `learned_edit(common_edit(anchor))`로 바꾸지 않는다.
3. 고정 C 운반 상태는 결과를 보기 전의 순서대로 저장한다. shadow learned 결과는 C의 `receive`, Hypothesis `target`, archive, RNG, rewards, seen 집합, 호출 잔여량에 되먹임하지 않는다. 계측 실행 시간은 운반 경로 종료 후에 별도로 지출·기록한다.
4. 동일 상태 비교는 D 전체 rollout의 복원이 아니다. C 운반 상태에서 D 제안 연산을 평가하는 조건부 진단이다.

관련 구현 위치:

- `online_engine.py:24-180`: `OnlinePolicy`, `common_state_digest`, archive anchor, `_common_structure_choice`, `_guided_structure_choice`, `propose`.
- `online_engine.py:227-314`: 실제 host 호출 계수, 두 번의 확인, 이벤트와 policy-state digest 연결.
- `online_learning.py:49-73,91-182`: 현행 Source 정규화·관측 일치·지지/반증 기반 점수. 새 paired 보상은 이 기존 schema에 있다고 가정하지 않는다.
- `online_mold.py:22-42,126-141`: 현재 특성·적용·선택. MRI branch 의미를 새로운 policy predicate로 공급하지 않는다.
- `online_observe.py`의 실제 관측·입력 검증·오류 분류와 현재 정확 0 비교를 그대로 사용한다.

### 자료 선행 조건과 독립성

현재 확보: 기존 동결 코드/Mold/계약/Source 기록, 기존 실행 원문과 파생 분석. **미확보: 다음 진단의 새 개발 Source와 검토된 paired 영수증.** 기존 E1~E9-R1 소비 자료는 설계·선택 자료로만 남긴다.

향후 별도 승인 뒤, 결과를 보지 않은 계약·계보 metadata로 개발 Source 4계보를 사전 등록한다. 적어도 2프로젝트와 2기전군을 포함하고, pure/reset 지원·공개 입력 계약·독립 Oracle의 검토를 먼저 끝낸다. 선정 manifest는 구현/Oracle/계약 해시, 프로젝트·기전·계보, 라이선스·접근 범위, 제외 사유, 자료 역할을 묶어 동결한다. 자격 Source가 4계보 미만이면 축소된 평가를 성공 기준에 맞춰 재해석하지 않고 `HOLD_INSUFFICIENT_LINEAGES`로 끝낸다.

독립 단위는 검토된 구현/결함 계보이며 시드는 독립 결함이 아니다. 프로젝트·기전군·고유 결함·시드 반복을 별도 열로 보고한다. 독립 Oracle의 의미 검토는 해시 차이만으로 대체하지 않는다. 런타임 LLM 부재는 사람/AI 설계·공개 결함 지식·선정의 영향을 제거하지 않는다.

### 저장할 상태와 paired 영수증

각 구조 슬롯의 `native_input`, archive에서 택한 `anchor_input`, `common_input`, `learned_input`을 서로 다른 필드로 둔다. 민감한 실제 입력은 비공개 호스트 기록에만 남기고 공개 문서에는 해시와 집계만 둔다.

필수 필드:

| 묶음 | 필드 |
| --- | --- |
| 계약·실행 정체성 | schema/version, experiment_contract_sha256, implementation_sha256, oracle_sha256, input_contract_sha256, MRI/structure_sha256, environment/dependency lock, source_lineage_id, project_id, mechanism_id, split=development |
| 상태 | run_id, seed, proposal_index, actual_calls_before, phase, full policy state bytes와 digest, common_policy_state_before, native RNG state, rule RNG state, caps/used/attempts/archive/last_feedback/operator_rewards/seen, reset-adapter identity |
| 후보 | native/anchor/common/learned의 입력·digest, common_operator, rule_id/edit_composition, Mold digest, source_state, validity/duplicate/fallback 사유 |
| 실제 실행 | branch=common/learned, observation IDs, 각 반복의 status/feedback digest와 host-private semantic_digest, 실제 Target·Oracle 호출 증분, reset 성공, 오류·시간·확인 일치, 후보별 outcome identity |
| 사전 예약 | reservation_id=SHA256(canonical(contract_digest, lineage_id, run_id, proposal_index, state_digest, native/anchor/common/learned candidate digests)); 결과·label·비용은 포함하지 않음 |
| 완료 영수증 | reservation_id, 실제 반복 결과·비용·파생 label·불확정 사유·source linkage를 묶은 pair_receipt_sha256; 실행순서 결정에 사용하지 않음 |

`common_policy_state_before` 하나만으로 타깃 상태·Hypothesis 내부 상태·환경의 동일성이 입증되지는 않는다. 후보 단위의 pure/reset 비교에 필요한 계약·파일·환경·입력·reset 가정을 함께 검토한다. 전체 정책의 반사실 경로를 이 자료에서 복원하지 않는다.

계측 경계: `_run_online_core` worker의 `policy.propose(base)` 직전에서 JSON-safe public policy state를 캡처하고, 제안 직후 후보·reservation을 붙여 새 버전 `diagnostic_trace`를 completion result에 넣는다. 별도 opt-in diagnostic config/schema와 정확한 field validator를 정의한다. 기존 `online_boundary.py:56-64`의 evaluate 요청 `{action,request_id,input,phase,reference}` 5필드 계약은 유지하고 snapshot을 evaluate envelope에 넣지 않는다. completion 바깥의 `{action,result,inventory}`도 유지한다. snapshot별128KiB, 최대12예약, trace 총2MiB, 기존 전체 메시지8,000,000B 상한을 모두 검사한다. 어느 상한이든 초과·필드 불일치·digest 불일치가 나면 truncation/생략으로 성공 처리하지 않고 `HOLD_MEASUREMENT`로 fail closed한다. host는 worker 종료 후 version/field/cap/state-candidate consistency와 실제 운반 관측을 검증한 뒤에만 pair를 실행한다. Target/Oracle raw 값과 semantic_digest는 host에만 남기고 worker feedback으로 보내지 않는다. 이는 한 계측을 위한 필수 경계 변경이며 정책 score·schedule 변경과 묶지 않는다.

계측 순서:

1. 실제 C 제안 직전의 상태와 native 입력을 캡처한다. 같은 common 상태의 shadow 복사본에만 동결 Mold와 별도 rule RNG를 넣고 D의 기존 제안 함수를 호출한다. shadow rule RNG는 전용 고정 seed에서 시작해 구조 슬롯마다 순서대로 전진하고, native/C RNG는 건드리지 않는다. 실제 C와 shadow가 만든 common digest가 다르면 그 슬롯을 UNKNOWN으로 남기고 원인을 수정할 때까지 수집을 중단한다.
2. invalid/duplicate/fallback도 모두 기록한다. 유효하고 common과 다른 learned 후보가 나온 앞 12개 슬롯만 결과와 무관하게 pair로 예약한다. 같은 상태·후보 digest의 중복 예약은 한 번만 허용한다. 12개를 채우려고 Source·seed·정책을 바꾸지 않는다.
3. C 운반 실행과 completion trace 검증을 마친 뒤, 예약한 각 후보를 fresh reset 환경에서 3회씩 실행한다. common과 learned 모두 실제 Target/Oracle 결과를 남긴다. 후보별3회 status가 모두 같고 host-private semantic_digest가 정확히 같으며3회 모두 reset 성공을 확인해야 resolved로 인정한다. 이는 현행 confirm의 semantic_digest/reference_match 검사보다 약해져서는 안 된다. 검증된 결정성이 없거나 반복 status/semantic_digest/reset 결과가 다르면 UNKNOWN이다. Oracle 오류·실행 오류·입력 거절을 PASS로 대체하지 않는다.
4. 모든 분기 순서는 **결과 관측 전에 고정한 `reservation_id`**의 최하위 비트로 정한다. 완료 결과를 포함하는 `pair_receipt_sha256`는 실행 뒤에만 만들며 실행순서 결정에 쓰지 않는다. common 먼저/learned 먼저가 한쪽의 잔여 상태를 소비하지 않도록 매회 reset한다. 호출·시간 한도가 pair 도중 끝나면 미완료 pair와 사용한 비용을 보존하고 UNKNOWN으로 처리한다.
5. C 운반 실행의 발견과 shadow에서만 얻은 발견을 분리한다. shadow 발견을 C/D의 원래 성능이나 자동 발견으로 세지 않는다.

## 비용·규모·종료

아래 숫자는 **제안한 엔지니어링 자원 상한**이며 과거 24/48·88·384에서 추정한 통계적 검정력 값이 아니다.

- Source 4계보 × 사전 고정 seed 2개 = 운반 8회. seed는 `int(SHA256(contract_id || lineage_id || repeat_index)[:8],16)`로 결과 전에 결정한다.
- 운반 1회: 실제 Target 최대72회, Oracle 최대72회, 그 안에 shrink_budget 9와 현행 확인·재현을 포함한다. 따라서 discovery_limit은63이고 현행 caps는 replay=63//5=12, structure=3*63//10=18이다. 각 구조 슬롯의 +3 여유 검사도 그대로 둔다. 이 규모는 3-call 확인과 구조 cap 아래 여러 슬롯을 관측하는 작은 진단을 위한 상한이다. Oracle/Target 횟수가 항상 같다고 가정하지 않고 둘 다 독립적으로 제한한다.
- pair 최대12개 × 후보2개 × 반복3회 = 운반당 추가 Target 최대72회·Oracle 최대72회. 캐시·기존 관측으로 실제 호출을 했다고 채우지 않는다.
- 예약 pair의 추가 호출은 별도 진단 ledger에 계수하며 C 운반의 budget72/discovery_limit63 또는 policy.used를 바꾸지 않는다. 이를 합친 총 최대1,152 Target +1,152 Oracle 호출. 후보 생성/검증/조회 횟수는 호출과 별도로 전수 계수한다. Mold는 동결되어 이 M0의 Source 재학습 호출은0이다. 과거 Source 취득·학습 비용은 별도 sunk-cost 열에 남기며0으로 삭제하지 않는다.
- 운반 1회30초, 예약 pair 단계 1회90초, 전체 machine wall 상한20분, 수동 계약/Oracle 검토 상한120분. 초과 시 미완료 상태로 종료한다. 프로세스 시작·reset·MRI·조회·직렬화·파일 I/O·학습 CPU·확인·축소·재현·실패 호출도 기록한다. 겹치는 시간은 phase 표시에 따라 중복 합산하지 않는다.
- 환경/계측 오류에 한해 동일 동결 manifest·동일 seed의 중단 실행을1회 재시도할 수 있다. 원 실패·부분 비용을 보존하고 총 비용에 포함한다. 과학적 미검출·손실·낮은 적용률을 이유로 재시도하거나 문턱값을 바꾸지 않는다. 재시도도 위 전체 상한을 늘리지 않는다.

### 지표와 사전 판정

pair의 common·learned 각각3회가 모두 PASS 또는 모두 FAILURE이고, **후보별3회 semantic_digest exact 일치·매회 reset 성공·계약 유효성**을 모두 만족할 때만 다음을 부여한다. 두 후보끼리 semantic_digest가 같아야 한다는 뜻은 아니다.

- gain: common PASS, learned FAILURE.
- loss: common FAILURE, learned PASS.
- neutral: 둘 다 PASS 또는 둘 다 FAILURE. 두 중립 유형은 별도 집계한다.
- UNKNOWN: 오류/반복 불일치/동일성 불충분/미완료. invalid·duplicate·fallback·후보 동일도 예약 전 별도 분모로 보고하며 이들을 성과에서 삭제하지 않는다.

각 계보에서 `(gain-loss)/resolved_pairs`를 계산하고 네 계보를 동일 가중한다. 분모0인 계보는 UNKNOWN이며 평균에서 조용히 제거하지 않는다. pair 수·발견 입력 수·고유 결함 수를 구별한다. 운반의 미검출과 budget exhaustion도 반드시 남긴다.

- `LOCAL_SIGNAL_OBSERVED`: 4계보 모두 적어도1개 resolved pair가 있고, 전체 예약 pair의 UNKNOWN 비율≤25%, 둘 이상의 독립 계보에서 gain≥1, 계보별 동일 가중 평균 순이득>0. 다음 selector 검토를 진행할 수 있다는 뜻이다.
- `HOLD_NO_LOCAL_SIGNAL`: 계측 완결성 조건을 만족했으나 위 이득 기준 미달. typed-edit 가설족 전체 반증이 아니라 이 동결 Mold/운반 분포에 대한 자원 배분 보류다.
- `HOLD_MEASUREMENT`: 자격 계보·유효 pair 부족, UNKNOWN>25%, 정체성·reset 실패, 비용/시간 상한 초과. 유효성 문제를 성능 실패로 바꾸지 않는다.

본 M0는 양쪽 후보에 같은 반복 횟수를 쓰는 **국소 비교**다. 추가 호출 때문에 전체 D 정책의 같은 총비용 효용을 검증하지 않는다. 공동 탐지의 속도만 보고 미검출 손실을 숨기지 않는다. 아직 global rollout superiority와 재귀 개선은 `NOT_ESTABLISHED`다.

## M0 이후에만 검토할 정책·재귀 계약

다음 항목은 M0에 묶어 실행할 두 번째 변경이 아니다. M0 성공 뒤에도 별도 사전 등록·사용자 실행 허가·독립 자료 경계가 필요하다. M0를 본 뒤 아래 규칙을 임의 조정하면 그 자료는 추가 선택 자료로 소비되고 새 독립 개발 검증이 필요하다.

### 학습 대상과 고정 업데이트

학습할 것은 semantic failure predicate가 아니라 **현행 구조 슬롯에서 common과 frozen-Mold learned 후보 중 어느 것을 실행할지**다. 정책 변경은 이 binary selector 하나로 한정한다.

- context key = `(kind, size_class, all_equal, has_negative, common_operator, learned_edit_composition)`. 미존재 특성은 별도 UNKNOWN 값이며 False로 강제하지 않는다. MRI 새 의미 특성을 더하지 않는다.
- 매 개발 pair의 gain/loss/neutral을 source-lineage별로 집계한다. 동일 reservation/완료 pair 중복과 seed 반복은 독립 support 수를 늘리지 않는다. key별 state는 `lineage_gain_count`, `lineage_loss_count`, `resolved_pair_count`, `unknown_pair_count`, consumed_reservation_ids 및 전체 paired receipt digest다.
- 고정 업데이트는 새 개발 pair를 중복 없이 append하고 lineage별 `(gain-loss)/resolved`를 동일 가중해 `u(key)`를 다시 계산한다. 둘 이상의 독립 lineage에 resolved 근거가 있고 `u(key)>0`일 때만 learned를 선택한다. 그 외에는 common을 선택한다. UNKNOWN을 이득/손실0으로 보충하지 않는다. 규칙 수·Mold 점수·slot cap은 유지한다.
- 기존 `online_mold.py`의 엄격한 score/schema는 새 한계 기여 점수와 다르다. 기존 `selection_statistics.empirical_score`를 위 점수로 덮어쓰거나 기존 artifact가 지원하는 것처럼 가장하지 않는다. 별도 버전의 selector sidecar와 validator로 정의하고 parent/Mold/contract/paired-evidence digest를 묶는다.
- 사람이 결과를 보고 편집·가중치·threshold를 바꾸지 않아도 새로운 개발 pair가 `u` 부호를 바꾸면 다음 세대의 동일 구조 슬롯 행동이 바뀐다. hash 변경만으로 행동 변화가 입증되지는 않으므로 고정 candidate-state 목록의 before/after 선택 차이를 별도로 남긴다.

### 동일 비용 정책 검증과 최소 대조군

최초 정책 검증의 비교군은 A, C, `F`, `L` 네 개로 고정한다.

| 군 | 의미·식별 목적 |
| --- | --- |
| A | 강한 A/B 후보 중 A를 결과 전에 선택. 기존 작은 예산에서 C가 항상 최강이 아니었고 A/B가 동률이었으므로 추가 복잡성이 적은 A를 지정한다. 새 결과를 보고 B로 교체하지 않는다. |
| C | 공통 replay/local 구조 경로의 비용·발견 기준. |
| F | L과 같은 slot·feature·Mold·validity/fallback·보호 조건을 쓰되 Source utility를 제거한 고정 common 선택. sidecar 로딩·특성 계산 overhead도 동일하게 수행해 L의 이득이 단순 안전 규칙/배분인지 구별한다. |
| L | 위 고정 업데이트로 학습한 selector. |

F는 동결·경험 제거 대조를 겸한다. 여기서 C/F의 의미적 선택은 같지만 F가 selector 장치 비용을 갖는 차이를 명시한다. 별도 exchange control은 기본 구성에서 제외한다. 규칙/경험 교환은 적용률·rule 수·비용까지 바꾸기 쉬워 이 작은 비교가 추가로 식별할 변수가 불명확하다. 추후 필요하면 교환 정보를 하나로 제한하고 적용률/비용을 맞춘 별도 계약을 쓴다. 동률만으로 경험 무용·선정 편향 등의 원인을 확정하지 않는다.

최종 정책 비교의 입력 manifest·예산은 M0 결과와 무관한 새 개발 검증 자료를 바탕으로 결과 열기 전에 동결한다. 각 군 동일 Target/Oracle 총 cap과 동일 machine wall cap을 적용한다. L의 Source 수집/paired 추가 실행/학습/lookup overhead는 같은 평가 wave의 총 자원에서 먼저 차감한다. A/C/F에도 동일 전체 자원을 부여해 남은 예산을 탐색에 쓸 수 있게 한다. 평가 타깃 수를 사후 늘려 L의 학습 비용을 임의 상각하지 않는다. 수동 계약 노동은 군별·공통 비용을 따로 보고하고 이미 소비된 노동도0으로 치환하지 않는다.

정책 성공은 미검출 포함 고유 결함 탐지와 capped detection cost에서 L이 A·C·F 모두를 개선하고, 추가 시스템 비용을 포함해도 사전 criterion을 만족할 때만 선언한다. 동시 성립하지 않으면 TRADEOFF 또는 HOLD다. 특히 A/F를 이겨도 C를 개선하지 못하면 공통 탐색 대비 추가 효용 성공으로 선언하지 않는다. 실행 가능한 최종 수치 cap·표본 manifest·사전 criterion이 비어 있으면 정책 평가를 실행하지 않는다. M0의1,152회 상한을 이 후속 평가에 자동 복사하지 않는다.

슬롯75% 보존 또는 현행 cap은 개입 범위를 제한할 뿐 탐지 성능의 하한을 보장하지 않는다. 기준선의 유일한 성공이 남은25%에 있거나 한 개입이 이후 archive/RNG/feedback을 바꾸면 손실이 가능하다. ■ CONSENSUS [95%]: 예산 비율에서 적응적 정책의 무회귀 보장은 도출되지 않는다.

### 세대·자료 소비·영속 상태

각 세대는 `(parent_policy_digest, selector_state, Mold_digest, update_algorithm_digest, consumed_development_manifest, E7_archive_receipt, cost_ledger)`를 남긴다. G0는 **위 ALL Mold를 그대로 보유하되 selector 충분통계가 비어 있어 항상 common을 고르는 F 정책**이다. 기존 D의 무조건 유효 learned 선택을 G0라고 부르지 않는다. G1은 새 개발 T1(M0)의 고정 업데이트 결과, G2는 별도 새 개발 T2의 고정 업데이트 결과다. 업데이트 최대2회, 각 wave의 frozen evaluation은1회다. 결과가 나쁘다고 세대를 건너뛰거나 이전 snapshot을 최신으로 복원하지 않는다.

- T1/T2는 source/development 선택 자료다. 규칙 유지·폐기·문턱값·승격에 사용한 순간 consumed로 기록한다. 동일 구현/결함 계보는 다음 미관측 최종 평가가 될 수 없다.
- U1은 G1 동결 후, U2는 G2 동결 후 확보하는 서로 겹치지 않는 새 미관측 평가 경계다. U2의 동일 과제에서 G0/G1/G2를 모두 평가해 초기·직전·현재를 직접 비교한다. 평가 순서를 사전 고정/균형 배치하고 각 run을 reset하며, 각 군 같은 누적 자원 계산을 적용한다.
- U1/U2는 최종 평가이므로 feedback을 E7 또는 selector 개발 업데이트로 보내지 않는다. G2는 U1 결과가 아니라 별도 T2로만 갱신한다. T2 선정 manifest·고정 업데이트·예산·제외 기준은 U1 결과 공개 전에 동결하고, T2 선정자/업데이트 절차는 U1 feedback을 받지 않는다. 개별 semantic 결과뿐 아니라 U1 aggregate report도 T2 선정·threshold·업데이트·예산 변경에 사용하지 않는다. 사람/AI의 사후 Source 선정으로 final feedback 경계를 우회하지 않는다. 이 정보 경계를 확인할 수 없으면 G2의 미관측 개선 판정을 보류한다. 평가 뒤 학습하는 온라인 방식을 원하면 기존 final을 development로 바꾸지 않고 별도 프로토콜과 그 뒤의 새 독립 평가가 필요하다.
- G1의 한 번 개선은 관련 Source 추가 효용 단계다. G2가 U2에서 G1과 G0를 누적 비용 포함 개선하고 또 다른 독립 wave가 반복되기 전에는 세대 누적 자기개선으로 부르지 않는다. 여기서 최대2회 업데이트는 그 주장에 충분한 반복 실증을 자동 보장하지 않는다.
- 두 독립 개발 wave 모두 추가 이득이 없거나, 행동은 바뀌어도 A/C/F 대비 순성과가 개선되지 않거나, 새 평가에서 직전 세대 손실이 비용 이득을 상쇄하면 추가 효용 가설을 보류한다. 알려진 빈 입력 손실의 복구, empty-Mold fallback 동률은 별도로 보고한다.

## E7을 재사용하는 정확한 경계

다음은 현재 원문으로 확인한 구현 계약이다. ■ CONSENSUS [95%]: 이 문서의 설계가 아니라 기존 API의 거부·검증 경로다.

1. `knowledge.py:70-125`의 `normalize_observation`/`normalize_semantic_observation`은 `split=development`만 받고, 명세·공개 IR·출처·구현 identity·최소 evidence·receipt를 검증한다. 출처의 Oracle 해시는 제공된 경우 검증되며, 독립 적용 자격에는 구현·Oracle 해시와 검토 식별자가 모두 별도로 필요하다. `knowledge_protocol.py:44-54,73-84`도 초기 purpose와 일치하는 관측을 검사한다. 임의 score/원시 actual·expected를 E7 evidence에 밀어 넣지 않는다.
2. `knowledge.py:500-543`의 `freeze/fork`는 완전한 frozen parent 해시·유일한 generation ID·기존 journal과 반증을 유지한다. fork 뒤 `learn` 덮어쓰기는 금지되며 검토된 development 관측만 추가한다. 새 Source 학습은 별도 archive 문맥에서 한다.
3. `knowledge_store.py:22-25,63-96`의 기존 `KnowledgeStore.append`를 semantic archive 영속 기록에 사용한다. 동일 ID 동일 snapshot은 idempotent이고, journal prefix rollback은 거부한다. selector sidecar는 E7 strict snapshot에 임의 필드로 삽입하지 않고 별도 append-only generation manifest로 연결한다. 해시 체인은 기록 보존·정체성 근거이며 인과성/독립성의 증명이 아니다.
4. `knowledge.py:891-898,987-1021`의 `record_guidance_utility`는 trusted host, 실제 claim IDs, Source-validation batch, comparison contract, 관측 호출/시간, selection_changed와 first_discovery_new_guided의 명시적 bool 값을 요구한다. 실패한 utility 기록도 받을 수 있으며 UTILITY_SUPPORTED 판정에는 실제 변경·새 guided 첫 발견·사전 비용 조건을 함께 만족해야 한다. 귀속은 `ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT`다. 전체 배치 성공을 개별 rule의 인과 기여로 나누지 않는다.
5. `knowledge.py:929-960`의 R1 `qualify`에는 frozen archive, Source 지지, 독립 contrastive corroboration, 적용 계약·출처·필요한 AST 대응, empirical utility가 함께 필요하다. 탐지 성적만으로 `QUALIFIED_FOR_PROBING`이 되지 않는다. 현행 E9 edit `rule_id`와 E7 semantic `claim_id`는 서로 다른 identity이며 자동 대응이 없다. 지원 grammar와 의미적 linkage가 검토되지 않으면 `E7_LINKAGE_UNKNOWN`으로 남긴다.
6. E9 selector의 loss는 탐색 효율의 반증이고 E7 semantic claim의 반증과 동일하지 않다. semantic prediction과 실제 Oracle 결과가 충돌하는 최소 development 영수증만 기존 observe 경로로 제출한다. 반증 제거·이름 변경·과거 snapshot rollback으로 승격을 복원하지 않는다. `final_feedback_allowed=False`는 세대가 바뀌어도 유지된다.

이 계약이 허용하는 현재 결론은 **필요 계측·업데이트·비교·자료 경계가 구체화되었다**는 것이다. Source 추가 효용, 같은 총비용의 정책 우월성, 다음 미관측 과제의 세대 개선, 반복 누적 자기개선은 아직 입증되지 않았다.
