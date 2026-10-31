# 제품 실행 수정·검증 기록 — 2026-11-01

이 기록은 제품 패치 커밋 전의 로컬 실행 결과다. 원격 검증의 확정 결과는 draft PR의 `product-runtime-regression` checks와 각 `product-runtime-OS-Python` artifact에 연결한다. 미관측 연구의 성능 증거가 아니다.

## 시작 상태와 작업 경계

- 실제 GitHub `main`: `3ece4df3bd01abe6aae58ef8a01bf4b01515f689`, API readback으로 확인했다. 로컬 공유 저장소의 오래된 `origin/main` 캐시는 `3739e7d…`였으므로 시작점으로 사용하지 않았다.
- 기존 checkout은 `release/product-0.8.0a1`, HEAD `36196396533c74371fe8ce7885cb1ffb491894bd`, 미커밋 변경 없음이었다. 기존 checkout을 수정하지 않고 확인한 main에서 별도 worktree/`fix/product-runtime-diagnostics-20261101` 브랜치를 만들었다.
- 원격 저장소는 `hibou04-ops/antemortem-structural-lab`이다. 적용되는 별도 디스크 AGENTS.md는 없었고 사용자가 제공한 작업 지침을 적용했다. `pyproject.toml`, CONTRIBUTING, 영/한 README, 실제 두 workflow를 읽었다.
- 검증용 패키지 버전은 `0.8.0a1` 그대로다. 새 wheel/sdist는 로컬·CI 검증용이며 기존 공개 파일을 교체하거나 발행하지 않는다.
- 연구 보고서 revision `591f802…`, 연구 실행 revision `6cbe985…`, 제품 revision `3ece4df…`를 분리했다. 기존 동결 보고서·manifest·결과 파일은 변경하지 않았다.

## 제품 결함과 변경 파일

| 항목 | 원인·수정 | 유지한 계약 |
| --- | --- | --- |
| 정상 모듈 로딩 | `tomolab/cast.py`: 실행 전 `sys.modules` 등록, 실패 시 이전 등록 복구/새 등록 제거 | postponed annotations와 dataclass를 포함한 정상 모듈의 단일 동기 함수. 클래스 MRI·임의 객체 지원은 추가하지 않음 |
| 별칭 기본 재현 | `tomolab/online_cli.py`: callable의 자체 이름과 선택 export를 분리해 v1 binding에 선택 이름 저장 | 파일·계약 해시, 선택 함수명, binding digest, callable 기반 usage identity. 구형 own-name binding은 기록된 명시 이름으로 재현 |
| CP1252 도움말 | `tomolab/cli.py`: parser 도움말/진단에만 stream encoding 기준 안전 표현, MRI 설명은 `<->` | 전역 stdout 설정·JSON 출력·일반 실행 출력은 변경하지 않음. UTF-8 도움말 내용 유지 |
| 기여 환경 | `CONTRIBUTING.md`: 개발 `[qa]`, 선택 solver `[qa,solver]` | 기본 제품 의존성은 늘리지 않음 |
| 수치 비교 문서 | `README.md`, `README.ko.md`: 정확한 0 우선과 비영 float의 abs_tol/rel_tol 수식·예제 | `online_observe.py` 수치 의미·기존 연구 판정 변경 없음 |
| 회귀·설치 확인 | `tests/test_product_runtime_regressions.py`, `scripts/check-product-runtime.py` | 작은 작성 fixture만 실행. 기존 Source/Mold/역사 연구 실행 없음 |
| 안전한 CI 경로 | `.github/workflows/tests.yml` | 이번 접두사 브랜치의 PR에서는 제품 matrix만 실행. 다른 브랜치와 main의 기존 검증 조건은 유지 |

별칭 새 영수증은 `implementation`을 선택했다면 같은 이름으로 재현한다. 같은 callable이라는 이유로 `--function actual_function` 변경을 허용하지 않는다. 처음부터 actual_function을 명시한 별도 영수증의 명시적 재현과 구형 v1 callable-name 영수증의 기존 명시 재현 경로는 회귀 검사에 포함했다.

## 수정 전·수정 후 실제 로컬 실행

환경은 **실제 Windows / Python 3.12.10**이다. Linux 모사나 Python 3.11/3.13 결과로 바꾸어 표기하지 않는다.

| 확인 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 새 회귀 13개 | 4 실패·9 통과 | 13 통과·0 실패 |
| dataclass 실제 online-run | exit1, AttributeError | exit0, COMPLETE |
| 별칭 run / 기본 replay | run0 / replay2 | run0 / replay0, REPRODUCED |
| root 및 online-run 도움말 CP1252 strict pipe | 둘 다 exit1 | 둘 다 exit0 |
| 새 회귀+기존 제품 보호 검사 | 해당 없음 | 31 통과·0 실패·0 error·0 skip, Mold 학습을 하는 explicit_D 1개 제외 |
| 기여 환경 전체 테스트 수집 | 기존 감사에서 Hypothesis 누락 | `[qa]` 설치 후 1,109개 수집, exit0. 전체 테스트 실행이 아님 |
| 빌드·metadata | 해당 없음 | wheel/sdist 생성·twine check 둘 다 통과 |
| checkout 밖 새 환경 | 해당 없음 | wheel/sdist 각각 설치·pip check·import origin 확인, 총 2설치/36 subprocess checks PASS |
| 동결 자료 | 보존 baseline | 226개 역사 code blob과 기존 regression 60개 보존 검증 PASS |

CP1252 검사는 `PYTHONIOENCODING=cp1252:strict`, `PYTHONUTF8=0`, 실제 subprocess stdout pipe다. 그 검사에는 환경 설정을 무시하는 `-I`나 UTF-8 강제 옵션을 넣지 않는다. 일반 fixture 실행의 UTF-8 설정과 구분한다. 설치 검사에는 정상 모듈·별칭 기본/명시 재현·일반 A 탐색/재현·파일/함수 변경 거절·허용 예외·Oracle 오류·정확한 0/비영 허용오차 대조가 들어 있다.

실제 명령(환경 경로는 로컬 venv의 Python으로 대체):

```text
python -m pip install -e ".[qa]"
python -m pip install pytest build twine
python -m pytest --collect-only -q
python -m pytest tests/test_product_runtime_regressions.py tests/test_product_workflows.py -k "not explicit_D" -q --junitxml=product-regressions.xml
python -m build
python -m twine check dist/*
python scripts/check-product-runtime.py --output product-runtime.json
python scripts/check-historical-freeze.py --revision 591f802dea6f8ac88a27af3ffd89bd6e1396b318 --manifest docs/HISTORICAL_PROFILE.json --output historical-preservation.json
git diff --check
```

## 원격 제품 검증과 트리거 감사

요구된 설치 matrix는 Windows/Linux × Python 3.11/3.13 × wheel/sdist = 8조합이다. 로컬 3.12의 2설치는 이 8조합을 대신하지 않는다. 커밋 시점의 8조합은 `PENDING_REMOTE_CI`이며 실제 결과 JSON에서만 PASS로 판정한다. 각 matrix job은 두 패키지를 각각 새 venv에 설치하고 실제 import origin을 확인한다. Windows CP1252 결과와 Linux의 CP1252 simulation label을 나누어 기록한다.

기존 `tests.yml`의 PR 트리거에는 E4 실행, online Source learning, 역사 Source preflight 등이 있었다. 이번 브랜치에서 그 jobs가 실행되지 않도록 분기 조건을 넣고 제품 전용 job만 활성화했다. 발행 workflow는 main의 별도 수동 dispatch만 가능하다. push/PR 전에 실제 조건을 검토했고 이 작업에서 연구·발행 workflow dispatch를 하지 않는다. 원격 job readback으로 제품 job과 skip된 legacy job을 다시 확인한다.

기존 감사 run `41226721157`은 4개 job 모두 failure였고, 대조 run `41227258146`은 보존 자료 통합 job success였다. API로 확인한 이 두 상태는 서로 다른 작업의 상태다. 후자의 성공을 원래 제품 결함이 없다는 증거로 해석하지 않는다. 기존 공개 파일 해시/크기·기본 A·일반 재현·변경 거절·예외 분류의 통과 기록은 원래 감사에 보존하고 이번 새 검증과 구분한다.

로컬 일반 권한에서는 네트워크 조회와 새 venv의 ensurepip 하위 프로세스가 실패했다. 허가된 개발 의존성 설치·검증은 정상 실행 권한으로 완료했다. GitHub 연결 도구로 원격 상태를 읽고 branch/commit/draft PR을 만들며, 로컬 인증 토큰을 출력하거나 요구하지 않는다.

## 연구 상태·남은 주장

[관측 가능성 분석](PRODUCT_LEARNING_OBSERVABILITY_20261101.ko.md)과 [최소 후속 계약](MINIMAL_RECURSIVE_RESEARCH_CONTRACT_20261101.ko.md)은 기존 자료의 진단·설계다. 국소 대응 55/240의 이득0·손실8·중립47, UNKNOWN185는 전체 정책의 반사실 복원이나 신규 일반화 실적이 아니다.

제품 결함 수정과 알려진 손실 회귀 복구, 관련 경험의 추가 효용, 새 경험에 따른 정책 갱신, 다음 미관측 과제의 세대 개선은 별도로 판정한다. 이번 작업의 연구 Source 수집·Mold 재학습·역사 연구 재실행·신규 연구 Target 평가·최소 계약 실행은 모두0회다. main 병합·태그·Release·PyPI 발행·Drive/외부 정본/메모리 쓰기도0회다.
