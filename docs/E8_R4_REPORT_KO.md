# E8-R4 결과: 동결 가이드의 별도 구현 적용

## 판정

| 상태 | 확인한 범위 |
|---|---|
| FROZEN_GUIDE_PRESERVED | R3 guide·digest·Source-only scope·가중치·domain·생성기·worker·Oracle·기존 결과 보존 |
| IMPLEMENTATION_INDEPENDENCE | 고정 CPython/SciPy의 별도 코드·호출 경로 검토, 동일 correlation helper 호출 없음; CPython runtime 공유 |
| ORACLE_INDEPENDENCE | 대상 API와 다른 Fraction/Decimal 수학 경로; 공통 Oracle 한 계보이며 다중 독립 Oracle 아님 |
| CONTRACT_ADAPTER_VALIDATION | 실제 함수 진입·문서상 예외/경고/NaN·정확 퇴화·유한값 비교·권한 검사를 제품 테스트와 실제 실행에서 확인 |
| CORROBORATION_EXECUTION | 2구현×4방법×새6seed = 48회 완료, 결과 전 48계획 동결·실제 호출 0 확인 |
| CONFIRMED_CONTRACT_VIOLATIONS | CPython3.12.10의 상수 입력 유한값 반환 위반 확인; SciPy1.18.1은 예산 내 미발견 |
| ADDED_VALUE_OVER_B | 탐지 범위 추가 없음; 고정예산 D6/6 vsB3/6의 제한적 관측 이득; D 비용 증가 |
| ADDED_VALUE_OVER_C | 범위·고정예산 추가 이득 없음(C=D6/6); D 비용 증가·선지출 포함 최초 확인 지연 증가 |
| PREPARED_AND_COLD_COST | 두 child 전체 비용 합74.1105491초를 8개 구현/방법 그룹에 보존 배분; Cold는 과거 준비비 재사용 시나리오와 UNKNOWN 이력 구분 |
| QUALIFIED_KNOWLEDGE_STATUS | 자동 승격하지 않음; 원본 Source archive·반증 기록 변경 없음 |
| FINAL_TARGET_READINESS | CORR 소비 구현을 미소비 FINAL로 재등록하지 않음; 최종 블라인드 전이 미실행 |
| PUBLICATION_STATUS | draft·allow_release=false; main 병합·새 tag·Release·PyPI upload·Drive 쓰기0 |

결론은 **별도 구현에서 위반은 확인했지만 강한 재생 기준선 C보다 추가 발견 이득은 없었다**입니다. B 대비 고정예산 결과 차이는 별도로 보존합니다. 입력 수 증가를 독립 기전·결함 수 증가로 바꾸지 않습니다. 기존 R2·R3 판정도 소급 변경하지 않습니다.

## 고정 조건과 독립성

CPython3.12.10의 `statistics.correlation`, SciPy1.18.1의 `scipy.stats.pearsonr`와 NumPy2.5.3, Hypothesis6.170.11을 고정했습니다. 공식 고정 태그와 설치 모듈의 함수 AST·전체 text를 대조하고 SciPy/NumPy 배포 3,879개 파일의 RECORD 불일치·누락0을 확인했습니다. 실제 import 경로와 바이너리 hash는 로컬 검토 영수증에, 개인정보를 뺀 identity는 `E8_R4_IMPLEMENTATION_REVIEW.json`에 있습니다. RECORD는 서명이나 바이너리 원본 provenance 증명이 아닙니다. 기존 설치분포를 별도 환경으로 바이트 확인해 복사했으며 새로운 index 설치라고 보고하지 않았습니다.

Source의 Python 합산·중심화, CPython의 `fsum`/`sumprod`, SciPy의 NumPy 평균·norm 경로가 다릅니다. Oracle는 기존 정확 float 입력의 Fraction 중심화·Decimal 최종 sqrt 경로이며 대상 correlation API를 호출하지 않습니다. 다만 하나의 공통 수학 Oracle를 공유합니다. 이전 연구의 `statistics.pstdev` 사용은 있었으며 두 correlation 함수의 직접 수치 사용은 확인한 기록에서 발견되지 않았습니다. 전역 미사용 증명은 아니고 이번 CORR 사용 자체로 두 계보를 소비 기록했습니다.

Source public domain3~6을 공통 계약으로 유지하고 새 후보는 R3의 길이4/5/6을 유지했습니다. C의 원래 Source 반례 길이3 재생은 별도 phase에서 공통 계약으로 평가했습니다. 803개 공통 Source digest·원래 Source 반례5개·새 seed1103/1229/1367/1489/1613/1741, size32/max_examples512/pair_budget96/shrink16, 균형 순서와 1회 생성 runtime을 사전에 고정했습니다. C에 새로운 CORR 반례를 추가하지 않았습니다.

## 실제 결과

각 항목은 방법당6회입니다. 확인 입력 수는 고유 입력이며 기전 수가 아닙니다.

| 구현 | 방법 | 예산 내 확인 탐지 run | 고유 확인 위반 입력 | Target/Oracle 각각 | Prepared 초 | Cold 시나리오 소계 초 |
|---|---|---:|---:|---:|---:|---:|
| statistics3.12.10 | A |0/6|0|192|8.4351|8.4351|
| statistics3.12.10 | B |3/6|10|233|9.0978|9.0978|
| statistics3.12.10 | C |6/6|40|397|10.0185|10.0185|
| statistics3.12.10 | D |6/6|65|361|10.1982|18.7506|
| SciPy1.18.1 | A |0/6|0|192|8.6276|8.6276|
| SciPy1.18.1 | B |0/6|0|192|9.1080|9.1080|
| SciPy1.18.1 | C |0/6|0|282|8.9390|8.9390|
| SciPy1.18.1 | D |0/6|0|192|9.6863|18.2387|

실제 함수 진입은 statistics1,183회·SciPy858회·Oracle2,041회·원본 Source0회이며 원장과 일치했습니다. 모든 확인은 같은 입력의 초기 위반+2회 별도 동일 재현입니다. 정상화에서 clipping·NaN→0·Oracle 출력 대체를 하지 않았습니다. SciPy의 문서상 상수 경고+NaN과 statistics의 문서상 상수 예외는 결함으로 세지 않았습니다. Oracle 오류·재현 불일치·비교 불가0입니다.

전역 최초 확인은 **METHOD_C가 원래 Source 반례를 별도 구현에 재생한 경우**이며 run index2, 누적Target/Oracle 각각67회였습니다. 이를 D의 최초 독립 발견으로 보고하지 않습니다. 실행 child 함수 진입 후3.1603초, 이전48plan 비용을 더한 합산 지연60.4174초는 별도 수치이며 후자를 연속 wall clock이라고 하지 않습니다.

statistics에서 C는 모든 seed에서 Target/Oracle 각각3회에 최초 확인했습니다. D는3/31/7/3/14/3회, B는 미검출/null·21회·null·null·6회·31회였습니다. 미검출에 성공 시간을 대입하지 않았습니다. 선지출 plan+run event 지연은 C1.053~1.087초, D1.202~1.335초였고 함께 탐지한 B3개 seed도 B가 빨랐습니다. C는 이 비용 합산 지연에서6/6, B는 공통 탐지3/3에서 D보다 빨랐습니다. 평가 실행 부분만 보면 D가 일부 더 빠르지만 그것을 전체 최초 탐지 우위로 확대하지 않습니다.

D의 B 대비 Prepared 추가 비용은 statistics1.1005초·SciPy0.5783초, C 대비0.1797초·0.7473초였습니다. 작은 고정 workload의 설명적 측정이며 통계적 우월성·새 실행 순서에서의 보장으로 해석하지 않습니다. D의 고정예산6/6 vsB3/6은 이 범위의 별도 관측이고, C 대비 탐지 이득은 없습니다.

SciPy는 **NO_CONFIRMED_FAILURE_WITHIN_BUDGET**입니다. 문서에 맞는 정상 퇴화 관측을 Source 실패로 오인하지 않았습니다. 이 입력·예산의 미발견을 SciPy 전체 정확성이나 거푸집 학습 불가능성으로 확대하지 않습니다.

독립 기전 감사는 statistics 불일치 관측522개 모두에서 정확 상수의 분산0, `fsum(axis)/n`의 평균 반올림, 비영 중심화 잔차, 양수로 계산된 `sumprod` 분산과 유한 반환을 재구성했습니다. 기록된 반환과 모두 일치했고 확인한 CORR 기전은 **1개·구현/기전 쌍1개**입니다. 고유 확인 입력115개를115개 결함으로 세지 않습니다. 등록 배치 뒤 별도 fresh process의 직접 statistics3회·공유 Oracle1회 재현도 일치했습니다. 이 추가 호출과 Source의 기존 제공 진단 기능 재생1쌍은 정식48회·2,041쌍에 합산하지 않습니다. 다른 Python 버전·현재 upstream의 영향은 UNKNOWN이며 다른 프로젝트의 코드나 릴리스를 수정하지 않았습니다.

## 비용·증거 경계

계획 child57.2570866초와 평가 child16.8534625초, 합74.1105491초를 실제 parent stopwatch로 측정했습니다. import·guide validation·실제 generator subprocess·어댑터·Oracle·재현·축소·private/public 결과 fsync·child 종료를 포함합니다. 결과 후처리 원형 JSON을 보존하고 시작/최종쓰기/종료 잔여를 동일8그룹으로 배분한 파생 보고서로 비용을 결속했습니다. parent 영수증 자신의 쓰기와 문서·패키지·CI·독립 감사는 별도이며 중첩 구간을 합산하지 않습니다.

R4에서 guide 보정·컴파일은0회입니다. Cold는 **과거 R3 실측 준비비17.1048364초를 재사용한 시나리오**이며 이번 새 측정이라고 하지 않습니다. 실제 하나의 guide를 두 구현×D6회, 총12회 썼으므로 구현별 D에 절반을 배분했습니다. 과거 Source 최초 수집 비용은 여전히 UNKNOWN이며0이 아닙니다. 과거 비용의 기록 경계까지 포함한 완전한 역사적 총액을 주장하지 않습니다.

`FROZEN.json`은 여러 계획을 담은 host 감사 자료이며 worker로 통째로 보내지 않았습니다. 각 worker에는 기존 최소5module과 R3 compact 요청만 전송했습니다. 추가 import 진단328개 event에서 NumPy·SciPy·statistics·Source·평가 모듈 로드0을 확인했습니다. subprocess는 LOGICAL_ISOLATION_ONLY이며 OS 컨테이너라고 하지 않습니다. 기존 Docker 기능 검사는 CI에서 유지합니다. 역할별 에이전트는 같은 파일·도구를 공유하므로 역할 분리 자체는 접근 격리가 아닙니다.

## 제품·공개 상태

기존720개를 포함한812개 검사 오류·실패·skip0, Source/Oracle·R3 runtime/audit/validator·worker 바이트 보존, 설치 wheel의 실제 어댑터·CLI 경로를 확인했습니다. 정상 인덱스 설치와 OS별 회귀는 최신 PR CI의 실제 결과로 별도 보고합니다. [실제 실행 명령](E8_R4_USAGE_KO.md), [사전 계약](E8_R4_EVALUATION_CONTRACT.json), [공개 결과](E8_R4_RESULTS.json), [CORR 소비 이력](E8_R4_CORR_USAGE.json)을 참고하세요.

원시 반례·정답·개인 경로·대상 raw log는 로컬에 보존하고 공개하지 않습니다. 다른 프로젝트의 코드·계정·배포 설정·Drive는 변경하지 않습니다. CORR 결과는 유효성을 검토할 개발 증거이며 원본 Source-only guide를 전이 인증서로 바꾸거나 qualified 지식·새 미소비 FINAL·발행 권한으로 승격하지 않습니다.
