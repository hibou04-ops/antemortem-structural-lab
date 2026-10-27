# E6 — Stateful Structural Mold와 Hypothesis-First

## 구현 범위와 연구 판정

E6는 유한 공개 EFSM 계약의 상태·행동·시간 관계를 E5의 실제 Version Space에 추가합니다. 기존 E5 모듈과 250개 테스트는 보존합니다. 구현과 일반화 성능은 별개입니다.

공개 개발 비교는 **NO_IMPROVEMENT**입니다. E6는 상태 문제 15회 중 14회 발견했고 세 black-box 기준선은 15/15입니다. 대표 가설 13개 중 12개는 새 개발 trace에서 반증됐습니다. E5의 알려진 last-pop 회귀는 표현되지만 새 문제의 OUT_OF_GRAMMAR는 남으므로 해결 판정은 **PARTIAL**입니다. 외부 실제 프로젝트 일반화는 **NOT_EXECUTED**입니다.

## 실제 코드 경로

| 계층 | 실제 구현·정보 흐름 |
| --- | --- |
| 공개 EFSM | `temporal.py`: 상태 초기값·타입, 행동 이름/역할, 공개 pre/postconditions, 동시 갱신식, invariant, dependencies, 순서와 first-failure-index |
| 공통 학습 | `temporal_engine.py`: E5 `DiscoveryEngine` 상속, static/AST·temporal 관계를 동일 relations/masks/groups에 넣고 동일 반증 제거 루프로 검사 |
| 기본 탐색 | `native_stateful.py`: 실제 Hypothesis `RuleBasedStateMachine/rule/precondition/invariant/Bundle`; 공개 EFSM만으로 행동·인자 결정 |
| 효율 | `efficient.py`: spec/version/actual-input 캐시, fresh native Strategy, incremental integer Z3 solver와 push/pop, 동일 SAT witness 중복 생성 방지 |
| 실제 평가 | `temporal_service.py`: 독립 callback 비교 → 최소 개발 증거 → worker 등록·갱신 → qualified query → freeze → native shrinking·2회 replay |
| 전이 | `temporal_transfer.py`: 입력·state·action 역할/이름, domain·초기 상태·전제·효과·불변식·기존 반증과 4-way gate |
| 정보 경계 | `temporal_protocol/boundary/worker.py`: 전송 전/수신 후 strict 검증, allowlist, frozen register/observe 차단, 별도 비용 RPC |
| CLI | `stateful-inspect/demo/run/plan`; E5 discovery/mold/pbt와 기존 MRI/CAST/Claim 유지 |

`register`는 native Hypothesis가 만든 공개 trace를 실제 callback 전에 worker에 등록합니다. 입력은 preconditions를 만족해야 하고 raw expected/actual state는 보내지 않습니다. 관측은 기존 최소 failure/refutation 필드와 첫 실패 전이 위치만 포함합니다. 새로운 관측에 따라 같은 group의 후보가 실제 제거되며, competing hypotheses와 provenance는 보존됩니다.

새 입력은 경쟁 가설의 불일치·다양성과 적용 가능성으로 선택됩니다. 공개 모델의 정수 인자를 incremental solver로 구별할 때 실제 새 유효 trace를 만들고 실행 경로에 사용합니다. SAT는 대상 프로그램 정답이나 결함 존재의 증명이 아닙니다.

## 명시적 지원 범위

EFSM은 최대4개 bounded int/finite float state projection, 최대16개 행동, 유한 산술·Boolean·조건부 동시 갱신을 지원합니다. 현재 native 실행은 integer argument domain 최대129값, trace min_size0/최대16단계를 요구합니다. 초기 projection은 선언 및 독립 Model과 일치해야 합니다. 미지원 float action arguments·임의 객체 의미·비정지 callback은 거절하거나 미검증으로 남깁니다.

구현 내부가 list/deque/서로 다른 저장 구조라도 호출자가 선언한 numeric projection과 step 계약으로 검사할 수 있습니다. 이 projection 밖의 값·순서·자료구조 의미는 검사하지 않습니다. E5의 int/float/str/list/tuple/dict API와 일반 함수 검증은 보존합니다. 모든 Python 프로그램의 의미 추론을 주장하지 않습니다.

## 실패 형상과 전이의 실제 증거

공개 두 행동 stack은 E5에서 알려진 last-element omission의 기능 회귀입니다. 독립 scalar Model은 push 뒤 size 증가, pop 뒤 size 감소를 검사합니다. 이는 새 독립 연구 결함이 아닙니다.

실제 학습 후 snapshot은 `HYPOTHESES_REMAIN`이 되고, action role과 public pre-state·order 조건을 표현하는 temporal 관계가 남습니다. source와 target의 이름을 trace→steps, push→offer, pop→take, count→occupancy로 바꾸고 내부 list를 deque로 바꾼 대상에서 frozen plan을 생성해 별도 Oracle로 실패를 확인합니다. 최종 계획에는 target feedback이 들어가지 않습니다.

한 실패로 원인을 확정하지 않습니다. `remove`와 직전 크기·이전 insert 관계, argument 조건 등 서로 다른 후보는 추가 관측으로만 반박합니다. 제약의 불확실성은 membership hypothesis로 유지합니다. `APPLICABLE_FOR_PROBING`은 탐색 근거, `NOT_APPLICABLE`은 계약 부적합, `UNKNOWN`은 근거 부족, `CONTRADICTED`는 승인된 target development evidence의 반증을 뜻합니다.

첫 prototype에 추가했던 clear/no-op 행동까지 포함한 3-action 설정은 budget128에서 실패를 관측하지 못했습니다. 이 결과는 보존했습니다. 배포 demo는 원래 E5 push/pop 회귀의 두 행동 계약이며, 연구 문제·seed·기준은 이 demo 변경과 무관하게 고정했습니다.

## 계산 비용 구조와 확인한 최적화

clean cold path는 빈 유효 seed만 보존하고 전체 후보 풀·temporal grammar를 계산하지 않습니다. 첫 failure 또는 approved prior에서 한 번 native pool과 static grammar를 만들고 이전 반증도 재검증합니다. 활성화 cutoff와 확장·solver cache version을 snapshot에 보존해 재생 중 미래 point가 과거 threshold를 바꾸지 못하게 합니다. Solver가 이미 새 witness를 선택한 라운드는 별도 guided Hypothesis batch를 생성하지 않습니다.

동일 3-action clean 명세·계약·target·Model hash, 동일 관측 입력 순서, model/target 각각24회 호출인 단일 공개 프로파일에서 pool 생성0.245초→0, worker init0.247초→0.0016초를 확인했습니다. 전체 wall은1.358→1.117초였습니다. 이는 불필요 계산 경로 제거의 기능 증거이며 통계적 효율·일반화 우위 주장이 아닙니다.

전체 wall은 startup/import·생성·IR·Version Space·solver·Oracle·축소·재실행을 포함합니다. worker dispatch는 검증/계산/JSON encoding을 측정하고 stdin 대기/출력 flush는 제외합니다. transport residual은 정확한 순수 IPC 시간이 아닌 관측 잔차입니다. 일부 phase는 겹치므로 합산해 전체 wall로 제시하지 않습니다.

서비스의 `oracle_calls`는 실제 model transition 수이며 target transition도 별도로 셉니다. E5의 whole-trace 함수 호출과 섞지 않습니다. 평가의 primary primitive count는 실제 model+target 전이 호출 합입니다. factory episode도 별도로 보고합니다. CPU process-tree 계측은 표본 하한, RSS는 표본 또는 시점 snapshot이며 OS peak가 아닙니다.

예산 중단이 Hypothesis의 불일치 오류에 감싸질 때 해당 run의 실제 중단 예외가 cause/context chain에 있는 경우만 `RESOURCE_BUDGET`으로 기록합니다. 무관한 nondeterminism은 전파합니다. 예산 내 미발견과 축소 미완료를 성공으로 바꾸지 않습니다.

## 사전 계약과 독립 평가

[평가 계약](E6_EVALUATION_CONTRACT.json)은 새 scalar EFSM 5계열과 프로젝트 정상 controls2개를 사용합니다. seeds13/47/89와 주요 판정을 결과 전에 정했습니다. 기존 E1~E5의 소비된 private holdout은 읽거나 재사용하지 않습니다.

Native Hypothesis full typed traces, Native RuleBasedStateMachine, 변경하지 않은 E5 baseline, E6를 비교합니다. CrossHair는 실제 공개 코드 source-aware tier로 별도 실행하며 내부 symbolic calls는 UNKNOWN입니다. 도구의 지원 밖은 NOT_COMPARABLE로 기록합니다.

개발 common resource cap은 model/target 각각1024 primitive calls, wall12초입니다. whole-trace 도구의128 callback cap과 native factory episode를 혼동하지 않습니다. Native episode는 별도 계측하고 실제 transition과 시간으로 제한합니다. 각 도구의 고유 설정·자체 종료 정책은 다르며 단위를 계약에 공개합니다. E6 기본 개발128/shrink62 transition, NativeStateful은 최대1024 transition을 사용할 수 있습니다. 기준선의 native shrinking을 약화하지 않았습니다.

최종은 모두64개 이하의 frozen plans를 평가하는 별도 track입니다. Native RBS도 public model만으로 계획을 만들며 target/Oracle callback을 전달하지 않습니다. 제품·계약·public fixtures·별도 private final source·source molds·E5 runtime 경로를 동결하고 exclusive once-only ledger를 사용합니다. 필요한7 cases×4 methods×3 seeds=84 records의 완전성을 검사하고 최종 feedback은0입니다. 필수 method의 control 오탐·실행 오류는 개선 판정으로 통과시키지 않습니다.

## 개발 결과와 반증

91개 기록:85 COMPLETE / static NativeStateful6 NOT_COMPARABLE, 오류·timeout·source drift0, control 오탐0.

| 방법 | 고유 상태 결함 계열 | model+target 실제 호출 | 전체 wall 합계(초) |
| --- | --- | --- | --- |
| Native Hypothesis | 5 | 9,760 | 20.296 |
| Native Stateful | 5 | 15,144 | 29.706 |
| E5 | 5 | 15,674 | 42.301 |
| E6 | 5 | 4,510 | 44.774 |
| CrossHair / source-aware | 2 | 내부 UNKNOWN | 별도 집계 |

E6의 seed별 stateful 발견은14/15, 다른 세 black-box는15/15입니다. E6 paired wall 중앙 비율은 Hypothesis2.514 / NativeStateful1.352 / E51.071이며, 호출 수 감소만으로 효율 향상이라고 하지 않습니다. 개발 판정은 **NO_IMPROVEMENT**입니다.

stateful E6 source15개는 HYPOTHESES_REMAIN13 / OUT_OF_GRAMMAR1 / NO_FAILURE_EVIDENCE1 / INCONSISTENT0입니다. Temporal 관계가 남은 source는13/15, 남은 관계 총36개입니다. 표현력 개선은 지원된 관계 범위에 한정하며 모든 새 실패 구조를 표현하지 못합니다.

별도 새 개발 traces320개에서 대표 temporal 후보13개 중12개가 반증됐습니다. 이는 검증된 원인이나 일반화 성공이 아닙니다. 선언 대응 gate는25/25(허용8/거절17), 실제 clean counterevidence4건에서 반박된 constraint 제거가 일치했습니다. 이 gate 정확도는 결함 전이 정밀도가 아닙니다. 감사 입력은 source 모델 튜닝으로 역류시키지 않았습니다.

[공개 집계](E6_RESULTS.json)와 [한국어 평가 보고](E6_EVALUATION_REPORT.md)는 전체 손실·비용 단위·비교 한계를 포함합니다.

## 최종 평가

최종 실행 전 제품 Git blob과 working bytes를 대조하고, 평가 담당자에게 freeze 신호를 보낸 뒤 한 번만 실행합니다. 최종 결과와 hash는 완료 후 이 절 및 공개 집계에 기록합니다. 결과를 보고 grammar/정책/가설/대상/기준을 같은 final에서 다시 조정하지 않습니다.

## 품질·보안·릴리스

기존250개 보존, 전체 unit/integration·CLI·명시적 호출 계수·계약 검증·snapshot 재생/변조·frozen feedback·경계·배포 실패 차단을 검사합니다. 새 CLI와 한국어/영어 README 명령은 설치된 wheel에서 확인합니다. source scope와 wheel/sdist의 private path/credential 검사를 수행합니다.

기본 subprocess는 LOGICAL_ISOLATION_ONLY. E4/E5/E6 각 Docker job에서 실제 file/network/uid/env 접근 통제를 검사하고, E6 job은 실제 stateful 학습·동결·재실행도 수행합니다. local Docker 미가용을 통과로 기록하지 않습니다. 대상/Model은 신뢰된 host code이고 임의 적대 코드 sandbox가 아닙니다.

PR CI는6개 OS/Python matrix+3개 Docker jobs, main publication은 이9개 성공 뒤 별도 job입니다. E5의 검증된 draft list/ID 조회·source/hash checker를 재사용하고 E6 현재 main에서만 annotated tag→검증된 draft→experimental prerelease/latest=false를 공개합니다. tag·asset을 덮어쓰지 않고 원격 download를 다시 검증합니다. PyPI와 Google Drive 정본 변경은 포함하지 않습니다.

## 미해결 병목

native 전략·검증/serial/import·격리·solver 비용이 실제 발견 이득으로 연결되지 않았습니다. 대표 가설의 새 입력 반증률도 높고 한 연구 source는 OUT_OF_GRAMMAR입니다. 더 풍부한 문법과 검증된 guidance 자격 판단은 후속 과제이며 이 final을 재소비하지 않습니다.

범용 객체 의미, richer container state, float action native execution, 무제한 trace/반복·비정지 함수 강제 중단, causal proof, 전역 최소 반례와 실제 외부 프로젝트 일반화는 제공하거나 입증하지 않았습니다.

## 공식 기반 문서

[Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) · [Z3 Solver API](https://z3prover.github.io/api/html/classz3py_1_1_solver.html).
공식 Hypothesis 문서 조회본은6.170.12, 로컬 실행본은6.170.11입니다. Docker는 실행 검증한 Hypothesis6.170.11/Z35.3.2.0을 명시적으로 설치합니다. library 자체의 원리를 재증명하지 않고 실제 어댑터·경계·계수만 검증합니다.
