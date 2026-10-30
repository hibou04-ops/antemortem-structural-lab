# E8-R3 결과 — 실행 최적화와 연구 추가 가치의 분리

일반 실행의 중복 후보 생성을 제거했지만, 이번 새 Source 배치에서 B·C 대비 실용적 추가 가치는 입증하지 못했습니다. 기본 runtime 방법은 B이며 D는 명시적 연구 선택으로 유지합니다. R2의 `NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR` 판정은 변경하지 않았습니다.

## 실제 변경과 보존

`numerical_service.py`의 명시적 `verification_profile=runtime`은 주 생성 1회·기준 생성 0회입니다. `audit`의 D는 각각 1회이며 순서·입력·출처·recipe·transform·features·contract의 전체 의미를 비교합니다. 기본 인자가 없는 기존 D API와 기존 CLI는 R2 감사 수준을 유지합니다. A/B/C는 D 가이드 없이 동일한 clean worker와 엄격한 응답 검증을 사용합니다. C에만 승인된 재생 입력을 전달합니다.

기존 5개 worker module과 Source/Oracle, 기존 테스트 45파일, R2 동결·결과·계약, main의 수동 PyPI 발행 파일을 바이트 보존했습니다. 역사적 R2 157/165/167개 동결 inventory는 원 tree/revision에서 검사하고, R3의 새 165개 product 동결 기록을 별도로 작성했습니다. 현재 바이트로 과거 동결 해시를 덮어쓰지 않았습니다.

원본 archive 72,801,555바이트의 file SHA-256 `eb25d9d253f12fd989ebb216f1d18a007a55472ca284abb7a846b1d1dd7cdb44`를 확인했습니다. 실제 준비 시간은 17.0442초, 기존 archive 검증 2회·보정 2회(컴파일의 일치 확인 포함)·컴파일 1회이며, 기존 artifact digest `c5ac5b4d86a45eb4498af7123eeb928e3974165aa73f4b8202015f0de95a98ed`와 동일했습니다. 새 저장 bundle은 5,804바이트입니다. R2도 매 실행마다 전체 archive를 재생하지 않았습니다. R3 정상 실행의 실제 archive 처리 호출은 모두 0회입니다.

외부 host 승인 상태는 원본 content digest·validation version/코드·의미 버전·recipe/parameters·공개 계약·반증 상태·compiler bytes·schema·승인 artifact digest와 결속합니다. artifact 자체를 재해시한 것만으로 신뢰하지 않습니다. Source/Oracle 출력·후보 캐시·학습 worker·전송 제한 완화는 추가하지 않았습니다.

## Track1: 공개된 고정 작업의 소프트웨어 비용

실제 Source/Oracle 호출 0회인 직접 작성 callback으로 4개 seed×R2/runtime/audit 12회를 균형 순서로 실행했습니다. 후보 및 기존 평가 의미가 모두 동일하고 실제 생성 횟수는 2/1/2였습니다. 외부 process wall 중앙값은 R2 2.82666초, runtime 1.79208초, audit 2.83314초이며 runtime은 각 비교에서 4/4 블록 우세, 중앙값 약 36.6%/36.7% 감소였습니다. 사전 15% 감소·3/4 우세·품질 손실 0 기준을 통과했습니다. 작은 고정 workload의 구현 결과이며 통계적·외적 우월성을 의미하지 않습니다.

첫 판정기는 성공 enum `PASS_FULL_STRUCTURED_SEMANTICS`를 놓쳐 FAIL로 기록했습니다. 원본 실패·12행·파일 SHA를 보존하고 enum 어댑터만 수정해 같은 데이터를 재판정했습니다. 실험 재실행·임계값 변경은 0회이며 독립 감사로 확인했습니다.

## Track2: 새 Source 개발 검증

코드·레시피·예산·성공 기준·803개 공통 known digest를 결과 전 동결했습니다. 기존 424개, R2의 실제 평가 입력 362개, 후속 기능 검사 및 보수적인 공개 생성 입력 37개의 합집합이며 방법 실행 순서로 갱신하지 않았습니다. 새 seed 103/227/389/557/743/947, 길이 4/5/6, size32/max_examples512/pair_budget96/shrink16을 유지해 24회를 runtime으로 한 번 실행했습니다. 독립 블라인드 평가가 아닌 이미 관측된 Source의 새 입력 검증입니다.

| 방법 | 고유 새 유효 입력 | 고유 새 확인 실패 입력 | Source/Oracle 각각 호출 | Prepared 초 | 준비 1회 포함 Cold 소계·하한 초 |
|---|---:|---:|---:|---:|---:|
| A Native Hypothesis | 192 | 0 | 192 | 6.3882 | 10.3969 |
| B 공개 수치 사전지식 | 187 | 15 | 250 | 6.3889 | 10.3976 |
| C 동일 실패 자료 재생+변형 | 174 | 42 | 415 | 5.9542 | 9.9635 |
| D 보정 레시피+경량 worker | 192 | 73 | 379 | 7.1903 | 28.2450 |

각 방법 주 생성 6회·기준 생성 0회, 전체 24회이며 기존 기전 1개·새 기전 0개입니다. Oracle 오류·Target 오류·재현 불일치는 0입니다. Source/Oracle 총 호출은 각각 1,236회이며 단순 재생·fresh·확인 재현·native 축소·축소 재현을 별도 기록합니다. 방법별 고유 수를 전체 고유 수처럼 합산하지 않습니다.

Cold에는 공통 known 등록 비용 16.0349초를 각 1/4 배분하고 C의 검토 입력 검증, D의 원본 준비 및 준비 영수증 기록 비용을 추가했습니다. 등록 도구의 Source 호출 전 두 오류 비용도 공통 비용에 포함했습니다. API·guide load·직렬화·worker·Source·Oracle·재현·축소·run 영수증 write/flush와 공통 batch 관리 비용을 구분합니다. 고정 시간 checkpoint 1/2/4/8/16/32초의 누적 확인 입력 곡선을 결과 JSON에 보존했습니다. 최종 결과·공개 보고 파일 쓰기와 동결 전 관리 비용은 방법 시간 밖이며, 역사적 최초 수집 비용도 UNKNOWN입니다. Source 명령 전체의 process 시작·종료·최종 두 파일 기록 시간은 별도로 측정하지 못했고 0으로 두지 않습니다. 준비 CLI의 더 넓은 실측 경계에는 약 0.0589초가 추가로 있으며, 이 차이와 보정 소계를 파생 JSON에 별도 기록했습니다. 원형 결과와 사전 판정 자료를 수정하지 않았습니다. 표의 Cold는 현재 실행 비용까지 포함해 측정구간의 하한이며 완전한 총비용이 아닙니다. 누락된 공통 비용과 D의 추가 준비 비용은 B·C 대비 추가 가치 미입증을 뒤집지 않습니다.

사전 기준은 B·C 각각보다 고유 새 확인 실패 입력이 엄격히 많고 전체 실측 비용이 더 크지 않아야 합니다. D는 입력 수가 많지만 Prepared와 Cold 모두 비용이 커 `COLD_EFFICIENCY=NO_IMPROVEMENT`, `PREPARED_EFFICIENCY=NO_IMPROVEMENT`, `ADDED_VALUE_OVER_B/C=NOT_ESTABLISHED`입니다. 한 Source의 같은 기전 재현 수를 독립 결함 발견 능력으로 확대하지 않습니다.

## 검증·공개 상태

실제 명령은 [사용 안내](E8_R3_USAGE_KO.md)를 따릅니다. 초기 전체 717개 검사와 후속 신규 51개 focused 검사가 통과했습니다(중복을 합산하지 않음). 최종 전체 회귀·wheel 설치·원격 CI의 실제 수치는 PR Checks 및 최종 납품 보고로 확인합니다. 로컬 Docker daemon은 사용할 수 없어 정상 GitHub CI에서 실제 runtime/audit 컨테이너 검사를 수행합니다. host subprocess는 `LOGICAL_ISOLATION_ONLY`이며 컨테이너 경계로 표현하지 않습니다.

상태는 `RUNTIME_IMPLEMENTATION=COMPLETE`, `PUBLIC_WORKLOAD_COST_REDUCTION=OBSERVED`, `SOURCE_VALIDATION=EXECUTED`, `ADDED_VALUE_OVER_STRONG_BASELINES=NOT_ESTABLISHED`, `INDEPENDENT_CORROBORATION=NOT_AVAILABLE`, `EXTERNAL_GENERALIZATION=NOT_ESTABLISHED`, `PUBLICATION=NOT_AUTHORIZED`입니다. PR #8은 draft·`allow_release=false`; main 병합·새 tag·GitHub Release·PyPI upload는 모두 0입니다. PyPI `0.7.0a1` 및 기존 E7 자산·원본 Source·Drive는 변경하지 않았습니다.
