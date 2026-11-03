# Antemortem Structural Lab

<!-- QUICKSTART_DEMO_START -->
## 10초 시작 예제

```bash
pip install antemortem-structural-lab
uvx antemortem-structural-lab --help
python -m tomolab.quickstart_demo
```

동봉한 작성 예제로 실제 관측 비교기를 실행해 알려진 실패 입력과 수정 함수를 대조합니다. 이 출력은 재현 예제이며 자율 발견이나 완전한 정확성 증명이 아닙니다.

```diff
- [COUNTEREXAMPLE] point=0 actual=1 expected=0 confirmations=3
+ [PASS] fixed point=0 actual=0 expected=0
+ [PASS] replay matched all 3 failure observations
```
<!-- QUICKSTART_DEMO_END -->

**검토한 Python 함수·명시적 입력 계약·참조 Oracle로 실행하는 실험적 검증 도구**입니다. Hypothesis로 입력을 만들고 재현되는 불일치를 기록하며, 예산 안에서 반례를 축소하고 저장한 증거를 다시 실행합니다. 범용 Oracle를 제공하거나 프로그램의 완전한 정확성을 증명하지 않습니다.

[English](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/README.md) · [0.8 마이그레이션](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/MIGRATION_0_8.md) · [변경 이력](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/CHANGELOG.md)

## 패키지와 연구 범위

배포 메타데이터, `tomolab.__version__`, Git 태그를 **0.8.2 / v0.8.2**로 통일했습니다. 아래 명령으로 PyPI에서 설치합니다. 배포 식별자 통일은 연구 자격 승격이 아닙니다. `M0_HOLD`이며 효용·독립 OOS는 `NOT_ESTABLISHED`입니다. 과거 아티팩트의 버전·권한은 보존하며 이전 `0.8.0a1` 권한 문서는 별도로 보관합니다.

## C/D 혼합 예산과 음의 전이 방어

`method="D"`에서 `run_online`과 `OnlinePolicy`는 `epsilon_static_floor=0.5`를 노출하며 실제 호출 기준 워밍업의 기본값은 `circuit_breaker_warmup=6`입니다. 비학습 C는 별도 정책 인스턴스이며 native-base lane의 이름을 바꾼 것이 아닙니다. 전체 실행 예산 `B`에서 C에 `ceil(epsilon_static_floor * B)`회분을 예약하고 D는 나머지만 사용할 수 있습니다. Target과 Oracle에 각각 강제하며 확인·축소 호출도 포함하고 원래 arm에 귀속합니다. 두 arm에는 기존 replay/structure 전역 상한도 공유 적용합니다. 시간 제한이나 유한 입력 영역 때문에 예약분이 남을 수 있으므로 예약을 C의 실제 실행 완료량으로 주장하지 않습니다.

양쪽 arm의 워밍업이 끝난 뒤 D만 확인한 예외 phenotype이 0이고 D의 고유 phenotype 발견율이 C보다 낮으면 `circuit_breaker_triggered=True`가 됩니다. 호스트 HardCallMeter는 잔여 D 용량을 즉시 닫고 새로 생성하는 C 후보에 회수합니다. D의 모든 관측이 PASS이고 C에 세 번의 일치 실행으로 확인한 실패가 하나 이상이면, 고유 결함 수를 꾸며내지 않고 C 발견율의 양의 하한으로도 차단할 수 있습니다. `UNKNOWN`·부분 측정·식별 불가 또는 미확인 D 실패는 이득 0 판정을 막습니다. 워밍업 미완료는 `INSUFFICIENT_WARMUP`입니다.

지원하는 실패 서명은 세 번의 일치 실행 뒤 공개 계약과 예외 타입·위치를 사용합니다. 이는 관측한 phenotype이며 입증된 고유 결함이나 입력·출력 digest가 아닙니다. 반환값 불일치는 미분류로 남습니다. 영수증은 실제 C/D 진입·예약 용량·확인 phenotype·불확실성·차단 상태·회수 예산을 기록합니다. 거부된 D 제안에는 Target·Oracle·reset 진입이 없으며, D 작업의 이름만 C로 바꾸지 않고 C가 새 후보를 생성합니다.

작성한 세대 fixture는 실제 프로세스 재시작 뒤 통제된 슬롯에서 `common → learned → common` 선택을 계속 실행합니다. 해당 전체 mixed search에서 관측한 변경 가이드 실행 수는 `[0, 0, 0]`입니다. 통제 슬롯의 학습 선택 보존이 새 탐색에서의 사용이나 효용을 보장하지 않습니다. 엔지니어링 회귀 근거는 `M0 HOLD` 및 효용·외부 OOS `NOT_ESTABLISHED`와 별개입니다. 이번 변경으로 동결 연구 코호트를 재실행하거나 판정을 승격하지 않았습니다.

## 설치하고 작은 예제 실행하기

Python 3.11 이상이 필요합니다. **0.8.2**의 온라인 명령에는 `qa` extra를 설치합니다.

```bash
python -m pip install "antemortem-structural-lab[qa]==0.8.2"
python -m tomolab --help
python -m tomolab online-demo --workspace demo-work --usage-ledger demo-usage.jsonl --allow-local-execution --budget 24 --shrink-budget 6 --output demo-result.json
```

기본 방법은 **A: native Hypothesis 생성과 공통 관측·확인·축소 경로**입니다. 직접 작성한 이 데모는 입력 0에서 의도적으로 틀린 값을 반환합니다. A/B 데모는 Target과 Oracle만 실행하며 **Source 수집·학습을 하지 않습니다**. workspace·장부·출력에는 새 경로를 사용하며 기존 영수증은 덮어쓰지 않습니다.

배포 이름은 `antemortem-structural-lab`, import 이름은 `tomolab`입니다. `python -m tomolab`, `tomolab`, `antemortem-structural-lab` 별칭은 같은 CLI입니다. 다른 통합에 쓰는 `solver`, `analysis`, `corr` extra는 이 예제에 필요하지 않습니다.

검증한 CI 범위는 Windows·Linux의 Python 3.11–3.13입니다. macOS와 그 밖의 Python 버전은 이 검증 범위 밖입니다. `solver`는 지원되는 제한된 제약 검사에 Z3를, `analysis`는 선택적 CrossHair 비교 통합을 제공합니다. `corr`는 별도 상관계수 adapter용으로 Python 3.12 이상에서 선언한 SciPy/NumPy 버전을 설치합니다. 이 의존성이 범용 Oracle를 제공하지는 않습니다.

## 내 함수를 검사하고 증거 재현하기

동봉 예제를 새 디렉터리에 복사한 뒤 검토한 동기 함수와 독립적인 참조 모델로 교체합니다. 함수는 각각 **JSON으로 표현할 수 있는 입력 값 하나**를 받습니다. 예제 계약은 −8 이상 8 이하 정수입니다. Target의 입력 0 오류는 기능 확인용으로 넣은 결함이며 실제 프로젝트에서 발견한 결함으로 세지 않습니다.

`target.py`:

```python
"""Authored demonstration: deliberately wrong at zero; not a real project defect."""


def implementation(point: int) -> int:
    if point == 0:
        return point + 1
    return point
```

`oracle.py`:

```python
"""Explicit deterministic identity contract for the authored demonstration."""


def reference(point: int) -> int:
    return point
```

`contract.json`:

```json
{"kind":"int","low":-8,"high":8}
```

```bash
python -c "from pathlib import Path; from shutil import copytree; from tomolab.cli import EXAMPLES; copytree(EXAMPLES / 'product', Path('my-check'))"
python -m tomolab online-run my-check/target.py --oracle-file my-check/oracle.py --contract my-check/contract.json --usage-ledger my-check/usage.jsonl --allow-local-execution --budget 24 --shrink-budget 6 --output my-check/run.json
python -m tomolab online-replay my-check/run.json --source my-check/target.py --oracle-file my-check/oracle.py --contract my-check/contract.json --allow-local-execution --output my-check/replay.json
```

기본 함수명은 `implementation`과 `reference`입니다. 다른 이름은 `online-run --function`, `--oracle`로 지정합니다. 새 영수증은 검토한 파일과 계약의 identity를 연결합니다. replay는 연결을 확인하고 저장된 증거를 다시 실행하며 새 탐색을 하지 않습니다. 로컬 영수증에는 입력·출력·경로가 들어갈 수 있으므로 공유 전에 검토합니다.

`implementation = actual_function` 같은 별칭도 지원합니다. 새 영수증은 선택한 공개 이름을 기록하고, usage ledger는 callable 자체의 identity를 유지합니다. replay에서도 같은 선택 이름을 사용해야 하며 파일 해시와 binding digest 검사는 유지됩니다. 형식은 `tomolab-online-replay-binding-v1` 그대로입니다. callable 자체 이름을 기록한 구형 영수증도 읽을 수 있습니다. 기록된 이름을 `online-replay --function`으로 지정하고 Oracle도 별칭이면 `--oracle`를 지정합니다. 영수증 이름을 수정하거나 검사를 우회하는 방식은 호환 경로가 아닙니다.

Oracle는 **사용자가 명시한 기대 동작 모델**입니다. Oracle가 틀리면 불일치 보고도 잘못될 수 있습니다. 실제 명세·수치 허용오차·기대 예외·상태 초기화 정책을 유지하며 결과를 맞추려고 변경하지 않습니다.

### 여러 인자를 받는 함수 연결하기

import할 수 있는 모듈의 검토한 `legacy(left, right)`는 `target.py`에 입력 하나를 받는 wrapper를 작성합니다.

```python
from your_package import legacy


def implementation(point):
    return legacy(point[0], point[1])
```

입력 계약은 길이 2인 정수열로 고정합니다.

```json
{"kind":"sequence_int","low":-8,"high":8,"min_size":2,"max_size":2}
```

별도 `reference(point)`는 실제 명세에 따라 작성합니다. 이 wrapper는 두 인자를 대응시킬 뿐 Oracle를 자동 생성하거나 기존 함수의 정확성을 입증하지 않습니다.

## 지원 계약과 결과 해석

| kind | 제한된 입력 형태 |
|---|---|
| `int`, `float` | 선언한 수치 범위 안의 유한 값 |
| `sequence_int`, `sequence_float` | 해당 수치 타입의 JSON list |
| `text` | 선언한 문자 집합의 문자열 |
| `mapping` | 문자열 key와 정수 value |
| `state_trace` | `{ "op": ..., "value": ... }` 행동의 전체 list |
| `graph` | `{ "n": ..., "edges": [[from, to], ...] }` |

지원하지 않는 형태와 전제조건은 거절합니다. 임의 중첩 객체·비동기 함수·숨은 영속 상태·임의 Python 전체 의미는 이 계약 밖입니다. 순수 함수 또는 전체 입력 trace마다 상태를 새로 만드는 검토된 adapter를 사용합니다.

`run.status`, `run.outcome`, 오류 수, 확인·축소 기록을 함께 읽습니다.

| 결과 | 의미 |
|---|---|
| `CONFIRMED_FAILURE` | 기록된 Target/Oracle 불일치를 같은 결과의 실제 실행 세 번으로 확인했습니다. 결함 여부는 Oracle와 계약에 달려 있습니다. |
| `NO_CONFIRMED_FAILURE_WITHIN_BUDGET` | 이번 예산에서 확정된 불일치를 찾지 못했습니다. **정확성 증명이 아닙니다.** |
| `INCONCLUSIVE` | 한도·경계 실패·UNKNOWN·실행/Oracle 오류 때문에 확정할 수 없습니다. |
| replay의 `REPRODUCED` / `NOT_REPRODUCED` / `NO_CONFIRMED_FAILURE` | 기존 증거가 재현됐거나, 달라졌거나, 재현할 확정 실패가 없었습니다. |

`COMPLETE`는 실행을 끝냈다는 뜻이며 Target이 정확하다는 뜻이 아닙니다. 축소는 예산 안의 반례 감소이며 전역 최소성 증명이 아닙니다. 재현 불일치는 `INCONCLUSIVE`로 남깁니다. 현재 인자는 `online-run --help`, `online-replay --help`에서 확인합니다.

### 수치 허용오차와 정확한 0 비교

같은 타입의 유한한 0이 아닌 float 출력끼리는 `comparison.absolute`와 `comparison.relative`가 `math.isclose`의 `abs_tol`, `rel_tol`에 해당합니다. 판정식은 `abs(a-b) <= max(relative * max(abs(a), abs(b)), absolute)`이며 둘 다 기본값은 0입니다. 어느 한쪽 float가 0이면 허용오차와 관계없이 정확 비교가 우선합니다. `-0.0`과 `0.0`은 같습니다. 출력 타입이 다르면 불일치이며 지원하는 출력 컨테이너 내부에도 같은 규칙을 재귀 적용합니다.

예를 들어 `{"absolute":1e-6,"relative":0.0}`은 `1.0` 대 `1.000000001`을 수락하지만 `0.0` 대 `1e-9`는 거절합니다. `{"absolute":0.0,"relative":1e-6}`이면 `100.0` 대 `100.00001`을 수락합니다. 양의 절대 허용오차가 있어도 0을 포함한 비교에는 확장되지 않는 현행 계약입니다. 이번 패치는 설명만 추가하며 수치 의미나 과거 연구 판정을 바꾸지 않습니다.

### 예외도 비교 계약에 명시하기

Oracle의 일반 예외 타입이 전체 이름으로 `comparison.expected_exceptions`에 등록되지 않았다면 `ORACLE_ERROR`이며 확정된 Target 결함이 아닙니다. 명세가 정상 `ValueError`를 허용하는 경우에만 입력 계약의 `comparison`에 다음 객체를 넣습니다.

```json
{"expected_exceptions":["builtins.ValueError"],"exception_policy":"match_type"}
```

이 정책에서 Target과 Oracle가 같은 등록 타입의 예외를 내면 `PASS`이며 예외 메시지는 비교하지 않습니다. Oracle는 반환하고 Target만 예외를 내면 `FAILURE`로 관측하므로 사용자 코드와 계약을 검토해야 합니다. 호출 중 `MemoryError`, `ImportError`, `OSError`, `RecursionError`는 `EXECUTION_ERROR`로 분리합니다. 모듈 import·준비 단계 실패는 관측을 만들기 전에 종료될 수 있습니다. 둘 다 프로그램 결함을 정상 분류한 증거로 세지 않습니다.

## 선택 가능한 탐색 정책

| 방법 | 구성 |
|---|---|
| **A — 기본값** | native Hypothesis와 공통 관측·확인·축소 |
| B | 같은 native 기반과 공통 온라인 편집 정책 |
| C | B에 명시적으로 제공한 Source 입력 재생·일반 변형 추가 |
| **D — 명시적으로 선택하는 실험 옵션** | C 용량 예약·동결 Source 학습 D·호스트 서킷 브레이커를 갖춘 명시적 C/D 혼합 |

B/C/D는 `--method`로 선택합니다. C에는 입력만 담은 JSON list를 `--replays`로 줄 수 있습니다. D는 `--mold`와 별도로 승인한 `--expected-digest`도 필요합니다. `online-learn`은 검토한 Source 관측에서 Mold를 준비합니다. 명시적 C/D 데모는 기존 Source 준비 경로를 실행하고 비용을 기록합니다. D는 검증된 개선 방법이 아닙니다. 거부된 학습 제안은 D arm의 공통 fallback을 사용하며 전체 혼합 실행의 순서가 단독 C 실행과 같다는 뜻은 아닙니다. 손상 아티팩트는 오류로 처리합니다.

기존 MRI 코드 관측, CAST 실행 관측, Claim-to-Witness, Mold/Version Space, 수치·상태 명령은 `--help`에서 계속 사용할 수 있습니다. 각 기능의 제한된 계약은 별도 문서로 제공합니다. 온라인 인터페이스가 이를 범용 프로그램 검증기로 바꾸지는 않습니다.

## 기록된 연구와 한계

동결된 E9-R1 역사적 결함 비교는 프로젝트 3개, Source 결함 2개, Target 결함 6개, 수정본 대조 6개, 등록 실행 384회를 사용했습니다. 구현 전이에서 **A/B/C/D 모두 알려진 과거 결함 6개 중 5개를 재발견**했고 D는 C 대비 탐지·최초 확정 호출 이득이 없었습니다. 적격 empty-input leave-one-mechanism-out에서 학습 규칙을 실제 사용한 D는 두 예산 모두 0/6을 탐지했습니다. C는 예산 24에서 4/6, 48에서 6/6이었고 A/B는 두 예산 모두 6/6이었습니다. 작은 예산에서는 C도 A/B보다 손실이 있었습니다.

이는 음의 전이를 포함한 제한된 과거 결함 재발견입니다. 보편적 우월성·현재 upstream 배포판의 새 결함·독립 보강·외적 일반화를 입증하지 않습니다. 도구를 게시해도 연구 판정이나 최종 평가 readiness가 바뀌지 않습니다.

[역사적 결과·비용](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_REPORT_KO.md) · [전체 측정](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_RESULTS.json) · [기존 작성 예제 E9 보고서](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/ONLINE_REPORT_KO.md) · [이전 수치 결과](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/E8_R2_REPORT.md)

## 실행 경계와 라이선스

`online-run`, `online-demo`, `online-replay`는 신뢰한 로컬 Python을 import하고 실행합니다. `--allow-local-execution`은 동의이며 **OS sandbox가 아닙니다**. 별도 Generator process는 정보 접근을 제한하지만 악성 코드를 안전하게 만들지는 않습니다. 멈추지 않는 호출과 통제하지 않은 부작용은 협력적인 순수 함수 계약 밖입니다. 검토한 외부 역사적 캡슐에는 별도로 실제 설정을 검사하는 OCI/Docker 게이트가 적용됩니다. 로컬 동의 플래그로 우회하지 못합니다.

프로젝트 코드는 Apache-2.0입니다. 역사적 원문은 원래 MIT/BSD 라이선스를 유지하며 선택 의존성도 각각의 라이선스를 따릅니다. 비공개 연구 archive·원시 평가 자료·인증 정보·개인 저장소는 공개 패키지에서 제외합니다.

## 설치·실행 문제 해결

- **Hypothesis 또는 `qa` 누락:** 명령을 실행하는 interpreter에 `python -m pip install "antemortem-structural-lab[qa]==0.8.2"`로 설치합니다.
- **기존 workspace·출력 거절:** 이전 영수증을 보존하고 새 실행 경로를 사용합니다. 예제는 기존 파일을 덮어쓰지 않습니다.
- **지원하지 않는 함수 signature:** 동기 함수의 위치 인자 하나로 JSON 값을 받습니다. 여러 인자는 위 wrapper처럼 명시적으로 대응시킵니다. 이 파일 CLI는 async·generator 함수나 임의 callable 객체를 받지 않습니다.
- **예상 밖 실패·`ORACLE_ERROR`:** 불일치를 결함으로 판단하기 전에 독립 reference·domain·기대 예외·수치 비교를 검토합니다. 오류·UNKNOWN 수를 확인하며 예산 내 미검출을 정상 판정으로 해석하지 않습니다.

## 개발에 기여하기

소스 checkout의 개발 환경에서 실행합니다.

```bash
python -m pip install -e ".[qa,solver,analysis]" pytest build twine
python -m pytest -q
python -m build
python -m twine check dist/*
python scripts/check-public-scope.py
```

공개 범위 검사는 빌드 후 소스와 배포 파일의 내용을 검사합니다. 역사적 평가 배치와 검토된 외부 원본 캡슐은 일반적인 로컬 개발 테스트가 아니며 기존 실행·재소비 경계를 따릅니다.

[보안 범위](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/SECURITY.md) · [제3자 고지](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/THIRD_PARTY_NOTICES.md) · [역사적 실행 경계](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_USAGE_KO.md) · [기여 안내](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/CONTRIBUTING.md)

## 실험적 재귀 선택 정책

개발 paired 관측으로 후보 선택을 갱신하고 저장한 세대를 새 탐색에 적용하는 opt-in 기능은 [구현·검증·실행 예제](docs/RECURSIVE_PROGRESS_20261101.ko.md)를 참고하세요. `python -m tomolab recursive-demo --workspace work/recursive-example --allow-local-execution`은 작성된 합성 fixture만 실행합니다. 실제 효용·미관측 일반화·세대 성능 개선은 입증되지 않았으며 기본 정책은 자동 변경되지 않습니다.

## 제한된 GitHub 증거 수집

`python -m tomolab harvest-run --workspace work/harvest`는 공개 GitHub API에서 최대 50개 후보를 등록하고 검토 대기열을 만듭니다. 기본 동작은 외부 코드 실행과 학습을 포함하지 않습니다. 적격성·독립 Oracle·OCI 실행·재귀 API 연결 및 작성 fixture 예제는 [Harvester 사용·검증 기록](docs/HARVESTER_20261101.ko.md)을 따릅니다. 후보 메타데이터 수와 신규 고유 결함 수를 구분하며 실제 추가 효용은 미입증입니다.

## 실제 증거 자격과 구조적 후보 개발

기존 후보 의미 검토·실제 OCI control·공개 회귀 사례 재현·M1~M4 개발 후보·최소 전이 범위 감사는 [마일스톤 계약](docs/REAL_QUALIFICATION_20261101.ko.md)을 따릅니다. `python -m tomolab structural-probe --workspace work/structural --allow-local-execution`은 노출된 작성 fixture와 실제 Hypothesis만 실행하며 실제 전이 효용을 주장하지 않습니다. `python -m tomolab transfer-audit --manifest scope.json`은 자료 범위를 읽기 전용으로 감사하고 실행·승격 권한을 부여하지 않습니다. 실제 외부 함수는 별도 OCI control 및 명시적 실행 게이트가 필요합니다.
