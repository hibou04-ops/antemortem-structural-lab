# Post-v7: M0 자격 검사와 reset 대칭

이 증분의 기준점은 병합된 `c8b640f9cf3dcbb266d6caaa4b3c50f230381139`이다. v8은 연구 기록의 동기화 버전이며 제품 Release 번호가 아니다. v5·v6·v7 원본, 기존 ALL Mold, first M0 Target/Oracle 각1,152 상한은 보존한다.

## 다음 관문과 선택

`POST_V6_TRIAGE_PARITY_20261101.ko.md:46,57`과 `RECURSIVE_PILOT_READINESS_20261101.json`의 다음 관문은 공통 입력 계약의 검토·재현된4독립계보/2프로젝트/2기전군이다. 기존 두 알고리즘은 같은 프로젝트이며 계약이 달라 이를 충족하지 않는다. 선택지는 새 자료 수집과 기존 증거의 자격·측정 경계 보강이다. 이번에는 추가 수집 없이 후자를 수행한다. 자격 검사 개선 자체로 자료 수나 탐색 효용이 증가했다고 해석하지 않는다.

## 구현과 실행 경계

`tomolab/discovery/m0_readiness.py:assess_m0_readiness`는 기존 candidate·review·reproduction의 원본 digest, 출처, 독립 Oracle/reset 검토, 실제 재현 영수증을 기존 validator로 재검증한다. 정확4개 후보, 동일한 입력 계약, 독립 단위·프로젝트·기전 수를 구분한다. 후보 중복·구현 bytes/정규화 AST clone·누락·변조·상이 계약은 HOLD로 보존한다. kind가 같다는 이유로 계약을 합치지 않는다.

`READY_FOR_PREREGISTRATION`은 별도 M0 사전등록 준비가 가능하다는 뜻이다. 실행 승인·registry 승격·실제 M0·성능·효용·OOS 증거가 아니다. 이 명령은 source를 import/exec하지 않고 Target/Oracle/reset/네트워크 호출과 registry 쓰기가0이다. HOLD는 CLI exit3, 자격 준비 완료는 exit0이다.

```bash
python -m tomolab m0-readiness --manifest frozen-material.json --output readiness.json --allow-reviewed-evidence
```

`tomolab/discovery/call_meter.py:HardCallMeter._evaluate_per_entry`는 Target·Oracle 각각 진입 직전에 검토된 reset을 호출한다. `tomolab/structural_probe.py`의 A/C 기준선과 관계형 경로가 모두 이 정책을 사용한다. 완료된 실행의 Target N·Oracle N에는 reset2N이 대응한다. Oracle 직전 reset 실패에서는 이미 수행한 Target 비용을 남기고 Oracle 진입을 막아 부분 측정/HOLD로 기록한다. 예외를 삼킨 재진입도 성공으로 복구하지 않는다. 비교 arm 사이 reset 정책이 다르면 거부한다.

이전 범용 계량기의 한 pair당 reset 기본값은 과거 API 호환 범위로 남지만 새 구조 probe는 해당 정책을 거부한다. 실제 reset callback의 True 반환과 counter 대칭은 보편적인 환경 초기화의 증명이 아니다. OCI는 기존의 fresh container당 실제1reset·1call 영수증을 유지한다. 이번 post-v7 CI는 알려진 두 외부 함수를 다시 실행하지 않는다.

상태 오염 반례와 재실행:

```bash
python -m pytest tests/test_reset_symmetry.py::test_shared_reset_false_pass_is_refuted_and_replayed_with_symmetric_resets -q
```

Target이 공유 상태를 바꾼 뒤 Oracle가 그 값을 읽으면 한 pair당 reset만으로 잘못 일치할 수 있다. 독립 reset 후의 Target1/Oracle0 차이를3회 동일 semantic digest로 확인한다. 이 반례는 작성된 기능 검증이며 새 실제 결함 발견으로 세지 않는다.

## 18 CI 실행 항목과 로컬 SKIP

`workflow_audit.py`는 체크인된15 job 정의·matrix 확장에 따른18 실행 항목의 조건과 file:line을 기록한다. 이는 실제 플랫폼 실행 결과와 별도다. `feat/post-v7-*` PR에는 기능4환경과 first-party OCI control1개를 실행하고 비대상13개를 건너뛴다. external qualification·연구·release 작업을 성공으로 표시하지 않는다. 새 브랜치 push/dispatch는 추가 실행 opt-in 없이 연구를 시작하지 않는다. publication workflow는 별도 명시 dispatch와 main gate를 유지한다.

로컬의 `test_harvester_adversarial.py:146`은 실제 dangling symlink 생성 권한이 없으면 SKIP한다. 설정·권한을 바꾸거나 모의 결과를 실제 symlink 검사로 표시하지 않는다. hosted Windows/Linux의 실제 검사와 로컬 capability 영수증을 구분한다.

전체 로컬 회귀·4환경 CI·원본 artifact 검증과 동기화의 최종 결과는 이번 PR의 완료 readback 및 별도 한국어 보고서에 기록한다. v7 수치와 이번 실행을 섞지 않는다. 알려진 witness 재현이나 작성 probe의 gain/loss는 실제 추가 탐색 효용을 증명하지 않으므로 M0 HOLD·utility/OOS NOT_ESTABLISHED를 유지한다.
