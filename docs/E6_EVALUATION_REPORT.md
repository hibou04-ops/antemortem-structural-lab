# E6 독립 평가 기록

공개 개발 판정은 **NO_IMPROVEMENT**, 최종 독립 평가는 **NO_IMPROVEMENT**다. 외부 실제 프로젝트 일반화는 **NOT_EXECUTED**다.

## 사전 계약과 범위

- 기준: `v0.5.0a1`, `f269ba9e11dc77e439cf840160c3ab081439e110`의 수정 없는 E5 runtime.
- 계약 SHA-256: `ba780d7c85669aef7f68b1c597a58d0290f10e7d54634c00f7968e2697018d8b`.
- 공개 fixture SHA-256: `9c476a940b9f154ef7b433bfe48f29789fa14e00561eac80c801941fb95cab27`.
- 평가기 SHA-256: `85ee99967badd0c5313c7669624d7ab5fb90d36a3602331674bb1d6e45be0b1b`.
- 새 scalar EFSM mutation 5계열·기존 정적 정상 대조군2개·seeds 13/47/89. 기존 E1~E5 소비된 holdout을 읽거나 재사용하지 않았다.
- 개발은 Native Hypothesis full strategy/find/shrink, 실제 RuleBasedStateMachine, E5, E6를 실행했다. CrossHair는 공개 source-aware 별도 tier다.
- 최종은 모든 Generator의 feedback을 차단한 native Strategy/RBSTMachine/E5/E6의 frozen plan 비교다. 실제 정상 절차로 한 차례만 실행한다.

## 공개 개발 결과

| 방법 | 비교 가능/전체 | 발견 계열 | 상태 run 발견 | 상태 primitive 호출 | 총 wall(s) |
|---|---:|---:|---:|---:|---:|
| CrossHair | 7/7 | 2 | 2/5 | UNKNOWN | 24.140 |
| E5 | 21/21 | 5 | 15/15 | 14906 | 42.301 |
| E6 | 21/21 | 5 | 14/15 | 3742 | 44.774 |
| NativeHypothesis | 21/21 | 5 | 15/15 | 8336 | 20.296 |
| NativeStateful | 15/21 | 5 | 15/15 | 15144 | 29.706 |

실행 가능한 black-box 정상 대조군의 오탐은0이며 Native Stateful의 정적 대조군6 runs는NOT_COMPARABLE이다. E6는 총5계열을 발견했지만 stateful 15 runs 중14개에서 발견했고, 세 강한 black-box 기준선은15/15였다. E6/Native Hypothesis paired 총 wall 중앙값 비율은2.514, E6/Native Stateful은1.352, E6/E5는1.071이다. 호출 수 감소를 실행시간 또는 검출 우위로 해석하지 않는다.

## Stateful Mold와 독립 후보 감사

- Source 15개 상태: HYPOTHESES_REMAIN13, OUT_OF_GRAMMAR1, NO_FAILURE_EVIDENCE1, INCONSISTENT0.
- 남은 temporal 관계가 있는 source는13/15개(실패 관측 source 중13/14개)이며 남은 관계 발생 수의 합은36이다.
- 실제 구조 가이드 질의는23회였다. Source에서 표현·가이드가 작동했다는 증거이며, 이 후보가 일반적으로 유효하다는 뜻은 아니다.
- 별도의320개 새 개발 trace에서 first-seed 후보13개 중12개가 반증됐다. 이 감사 결과의 Generator feedback은0이다. 결과를 보고 후보·grammar·예산을 조정하지 않았다.
- 정적 전이 gate25/25(기대 허용8·거절17), 실제 clean trace counterevidence 제거4/4는 기능 증거다. 반복 결함의 존재 또는 원인 정확도 증거로 해석하지 않는다.

## 실제 반례 축소

저장된 원본 영수증과 실패 기록을 대조했으며 추가 target/model 실행은0이다. Native Hypothesis는15/15 native shrink 완료·행동 수 중앙값8→3, Native Stateful은15/15 완료·5→3이었다. E6는 발견14개 중8개에서 더 짧은 시퀀스를 반환했고 중앙값5.5→4였지만,14개 모두62-transition shrink 예산에서 중단됐다. E5는15개 중11개가 짧아졌고 중앙값8→3이었다.

반환된 E6 반례14/14에서 최초 실패 행동의 semantic role은 유지됐다. 이는 관측한 행동 역할의 보존이며 원인 동일성이나 전역 최소성의 증명이 아니다. E6에서 native shrink가 완전히 끝났다고 주장하지 않는다. 모든 native status와 길이 비교는 공개 JSON에 있다.

## 최종 평가

| 방법 | 비교 가능/전체 | 발견 계열 | 상태 run 발견 | 상태 primitive 호출 | 총 wall(s) |
|---|---:|---:|---:|---:|---:|
| E5-frozen | 21/21 | 5 | 15/15 | 8722 | 38.320 |
| E6-frozen | 21/21 | 5 | 15/15 | 9486 | 42.748 |
| NativeHypothesis-frozen | 21/21 | 5 | 15/15 | 9402 | 19.945 |
| NativeStateful-frozen | 15/21 | 5 | 15/15 | 11758 | 26.318 |

최종 판정: **NO_IMPROVEMENT**. 전체84 records는78 COMPLETE·정적 Native Stateful6 NOT_COMPARABLE이며 오류·timeout·source drift와 실행 가능한 정상 대조군 오탐은0이다. 네 black-box 방법 모두 stateful15/15와5개 계열을 발견했다. 최종 feedback은0이고 ledger START/COMPLETE는각1이다.

동결 SHA-256: `869158af27ab3c928caa0edc00b2375be6de72e1d76ab67bff06b1e0245c97ff`.
- E6/NativeHypothesis-frozen: paired wall 중앙값비율2.321, 최초발견 실제상태 primitive호출비율0.445.
- E6/NativeStateful-frozen: paired wall 중앙값비율1.387, 최초발견 실제상태 primitive호출비율0.414.
- E6/E5-frozen: paired wall 중앙값비율1.123, 최초발견 실제상태 primitive호출비율0.615.

이름과 내부 표현이 다른 새 target에 대한 실제 temporal 가이드 후보는326개였고, 6 runs의 최초 witness가 가이드 후보에서 관측됐다. 이는 frozen 계획에 source 형상이 쓰였다는 실행 증거이며 기존 도구로 불가능했던 발견이나 인과적 우위의 증명이 아니다.

Source 개발비를 포함한 두 track 관측 wall은 E6 87.523s, Native Hypothesis 40.241s다. Source/final 변형을 서로 다른 결함으로 두 번 세지 않는다.

## 비용과 해석 한계

Primitive 호출은 실제 model+target 전이 callback의 합이다. 한 번의 whole-trace Oracle 함수 호출과 혼용하지 않는다. E6 native 개발128 전이+shrink62 전이, Native Stateful 최대1024 전이, Native Hypothesis 최대128 whole-trace predicate, E5 최대64 trace 후보+62 shrink predicate는 단위가 다르다. 독립 primitive/wall 상한과 실제 비용을 함께 공개했다.

총 wall은 import·프로세스·IR·생성·solver·version update·직렬화·Oracle·축소·재실행을 포함한다. 측정 가능한 component만 공개 JSON에 기록했으며 중첩되는 시간은 더하지 않는다. 미노출 단계는 UNKNOWN이다. CPU는 표본 process-tree 하한, 메모리는10ms live-tree 표본 최대이므로 OS true peak가 아니다.

이 평가는 새로 작성한 작은 scalar EFSM과 정적 정상 대조군의 소프트웨어 QA다. 다른 이름·내부 표현의 target variants는 같은 공개 API 의미 안에서만 비교한다. 기존 known-last-pop 회귀 해결을 신규 문제 전체의 grammar 해결이나 외적 일반화 성공으로 승격하지 않는다. 반례의 축소와 원인 증명·전역 최소성도 구분한다.

최종 소스·입력·정답·raw logs·source molds·ledger는 저장소 밖에 보존하며 공개하지 않는다. 로컬 subprocess 경계는 LOGICAL_ISOLATION_ONLY이고 실제 Docker 접근제어는 별도 CI 증거로 보고한다. 실제 측정 원본에서 만든 집계는 [E6_RESULTS.json](E6_RESULTS.json)에 있다.
