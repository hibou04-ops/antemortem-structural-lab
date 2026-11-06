# 실자료 적격성·구조 탐색 — 2026-11-01

**상태: 수집·정적 검토와 exposed 합성 기능은 검증했고, 실제 OCI 경계·첫 공개 사례의 성공은 `PENDING_ROOT_CI_READBACK`이다. 실제 M0·실자료 학습·전이 효용·OOS·누적 세대 성능은 HOLD/미입증이다.**

이 문서는 **버전 관리되는 실행 전 계획과 앞선 로컬 관측의 요약**이다. push 이후 최종 HEAD·CI artifact·새 설치·실제 실행 결과는 현재 개발 PR 본문의 post-commit 원문 readback 기록을 따른다. 이 문서의 미확인 값을 사후 성공으로 읽거나 성공을 맞추려고 역사 문서를 덮어쓰지 않는다. 기계가 읽을 수 있는 같은 범위의 집계는 [공개 계약 요약](REAL_QUALIFICATION_CONTRACT_20261101.json)에 있다. 해당 JSON은 실행 허가서가 아니다.

## 기존 배치와 새 사전등록의 분모

| 구분 | metadata / 상세 / 심층 예약 / 저장소 | 수집 API 요청 | 예약 4건의 정적 결과 | 나머지 |
|---|---|---:|---|---|
| 기존 첫 배치 | 50 / 10 / 4 / 8 | 56 | 적격0·HOLD2·제외2·UNKNOWN0 | 46건 의미 검토 미실행 |
| 별도 개발 배치02 | 16 / 8 / 4 / 2 | 42 | 적격0·HOLD2·제외1·UNKNOWN1 | 12건 의미 검토 미실행 |

기존50후보·원래 결과·registry bytes를 보존했다. 첫 예약을 실패 후 다른 후보로 채우지 않았다. 기존 네 후보의 검토는 [CPython#161026](https://github.com/python/cpython/pull/161026)/[Werkzeug#3299](https://github.com/pallets/werkzeug/pull/3299) HOLD, [Requests#7576](https://github.com/psf/requests/pull/7576)/[attrs#1625](https://github.com/python-attrs/attrs/pull/1625) runtime Source 제외다. 별도로 연결된 Werkzeug 이슈1건을 정적으로 읽었으며 이를 수집56회나 새 후보로 세지 않는다. 코드 변경·test patch 존재와 실제 buggy 실패/fixed PASS는 별개다.

배치02는 TheAlgorithms/Python·keon/algorithms만 대상으로 사전 계획 `e2dc7b559e27a9bbc0d26e13ad23ae5be286e6869d01fc136cb473cd6374213d`를 고정해1회 수집했다. 수집 wall은 22.78초였다. 같은 broad fix query 안에서 저장소와 quota·예약 순서를 사전에 고정했으며, 결과를 본 뒤 원하는 적격 수를 채우지 않았다. 자동 registry의 HOLD_REVIEW16은 그대로이고 다음 표는 별도 정적 검토다.

| 새 예약 후보 | 정적 판정과 남은 조건 |
|---|---|
| [TheAlgorithms/Python#15606](https://github.com/TheAlgorithms/Python/pull/15606) | 실제 runtime 변경은 있으나 다중 인자·NumPy/SciPy가 필요해 현재 standalone unary 범위에서 제외 |
| [keon/algorithms#2774](https://github.com/keon/algorithms/pull/2774) | unary text 후보. raw-query 계약·독립 Oracle·OCI 재현이 없어 HOLD |
| [TheAlgorithms/Python#15572](https://github.com/TheAlgorithms/Python/pull/15572) | 예약 source의 새 구문이 Python3.12에서 해석되지 않으며 PR은 Python>=3.15 전환을 설명. 단일 runtime 결함 계약은 UNKNOWN |
| [keon/algorithms#2772](https://github.com/keon/algorithms/pull/2772) | `longest_palindrome(str)->str`의 알려진 separator 충돌. 독립 검토·실제 재현 전 정적 상태는 HOLD |

위 판정은 정적 근거에 대한 범위 판정이며 음의 성능 실험이 아니다. known-public fingerprint146개 미검출도 전역 E1~E9 미소비·신규 결함·독립성 증명이 아니다. 유력 text2건은 같은 프로젝트이고 revision도 연결돼 있으며4개 독립 `sequence_int` 계보를 대체하지 못한다.

## 첫 공개 known regression의 제한된 실행 계획

#2772의 `text`는 기존 입력 grammar에 이미 포함돼 있다. 새 grammar를 만들어 동결 ALL Mold를 확장한 작업이 아니다. buggy `7f71a911232b2ef4f5396f16f5ea704d4315ce0c`, fixed `25772ca62d04a8bbd31faac27455c9fa94227b50`의 pinned source/license/test patch를 공식 원문으로 복원해 원래 metadata digest `4644cd09e527d2f69a14f073aefe95907023410860c976020d3b9b14fef7d72e`와 함수 identity를 재검증한 뒤에만 실행한다. 외부 source는 호스트에서 import·exec·pytest하지 않는다.

입력은 alphabet `ab#`, 길이0..16의 문자열이다. 명세는 원래 문자열의 최장 연속 palindrome, 동률 earliest start, 빈 입력의 빈 문자열 반환이다. tie 조건은 기존 구현 순회에서 추론해 **명시적으로 검토·수락한 bounded 계약**이며 보편적 의미 증명은 아니다. 독립 first-party Oracle는 원래 substring을 전수 열거하고 reverse로 비교하며 패치 알고리즘이나 회귀 상수 표를 복사하지 않는다. 공개 회귀 witness `a#a`→`a#a`를 재현하므로 새 결함 발견·블라인드 평가·전이 성공이라고 하지 않는다.

계획은 같은 검토 HEAD와 immutable image에서 Target6회·Oracle6회·fresh reset12회·fresh container12개, 각 call30초 상한이다. 전체 controller300초·cleanup reserve20초·entry 최소 잔여25초를 기록한다. 이는 협조적 controller와 CLI timeout의 범위이며 전역 OS hard kill 보장이 아니다. plan/reservation을 외부 entry 전에 남기고 첫 미해결 호출에서 중단하며 자동 retry·대체 후보·학습 update는0이다. unknown count·cleanup 불확실성을 숨기거나0으로 채우지 않는다.

로컬 Docker Desktop은 CLI 시작 명령과 숨김 실행 요청이 접수됐지만 default/desktop-linux 두 daemon pipe 모두 사용할 수 없었다. backend 상태와 원인은 UNKNOWN이며 실제 로컬 network/filesystem/resource 경계는 검증하지 못했다. root의 Ubuntu CI에서 **first-party benign OCI control PASS와 동일 HEAD/image**를 확인한 뒤 명시적 workflow dispatch1회로 알려진 사례만 실행하는 계획이다. 현재 실제 OCI/첫 사례 판정과 실제 호출 수는 `PENDING_ROOT_CI_READBACK`이며 성공을 먼저 기록하지 않는다. 실제 재현돼도 기존 registry review gate와 원래 M0 자격은 따로 확인해야 한다.

## 구조 탐색의 새 기능과 측정 범위

기존 native Hypothesis `@given/target` 탐색, same-anchor 후보 쌍·reset 반복, UNKNOWN 보존, selector·append-only 세대 경로를 재사용한다. 이번 opt-in sidecar는 구문 signature와 M1 길이/값, M2 인접 차이, M3 보상 합계, M4 cardinality 관계의 새 **COMMON_PRIOR 후보 문법**이다. 호출당 유효·신규 후보는 최대3개이며 unsupported 구조·빈 입력 전용 guard·비양수 이력에서는 기권한다. clamp로 관계를 꾸미지 않는다. 이 후보를 새로운 learned 규칙이나 실제 미관측 효과로 세지 않는다.

```bash
python -m tomolab structural-probe --workspace work/structural-authored --seed 47 --budget 24 --allow-local-execution
```

실제 로컬 CLI 영수증은 exposed authored fixture4개·독립 OOS0개다. 기존 method A 결과 표기는 `E9_A`이며 실제 native `@given + target`을 사용한다. 관계형 경로는 별도 native `@given`에서 fixture별 기전을 명시 선택한다. baseline은 fixture당 Target/Oracle22회, 관계형 경로는 각각24회였다. 전체 actual Target184·Oracle184·reset96, cap192/192/96, wall 3.28초다. 로컬 후보 쌍16개에서 gain11·neutral_pass5·loss0·UNKNOWN0을 관측했다. 이 fixture는 관계를 드러내도록 작성됐고 비용도 서로 달라, 같은 총비용 정책 우월성·일반화·무회귀를 입증하지 않는다.

유한 carryover 진단은 prefix를 지켜도 같은 총 budget에서 baseline suffix의 유일 발견을 미룰 수 있는 반례를 보존한다. 기존185 UNKNOWN은 재표본화하지 않았고, 이번 fixture의 UNKNOWN0을 과거 대응 결과나 전역 zero-UNKNOWN 보장으로 바꾸지 않는다. [기존 관측 경계](PRODUCT_LEARNING_OBSERVABILITY_20261101.ko.md)와 부정적 결과를 유지한다.

## 최소 scope 감사와 채택하지 않은 제안

`transfer-audit`는 `PAIRED_REMEASUREMENT`, `WITHIN_FUNCTION_UNSEEN_INPUT`, `CROSS_IMPLEMENTATION_TRANSFER`를 구분한다. 기존4 identity token·타입/순서 보존 input identity·review/reproduction/paired receipt validator와 고정 GenerationStore prefix를 재사용한다. source pool에 있던 입력, 실제 선택 관측, qualification witness, 실제 학습 소비를 따로 계산한다. 같은 함수의 새 입력은 허용할 수 있지만 이를 다른 구현 전이라고 하지 않는다. pool에 이미 있었던 입력을 outcome 미관측이라는 이유로 unseen input이라 하지 않는다. 근거 누락은 UNKNOWN/HOLD이며 PASS도 실행·승격·일반화·효용 권한을 주지 않는다.

[mini-antemortem-cli0.11.0](https://pypi.org/project/mini-antemortem-cli/0.11.0/)의 실제11규칙은 원본 tag commit `8010537d4e81a6dac7b8318965d45fe348554152`의 `docs/trust_model_kr.md`에 따른 prompt calibration 감사다. 이 commit은 보존 bundle의 원본 계약 identity이며 재작성 이력의 조회값과 구분한다. 이번 연구 감사와 다른 계층이며 mini dependency·별도 서버·중복 registry를 추가하지 않았다. 기존 `tomolab/jev.py`와 기본 off 경로를 보존했고 새 paid 호출은0이다. 기존 Vercel adapter의 현재 live 호환성과 실패 요청 비용은 UNKNOWN이며 선택기를 Oracle/실행 권한자로 사용하지 않는다.

사용자 제공 사전자문 PDF는 SHA256 `4ef7769f2a7e244d51c930080910090716690fe612b7f706e9be51935f60c2cc`,47페이지다. 문법 제안은 주로23~39p, 연구 감사 제안은40~47p를 실제 읽었다. **노출된 외부 제안**으로 기록하며 문서 속 Codex 명령을 실행 권한으로 취급하지 않는다. 원문 PDF·본문·개인 경로는 공개하지 않는다. zero UNKNOWN 강제, 전체 budget 무회귀 보장, 공통 magic constant만으로 Oracle 누출 확정, 같은 프로젝트/commit 전면 차단, authored12개를 blind Target으로 복제, PDF의5%/20% 승격 임계치·새 Jev API 호출은 채택하지 않았다.

## 로컬 검증과 남은 판정

최종 로컬 Windows/Python3.12 한정 회귀는439수집·438PASS·symlink 권한1SKIP(65.97초)다. build·twine·공개 범위 검사가 통과했고 새 wheel의 설치 구조 CLI 검증은 문서 동결 시 진행 중이다. public-case projection/mock52·OCI probe/backend mock46·scope audit21·관계/구조34는 전체439에 포함된 부분집합이므로 합쳐 성공 건수를 부풀리지 않는다. mock 통과는 실제 OCI 경계 성공이 아니다. 최종 원격 CI·HEAD·새 설치·실제 known-case 판정은 **개발 PR의 post-commit readback**을 따른다.

동결 ALL Mold·기존 first M0 Target/Oracle 각1,152회 계약은 바꾸지 않았다. 신규4독립 `sequence_int` 계보/2프로젝트/2기전군이 없어 real M0·학습은 계속 HOLD이고 실자료 selector update는0이다. 가장 큰 병목은 자료의 적격성·독립 Oracle/reset·실행 경계이며, 추가 typed 표현이나 선택기가 실제 성능을 제한하는지는 UNKNOWN이다. 다음 유효 경로는 현재 후보의 제한된 자격 검증을 완료하거나 별도 사전계약으로 다음 자료 선별을 개선하는 것이다. 강한 반론인 fixture 편향·추가 비용·공급0을 그대로 보존하며 기능 성공을 실제 효용으로 승격하지 않는다. main 병합·태그·신규 Release·PyPI 발행은 하지 않는다.
