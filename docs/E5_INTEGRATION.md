# E5 — Unified Structural Discovery Engine

## 구현과 판정 범위

E5는 기존 E4 Mold를 보존하고 `tomolab/discovery`에 typed 통합 엔진을 추가합니다. 기능 구현과 bounded QA 성능, 외적 일반화는 별도로 판정합니다. 개발 비교는 `NO_IMPROVEMENT`입니다. 이 문서의 aggregate는 직접 작성한 mutation과 사용자 저장소의 clean control에만 해당하며 실제 외부 프로젝트에서의 우위는 `NOT_EXECUTED`입니다.

| 연결 | 실제 소비·생성 정보 | 구현 |
| --- | --- | --- |
| 공개 명세 → AST IR | 타입·역할·조건·의존성·상태 효과·정적 graph | `schema.py`, `analysis.py`, `predicates.py` |
| IR → Version Space | 역할로 정규화한 guard가 실제 구조 가설 문법에 추가 | `engine.py` |
| 실패·반증 → 학습 | 지원된 관측으로 반증된 가설 제거, 경쟁 가설·이력 유지 | `schema.py`, `engine.py` |
| 가설 → Active Query | 의미 중복 투표 감소, 불일치·다양성·공개 Oracle 비용 | `engine.py`, `features.py` |
| native Hypothesis → 후보 | 유한 typed Strategy와 조건 유도 fresh 후보를 실제 풀에 추가 | `hypothesis_adapter.py` |
| Z3 → 실제 선택 | 지원된 정수 제약의 SAT/UNSAT와 구별 witness, 실제 후보 재검증 | `solver.py` |
| 평가 → 반례 축소 | 생성기 동결 후 full Strategy의 native find/shrink와 재실행 | `service.py` |
| 동결 Mold → 전이 | 타입·역할·정적 graph·guard literal·계약·반증 검사 | `transfer.py` |
| CLI → 독립 실행 | JSON-only 별도 worker, 전송 전·수신 후 검증 | `protocol.py`, `boundary.py`, `worker.py` |

E4의 `mold-*`, `pbt-*`, `constraints-check`와 MRI·CAST·Claim-to-Witness는 유지합니다. 기존 `mold/boundary.py`의 transport를 subclass 설정으로 재사용하며 E4 기본값은 같습니다. 이전에 공개되지 않았던 사용자 소유 discovery 초안은 이번에 검토·통합·실행 검증했으며, 과거에 이미 검증된 공개 기능으로 취급하지 않습니다.

## 지원된 의미와 정직한 UNKNOWN

입력 계약은 범위 있는 int/finite float/str/list/tuple/문자열 키 dict를 지원합니다. 복합 크기와 중첩 깊이를 제한하고 출력은 유한 JSON 계약으로 비교합니다. bool과 int의 JSON 표기는 구별하지만 tuple/list는 JSON에서 동일한 배열이며 반환값의 모든 nominal type 동치는 보장하지 않습니다. NaN·무한값은 거부합니다.

AST는 import/실행하지 않습니다. 제한된 `if`, `for`, `while`, 산술·비교·Boolean, 명시적 자료구조 연산을 기록하지만 `SUPPORTED_STATIC_IR`은 지원된 **구문 기록**이며 의미 복원 증명이 아닙니다. unsupported 구문, annotation 불일치, 타입·역할 불충분은 명시적 거부 또는 UNKNOWN입니다. 반복문의 종료 증명이나 임의 객체 상태 추론은 제공하지 않습니다. trace는 제한된 데이터로 상태 전이를 재생하며 live 임의 객체를 격리 실행하지 않습니다.

Z3는 finite integer DSL에만 적용합니다. 실제 Python 의미와 일치하는 범위를 테스트하고 witness를 확인합니다. float/string/container 전체 의미를 SMT로 증명하지 않습니다. 전이의 literal-free graph는 이름 변경의 대응에 사용하고 guard 상수는 별도로 검사합니다. `x+1`과 `x+2` 같은 반환식이 같은 graph를 가질 수 있으므로 의미 동치나 결함 재현을 주장하지 않습니다.

실행 어댑터는 하나의 명시적 불변식과 서로 다른 신뢰된 target/Oracle을 요구합니다. 함수 binding 오류·지원되지 않는 반환값은 결함으로 위장하지 않습니다. Oracle 예외는 기본 전파하며 명시적으로 승인한 예외 종류만 결과 계약에 포함합니다. 두 번의 재실행은 일반적인 순수성·결정론성 증명이 아닙니다. `time_budget`는 협력적 검사이며 멈추지 않는 callback에 대한 강제 제한이 아닙니다.

## 실제 end-to-end 증거

공개 `examples/discovery`는 직접 작성한 순수 Python 예제와 별도 Oracle입니다. source checkout과 설치 wheel의 `discovery-demo`에서 실행합니다.

| 예제 / 고정 설정 | 실제 결과 |
| --- | --- |
| sequence, budget 12 / pool 32 / shrink 16 / seed 7 / Z3 | 첫 실패 query 1, 개발 12 + 축소 13 + 재실행 2 = 실제 Oracle 27회 |
| sequence 구조 반례 | `values=[-1,1], offset=0`; 리스트 합 0과 길이 조건이 실패와 연결됨. 유일한 원인 증명은 아님 |
| sequence 생성 연결 | native rounds 2 / attempts 192; solver calls 9 / SAT 7, witness가 실제 선택됨 |
| state, budget 16 / pool 32 / shrink 32 / seed 7 | 첫 실패 query 4, 개발 16 + 축소 26 + 재실행 2 = 실제 Oracle 44회 |
| state 축소 반례 | `push(0), pop(0)`; 실제 남은 상태 `[0]`, 독립 Oracle `[]` |
| renamed sequence frozen plan | 후보 8개, `APPLICABLE_FOR_PROBING`, final feedback 0, 동일 결함 재현은 UNKNOWN |

이 수치는 위 설정의 실행 기록입니다. 다른 seed·Hypothesis 버전·CPU에서 같은 시간이나 모든 callback 수를 보장하지 않습니다. native shrinking 완료는 전역 최소 반례 보장이 아닙니다.

## 평가 계약과 데이터 경계

[사전 평가 계약](E5_EVALUATION_CONTRACT.json)은 개발 결과를 보존하고 최종 source·코드·계약·source mold를 평가 전에 동결합니다. 기존 E1~E4의 소비된 holdout은 재사용하지 않았습니다.

개발은 다섯 mutation 계열(addition-order, whitespace, stable-dedup, negative-float-sign, reset-state-transition)과 사용자 저장소의 두 clean control을 사용합니다. 각 계열은 여러 seed·입력·변형·재실행과 무관하게 결함 하나로 셉니다. E4/Hypothesis/E5 seed는 17·43·101, max actual Oracle calls 128, 전체 wall cap 10초입니다. startup·import·IR·생성·solver·평가·축소·재실행을 시간에 포함합니다. native Hypothesis도 같은 typed full Strategy, 명시 seed, database 없음, 순수 중복 입력 캐시를 사용합니다.

CrossHair는 실제 설치 CLI를 사용한 source-aware tier입니다. 공개 개발 문제에만 적용하고 concrete witness를 독립 Oracle로 재실행합니다. 내부 symbolic 호출 수는 UNKNOWN이며 equal-call black-box 순위에 합치지 않습니다. E4 미지원 domain은 실패가 아니라 `NOT_COMPARABLE`입니다.

최종 frozen transfer는 모든 5 mutation + 2 control × 3 methods × 3 seeds의 63개 record를 요구합니다. 각 worker는 새 평가 대상의 정답·비공개 source를 받기 전에 64개 계획을 동결합니다. feedback·shrinking은 없습니다. 한 번의 exclusive ledger 생성이 해당 suite를 소비하며 오류·중단도 재튜닝/재실행의 근거가 되지 않습니다. 소스·원시 입력·정답·snapshot·ledger는 공개하지 않고 aggregate와 hash만 공개합니다. 이 blinding은 Generator에 대한 정보 차단이며 광범위한 실제 프로젝트 blind benchmark가 아닙니다.

## 개발 비교 결과

70개 method/run 기록을 모두 보존했습니다. 적용 가능한 실행은 완료됐고 E4의 미지원 15개는 별도입니다.

| 방법 | run / 비교 가능 | 고유 fault family | control 오탐 | 실제 Oracle | 전체 wall 합계(초) |
| --- | --- | --- | --- | --- | --- |
| E4 | 21 / 6 | 1 (지원된 정수 영역) | 0 | 275 | 10.583 |
| Hypothesis | 21 / 21 | 5 | 0 | 919 | 18.376 |
| E5 | 21 / 21 | 5 | 0 | 1,524 | 42.607 |
| CrossHair (source-aware) | 7 / 7 | 5 | 0 | 내부 UNKNOWN, concrete replay 7 | 5.755 |

E5/Hypothesis paired 15 fault runs의 wall 중앙 비율 2.660, 최초 발견 호출 비율 1.0입니다. 좁은 E4 stratum의 paired 3 runs는 wall 1.958 / first call 1.0입니다. 계약의 효율 개선 기준을 만족하지 않아 개발 판정은 **NO_IMPROVEMENT**입니다. 발견률 포화를 성능 향상으로 재해석하지 않습니다.

CPU는 evaluator process time과 worker process tree를 분리합니다. 평가기 계측은 PID/create-time별 마지막 CPU 표본의 합을 lower bound로 기록하고, RSS는 10ms 주기의 live-tree 합 표본 최대입니다. 짧게 생겼다가 관측되지 않은 프로세스는 빠질 수 있습니다. 서비스의 `worker_rss_bytes_at_freeze`는 peak가 아닙니다. 실행별 시간·호출·중복·자원 기록은 비공개 원본에 보존하며 public aggregate는 범위 밖 정밀도나 비용 청구 수준의 완전성을 주장하지 않습니다.

별도 440개 개발 입력으로 검사한 대표 후보 5개 중 2개가 반증됐습니다(둘 다 stable-dedup 계열). 후보가 없던 4계열을 포함하므로 2/5를 전체 제약 정확성으로 일반화하지 않습니다. 전이 gate **28/28**(양성 2 / 거부 26)은 선언된 typed/static 대응 검사입니다. clean counterevidence 5 records에서 반박된 가설 4개 제거 여부도 확인했으며, 하나의 반증으로 모든 경쟁 가설을 폐기하지 않았습니다. 결함 전이 정밀도는 UNKNOWN입니다.

개발 비교의 전체 축소 trajectory는 원래 per-run aggregate에 모두 보존되지 않아, 모든 반례의 축소량을 사후 재구성해 주장하지 않습니다. 새 실행부터 전체 algorithm receipt를 private로 보존합니다. 축소 기능 증거는 native Strategy 단위·통합 및 CLI 반례 재실행에 한정합니다.

## 최종 동결 평가

최종 once-only 63 runs는 **48 COMPLETE / 15 E4 NOT_COMPARABLE**, 오류·timeout 0, Generator feedback 0으로 끝났습니다. 판정은 **NO_IMPROVEMENT**입니다.

| 최종 방법 | 비교 가능 run | 고유 fault family | control 오탐 | 실제 Oracle | 전체 wall 합계(초) |
| --- | --- | --- | --- | --- | --- |
| E4-frozen | 6/21 | 1 (두 정수 영역) | 0 | 384 | 5.281 |
| Hypothesis-strategy-plan | 21/21 | 5 | 0 | 1,312 | 19.876 |
| E5-frozen | 21/21 | 5 | 0 | 1,344 | 30.815 |

15 paired fault runs에서 E5/Hypothesis wall 중앙 비율은 **1.540**, 최초 발견 호출 비율은 **1.0**입니다. 좁은 E4 1계열에서는 각각 3.636 / 5.0입니다. 생성 비용까지 포함했을 때 추가 효율이 확인되지 않았습니다. 최종 E5/Hypothesis process-tree CPU 표본 하한 합은 28.125/12.453초, live-tree RSS 표본 최대는 99,729,408/48,283,648 bytes이며 실제 OS peak나 과금 CPU는 아닙니다. 최종 두 방법의 run 내부 실패 입력 중복률은 모두 0입니다.

제품 40 files·source molds 27개·공개 fixtures·계약·새 private suite의 freeze SHA-256은 `3e143df698f7fcb2fde5dedfbce9622ba7fea6970c1364e38d18601059e71d8b`, 계약 SHA-256은 `290391f054213f7205c1121ceb4a6771d0c28b075d6b182ee0ff7738cc4368a1`입니다. 최종 결과 후 제품·평가기·대상·계약·mold 변경과 재실행은 0입니다. 문서·패키징·배포 준비만 이어갑니다. [공개 aggregate](E5_RESULTS.json) · [독립 평가 상세](E5_EVALUATION_REPORT.md).

## 검사·격리·배포 게이트

로컬 Windows/Python 3.12에서 **243 passed / 0 failed / 0 skipped**(17.965초). 기존 145개도 보존·통과했습니다. 새 검사는 실제 AST에 의한 선택 변경, 관측 후 Version Space·다음 query 변화, Z3의 실제 선택, native typed 생성·축소, 자료형·예외·상태 trace, 정당/부적당 전이, 평가 완전성·시간 초과, CLI 및 draft publication 실패 차단을 검사합니다.

부모 전송 전·worker 수신 후 strict field 검증, forbidden source/score/final-feedback의 transport 이전 거부, 동결 후 observe 거부를 실제 spy로 검사했습니다. 생성기 allowlist는 analysis·service·stateful·CrossHair symbolic·target·Oracle을 제외합니다. 직접 승인된 data-only IR은 허용하지만 raw target/Oracle source와 최종 정답은 보내지 않습니다.

기본 subprocess는 **LOGICAL_ISOLATION_ONLY**입니다. Docker는 network none / read-only root·code / uid 65534 / drop capabilities / no-new-privileges / 제한 메모리·tmpfs를 사용합니다. 로컬 Docker daemon은 사용 불가여서 실제 container access control은 정상 GitHub Actions 별도 job에서 검증합니다. 해당 job은 외부 서비스에 접속하지 않고 mount 밖 dummy sentinel·환경·UID·읽기 전용·network config를 실제 확인하고 E5+Z3 discovery도 실행합니다. 대상·Oracle은 여전히 신뢰된 호스트 코드입니다.

PR은 6개 Ubuntu/Windows Python 3.11/3.12/3.13 matrix와 기존 E4·E5 Docker jobs를 요구합니다. build·metadata·공개 범위·base/QA installed-wheel·기존 E4 smoke도 포함합니다. main CI의 8개 검사가 성공해야 release job이 annotated tag를 생성하고 draft의 wheel/sdist/SHA256을 다운로드 검증한 후 experimental prerelease를 공개합니다. 기존 tag/assets는 덮어쓰지 않으며 PyPI는 게시하지 않습니다. [보안 모델](../SECURITY.md) · [릴리스 노트](releases/v0.5.0a1.md) · [CI](../.github/workflows/tests.yml).

## 남은 병목

- 새 실제 프로젝트의 추가 가치·외적 일반화는 NOT_EXECUTED입니다. 새로 작성한 변형을 자연 발생 결함으로 계산하지 않습니다.
- native Strategy·solver·process startup 비용이 개발 비교에서 이득을 상쇄했습니다. 같은 최종 suite로 재튜닝하지 않습니다.
- bounded integer solver 밖의 복합 관계는 실제 Python 실행과 제한된 가설 문법에 의존합니다.
- arbitrary Python 의미·비정지 함수·적대적 대상 실행·임의 객체 상태·주관적 LLM 점수 검증은 제공하지 않습니다.
- 정적 대응과 예산 내 미반증은 correctness/causality/bug recurrence 증명이 아닙니다.
