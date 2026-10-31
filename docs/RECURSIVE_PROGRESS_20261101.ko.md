# 재귀 정책 구현·검증 — 2026-11-01

상태: **기능 경로 구현·합성 실행 검증 / 실제 개발 파일럿 HOLD / 실제 효용·미관측 일반화·세대 성능 개선 NOT_ESTABLISHED**.

이 작업은 2026-11-01 실행 미션에 따른 새 구현이다. 과거 `MINIMAL_RECURSIVE_RESEARCH_CONTRACT_20261101.ko.md`의 `DESIGN_ONLY / NOT_EXECUTED`와 역사 보고서는 수정하지 않는다. PR #12가 미병합이므로 기반은 해당 PR HEAD `525ca8b262497f5491c390580238de8949b241ef`이고 새 브랜치는 `feat/recursive-progress-20261101`이다. PR은 제품 수정 브랜치를 base로 삼아 이번 증분만 표시한다.

## 실제로 작동하는 경로

```text
C 개발 운반 → 종료 completion의 bounded trace 검증
→ host fresh reset + common/learned 각각 실제 3회 실행
→ development manifest + paired 영수증 검증
→ 고정 selector 업데이트 → 새 세대 append
→ 새 프로세스에서 세대 검증·복원 → 새 D 탐색의 실제 후보 선택
```

- `recursive_observe.py`: 같은 anchor의 common/learned 생성, C 복사본만 변경, 전용 shadow rule RNG 전후 상태 보존, completion trace/schema/크기 검증, 실제 운반 후보 대조, host 반복 실행·semantic exact 일치·reset·UNKNOWN·추가 비용.
- `recursive_policy.py`: 별도 selector sidecar, 6개 구조 context, 계보별 동일 가중 `(gain-loss)/resolved`, 둘 이상의 검토된 독립 단위와 양의 순이득일 때만 learned. missing feature는 `UNKNOWN`; `neutral_pass`와 `neutral_failure` 분리. 정확한 0 판정에는 유리수를 사용한다. 성공확률이나 무회귀 보장이 아니다.
- `recursive_store.py`: 원시 paired 영수증·manifest·통계·부모 digest·알고리즘·Mold·비용을 보존하는 canonical append-only journal. 배타적 협조 lock과 flush/fsync를 사용한다. 부분행·변조·잘못된 부모·버전·경험 롤백은 거부한다. 중복 영수증은 support를 늘리지 않는다.
- `recursive_api.py`: `create_generation`, `update_generation`, `run_generation`. 저장된 정책을 실제 새 `run_online(method="D", selector=...)`에 적용한다. 결과 파일을 실행 전에 배타적으로 예약한다. 실행 중 중단된 예약은 완료로 간주하지 않는다.

기존 Mold 문법·점수·규칙 수·슬롯 배분은 바꾸지 않는다. 기본 A 사용 경로도 유지한다. selector 없는 A/B/C/D와 paired 계측 off의 기존 경로는 회귀 검사로 확인한다. 기존 `online_worker`의 evaluate 5필드와 complete 3필드 외곽 계약은 유지하고 optional 설정과 result 내부의 trace만 확장한다.

worker에는 context 집계와 선택만 있는 runtime projection을 전달한다. full development evidence, 구현/Oracle 해시, 실제 출력, host-private semantic digest, 출처 계보·영수증 ID는 전달하지 않는다. 해시값을 통한 정책 정체성 연결은 통계적 독립성의 증명이 아니다. 경계는 `LOGICAL_ISOLATION_ONLY`이며 호스트 Target 실행은 OS sandbox가 아니다.

## 실행 가능한 예제

```bash
python -m pip install -e ".[qa]"
python -m tomolab recursive-demo --workspace work/my-recursive-demo --allow-local-execution
```

workspace는 새 디렉터리여야 한다. 예제는 직접 작성한 순수 함수·Oracle·동결 합성 Mold만 실행하며 실제 프로젝트 결함이나 독립 실증 자료로 세지 않는다. 전체 코드는 `tomolab/recursive_demo.py`에 있다.

예제는 관측 전에 기능 계약을 저장하고, 고정된 C 구조 슬롯의 실제 운반 관측 및 양쪽 3회 반복을 실행한다. G1은 서로 다른 작성 fixture의 gain 두 개, G2는 새 fixture의 loss 두 개를 추가한다. G2는 순이득이 0으로 돌아와 common을 고른다. 세대별 별도 Python 프로세스는 저장된 journal을 읽고 실제 후보를 실행한다. 별도로 같은 저장 세대를 fresh Hypothesis 탐색에도 적용한다.

| 검증 | G0 | G1 | G2 |
|---|---|---|---|
| 고정 상태 선택 | common | learned | common |
| 실제 실행 입력 | `[-1,-2]` | `[1,1]` | `[-1,-2]` |
| 작성 gain fixture 관측 | PASS | FAILURE | PASS |
| 새 전체 탐색의 learned 변경 실행 | 0 | 1 이상 | 0 |
| 누적 개발 영수증 | 0 | 2 | 4 |
| 누적 개발 Target/Oracle 호출 | 0/0 | 14/14 | 28/28 |

14회는 pair 2개×후보2개×반복3회와 C 운반 2회다. 실제 계수에서 Target·Oracle를 별도로 합산한다. 예제의 pair 추가 호출은 각각 24회이고 운반은 각각 4회다. 재시작 후 고정 슬롯·새 전체 탐색 비용은 세대 실행 영수증에 별도 보존한다. 이 결과는 행동 변화의 기능 증거이며 같은 총비용 성능 비교가 아니다.

`generations.jsonl`은 development의 host-private 원시 영수증을 포함한다. 실제 사용자 데이터로 만들었다면 공개 저장소에 올리지 않는다. 예제 출력 중 공개 CI에는 작성 fixture의 `summary.json`만 수집한다. 전체 실행·설치/빌드/검증 wall time은 별도 기록한다. `learning_seconds`는 업데이트 내부 검증을 포함한 구간이며 중첩 구간을 더해 총시간으로 쓰지 않는다. 세대 ledger의 `validation_seconds/io_seconds=0`은 별도 구간 분리 계측이 없다는 뜻이며 비용이 없다는 주장이 아니다. journal I/O·프로세스·직렬화 비용은 종단 wall 측정에 포함된다.

## Python API와 지원 범위

명시적 Python API를 제공하며 기본 공개 탐색에 자동 적용하지 않는다.

```python
from tomolab.discovery.recursive_api import create_generation, update_generation, run_generation

# 검토한 frozen_mold와 contract, 실제 development paired receipts/manifest를 사용한다.
g0 = create_generation("generations.jsonl", frozen_mold, contract)
g1 = update_generation("generations.jsonl", paired_receipts, development_manifest,
                       generation_id="G1", parent_id="G0")
receipt = run_generation(
    "generations.jsonl", frozen_mold, reviewed_target, reviewed_oracle, contract,
    generation_id="G1", execution_id="new-task-001", output="new-task-001.json",
    allow_local_execution=True, seed=47, budget=72, shrink_budget=9,
)
```

위 조각의 함수·자료는 호출자가 실제 검토한 객체를 공급하는 통합 지점이다. 자기완결 예제는 앞의 CLI다. 전체 운반·추가 개발 비용을 보유한 호출자는 `update_generation(..., cost_ledger=...)`에 누적 실제 장부를 명시한다. 입력하지 않으면 검증된 pair 비용과 이전 세대의 비용 하한을 보존하며, 영수증에 없는 자료수집 비용을 자동 추정하지 않는다.

M0는 `make_diagnostics(...)`로 opt-in하고 `run_online(method="C", diagnostics=..., diagnostic_reset=reviewed_reset)`을 호출한다. implementation/Oracle/환경/reset identity 및 검토 ID를 host에 제공한다. reset 미제공·실패, 반복 불일치, 미실행·오류·정체성 부족은 UNKNOWN/HOLD다. reset 함수의 의미적 완전성은 검토 책임이며 `lambda: True`로 외부 상태를 검증했다고 주장할 수 없다.

현재 snapshot은 명시적 OnlinePolicy의 data-only 상태다. native Hypothesis 내부 상태·타깃 전역 상태·전체 반사실 탐색을 복원하지 않는다. 재시작 기능은 저장된 selector를 다음 **새 탐색**에 사용하는 범위다.

## E7과 final feedback

selector는 탐색 효율 상태이며 E7 semantic claim이 아니다. `record_e7_linkage()`는 기존 `KnowledgeArchive` 검증과 `KnowledgeStore.append`를 재사용한다. 기존 freeze/fork·반증 보존·final 거부도 회귀 검사한다. rule_id→claim_id 자동 대응이나 탐지 성적만의 승격은 없다. 이번 selector linkage는 `E7_LINKAGE_UNKNOWN`이다. final split 영수증·manifest는 개발 업데이트에서 거부한다. 해시를 다시 계산하거나 이름만 development로 바꾼 자료의 의미적 독립성은 자동 보장되지 않으므로 실제 평가 역할은 사전등록·호스트 검토로 유지해야 한다.

## 실제 파일럿 판정

[자격 검토 JSON](RECURSIVE_PILOT_READINESS_20261101.json): 기존 private prepared 원본의 file SHA256 `c6159e46e4dd2c738c7c85f388da128e7ac05a192fd4a4961e361d27b9fc42eb`와 ALL Mold digest `8524b488e51ad145e9c9d544522a54a2bc2f4371b3baebf0d51108bfd998e24e`가 일치하며 validator도 통과했다. 원본을 재생성하지 않았다.

부족한 것은 미소비 새 개발 4계보/2프로젝트/2기전군의 사전등록, 독립 Oracle 의미·fresh reset·입력 계약·라이선스 검토다. 확인 범위는 기존 로컬 작업과 저장소 metadata이며 외부 전체에 자료가 없다는 증명이 아니다. 과거 소비 자료를 새 자료로 바꾸지 않았다. **실제 연구 Target/Oracle 호출은 각각 0회**다.

M0·A/C/F/L 정책 비교·U2 동일 과제의 G0/G1/G2 성능 비교는 실행하지 않았다. 새 자격자료가 확보되면 결과 관측 전에 실행 계약·역할·seed·해시·판정·재시도·단계별 예산을 동결해야 한다. 첫 M0는 각각 1,152회, 전체 연구는 각각 10,000회/실행 wall 60분/자료검토 120분 상한이다. 이 보고서는 빈 manifest나 미할당 후속 예산으로 실행을 개시하지 않는다.

## 조언의 실제 진전

| 조언 | 기존에 있던 기능 | 이번 실제 변경 | 행동 변화 증거 | 실제 효용 증거 | 판정 |
|---|---|---|---|---|---|
| 코드 자기수정보다 정책 학습·세대 갱신 | 동결 Mold와 run-local D | `recursive_policy/store/api` | G0→G1 learned, G2 common | 실제자료 비교 미실행 | 채택: 기능 진전, 효용 미입증 |
| 해로운 개입에 기권·게이트 | cap·validity·fallback·분리 RNG | 개발 대응 순이득 기반 선택 | G2 반증 후 common 복귀 | 무회귀 보장 없음 | 수정 채택: 경험 기반 기권 |
| 공통 대비 추가 기여 학습 | Source PASS→편집→FAILURE 지지 | `recursive_observe` 실제 paired 실행 | gain/loss/두 neutral/UNKNOWN 분리 | 국소 합성 fixture뿐 | 수정 채택: 실제 관측만 학습 |
| 구조 문맥을 적용 판단에 연결 | size/all_equal/negative Mold 조건 | 6특성 selector context | 같은 슬롯에서 경험에 따라 선택 변경 | MRI 새 의미 특성 검증 없음 | 기존 특성만 채택, MRI 확대 보류 |
| E7 보존과 다음 세대 연결 | freeze/fork/KnowledgeStore | 별도 세대 journal과 검토된 E7 링크 API | 부모·반증·원시경험 보존 | 의미 승격·일반화 없음 | 저장 재사용, linkage UNKNOWN |

가장 강한 반론은 작성 fixture가 행동 전환을 유도했을 뿐 실제 문제에서 selector가 유용하다는 증거가 없다는 것이다. 맞다. 따라서 기능 완료와 연구 성공을 별도로 표시하고, 기본 정책 채택·효용·미관측 일반화·세대 누적 성능 개선은 보류한다. 남은 연구 병목은 새 적격 개발/평가자료와 독립 Oracle·reset 검토이며, 표현/selector/계측/비용 중 어느 것이 성능을 제한하는지는 실제 M0 전 UNKNOWN이다.

## 검증과 보존

이번 bounded CI는 새 `recursive-*` 기능, 관련 online 경로, 기존 제품 모듈/별칭/CP1252와 E7 회귀를 명시적으로 실행한다. 새 브랜치에는 역사 연구·Source preflight·Docker 연구 job을 실행하지 않는다. wheel/sdist build, metadata·공개 범위 검사, checkout 밖 새 환경의 설치된 recursive 경로, 기존 제품 설치 검증, 역사 226파일·60회귀 보존을 별도로 확인한다. 구체 결과는 [검증 집계](RECURSIVE_VERIFICATION_20261101.json)에 기록한다. main 병합·태그·Release·PyPI 게시 권한은 이 PR에 없다.
