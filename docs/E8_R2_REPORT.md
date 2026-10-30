# E8-R2 — 수치 실패 구조 기반 생성과 경량 실행

이 문서는 R2 구현과 Source 개발 검증을 별도로 기록합니다. **실패 입력을 그대로 저장하는 기능과, 실패가 발생한 수치 구조를 보존하면서 새로운 입력을 생성하는 기능을 구분합니다.** 공개 PyPI `0.7.0a1`에는 이 기능이 없으며 PR #8의 `0.8.0a1` 미발행 후보에서 사용합니다. [사전 고정 계약](E8_R2_CONTRACT.json)과 [실제 결과 JSON](E8_R2_RESULTS.json)을 함께 확인합니다. 계약의 `NOT_EXECUTED`는 실행 전 선언 시점의 상태이며, 동결 계약을 사후 수정하지 않고 이 보고서와 결과 JSON에 완료 결과를 기록합니다.

## 현재 상태

| 항목 | 상태와 확인 범위 |
|---|---|
| main 호환 | main `3739e7d`의 PyPI 수동 workflow·검증 스크립트·E7 자산 고정을 연구 브랜치에 통합. 최종 CI는 `PENDING` |
| Source 재현 | 고정 `omega-lock@14ff508b`의 검토된 `pearson_result`·필요 타입을 확인. 기존 실패 5개는 Python 3.11·3.12에서 같은 중심화 기전으로 재현 |
| 수치 입력 생성 | typed recipe·native Strategy・원본 반례에서 시작하는 native shrinking·CLI 연결. 동결 Source 비교 12개 run 모두 완료 |
| 경량 실행 | canonical 3,448바이트 가이드, 실제 요청 최대 33,899바이트. subprocess 실행·host 기준 후보 일치 확인. 전체 72,801,555바이트 archive는 host 전용, Docker CI `PENDING` |
| A/B/C/D 비교 | 고유 새 유효 입력 94/92/77/93개, 확인한 고유 새 실패 입력 0/15/24/44개. 모두 같은 기존 기전, 새 기전 0개 |
| B·C 대비 추가 가치 | `NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR`. D의 발견 입력은 늘었지만 준비 포함 비용 조건 미충족 |
| 독립 C·미소비 Target | 없음. 외적 일반화 `NOT_ESTABLISHED` |
| 제품 검사 | 전체 669개 회귀 통과, 실패·오류·skip 0, pytest suite 125.859초. 후보 wheel 설치·README 명령·원격 CI는 `PENDING` |
| 공개 상태 | 기존 draft PR #8 갱신 범위. `allow_release=false`, main 병합·새 tag·GitHub Release 미실행, PyPI upload 0회 |

Source 비교는 Python 3.12.10·Hypothesis 6.170.11에서 동결 후 한 번만 실행했습니다. 같은 배치의 결과를 본 뒤 코드·recipe·예산·판정 기준을 조정하거나 재실행하지 않았습니다. 설치·CI의 `PENDING`은 해당 검증을 통과한 것으로 간주하지 않기 위한 상태입니다.

## 확인한 Source와 계산 경로

고정 대상은 [omega-lock의 과거 함수](https://github.com/hibou04-ops/omega-lock/blob/14ff508b2974298305d74c1c90bb43d3c0c13b82/src/omega_lock/walk_forward.py)입니다. 원본 생산 코드는 수정하거나 배포하지 않습니다. 현재 배포된 `omega-lock`에 같은 문제가 있다고 이 과거 revision의 결과만으로 단정하지 않습니다.

Source는 `EMPTY`, `LENGTH_MISMATCH`, `ZERO_VARIANCE_X`, `ZERO_VARIANCE_Y`를 수치 결과와 구분하는 명시적 상태 계약을 갖습니다. 검토한 상수 입력에서는 정확 float 값의 중심 제곱합이 0이어도 `sum(values)/n`의 반올림으로 중심화 잔차가 남고, 계산된 제곱합이 양수가 되어 `== 0` 검사를 통과할 수 있습니다. 기존 비공개 실패 5개는 오른쪽 상수축의 이 경로로 재현되었으며 같은 1개 기전으로 셉니다.

사용자 `[0.1]*3`·`[0.25]*3` 진단은 사용자 제공 개발 단서입니다. Python 3.13.5의 이전 채팅 관측을 이번 환경의 실행으로 표현하지 않습니다. `[0.0,1.0,2.0]` 대조의 `2.0`은 기존 `[-1,1]` Source domain 밖이므로 별도 진단이며 주평가 관측에 넣지 않습니다. 상수 Pearson의 수학적 정의와 거의 상수 입력의 수치 문제는 [SciPy 공식 문서](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html)의 공개 지식입니다. 제품 판정은 고정 Source의 상태 계약과 기존 검증 Oracle을 따릅니다.

기존 Oracle의 정확 float 해석·정확한 0·epsilon·예외 정책을 변경하지 않습니다. 수치 비교는 기존 검토된 `FINITE_JSON` 어댑터의 절대 `1e-10`·상대 `1e-8` 허용오차와 bool·None의 정확 비교를 사용합니다. 기존 `EXACT_CANONICAL_JSON` 수집기의 출력 문자열 비교로 대체하지 않습니다.

## 레시피와 공정한 비교

`FailureGuidanceRecipe`는 실행 가능한 Python 코드가 아니라 엄격한 데이터 계약입니다. 출처·공개 계약·기전 가설·입력 특징·허용 변환·파라미터 전략·domain·비교 계약·반대 증거·개발 검증 상태·예산을 보존합니다. `HAND_SPECIFIED_PRIOR`는 개발자가 넣은 수치 사전지식, `SOURCE_CALIBRATED_GUIDANCE`는 실제 실패·정상 관측에서 보정한 배정, `OBSERVED_VALIDATION_RESULT`는 별도 배치의 실제 결과입니다.

공개 입력 특징은 축별 실제 float 동일성, 길이, spread·scale·ULP와 공개 산술 경로의 중심화 잔차입니다. 숨겨진 정답·Oracle 출력은 생성 특징으로 사용하지 않습니다. 실제 float 변환 후 같은 입력을 같은 digest로 처리하여 `0`과 `0.0`의 JSON 표기 차이를 새 탐색으로 세지 않습니다. 수학적 불변관계가 float에서도 비트 단위로 유지된다고 가정하지 않으며 변환 결과를 다시 domain·Oracle로 검사합니다.

| 방법 | 제공 자료와 실행 |
|---|---|
| A — Native Hypothesis | 기존 형식 범위의 native typed Strategy. D recipe 없이 동일한 최소 생성 process에서 실행 |
| B — Domain-Informed Hypothesis | D와 동일한 공개 상수·중심화·표현 지식과 6개 전략 family. D recipe를 받지 않고 실패 라벨로 배정을 보정하지 않음 |
| C — 반례 재생 + 일반 변형 | D와 같은 기존 실패 입력만 bounded 데이터로 전달. 알려진 재생과 부호/스케일·길이·순서·인접 값의 일반 변형을 구분. Oracle 출력·라벨은 제외 |
| D — Source 보정 + 경량 worker | 같은 공개 family를 사용하고 413개 기존 Source 관측으로 배정만 보정. host 예상 digest에 결속한 경량 가이드를 worker에서 실행 |

현재 보정 자료는 실패 5개, 정상 408개입니다. 오른쪽 상수·중심화 잔차 family의 가중치는 16, 나머지 family는 1입니다. 이 규칙은 Oracle 정답이나 충분조건이 아닙니다. B·C 대비 추가 가치가 없으면 이를 그대로 보고하며 A보다 낫다는 사실만으로 지식 엔진의 독립적인 가치를 인정하지 않습니다.

새 배치는 길이 4·5·6, seed 13·47·89, 방법/seed별 후보 32개·draw 최대 512개·실제 Source/Oracle 쌍 최대 96개·축소 predicate 최대 16회로 고정했습니다. 재현과 축소도 같은 쌍 예산을 소비했습니다. 코드·recipe·예산·판정 기준을 최종 배치 전에 고정한 뒤 실행했으며 결과를 보고 같은 배치를 반복 최적화하지 않았습니다. 기존 371개·R1의 42개·사용자 진단 등 이미 관측된 개발 입력은 고정 known 집합 424개로 제외했습니다. 길이·표현·변환 축을 명시한 같은 Source 검증으로, 새 블라인드나 독립 프로젝트 일반화가 아닙니다.

값 축은 범위 내 일반 binary64, 분자 -16~16·2진 지수 -12~-4, 분자 -9~9·분모 10/100/1000의 decimal 생성, 선택적 1회 nextafter와 정확 표현 가능한 0.125/0.25/0.5 정상 패턴입니다. C는 동일 실패 입력의 반복/잘라내기·회전/뒤집기·축 교환과 2진 지수 -4~0의 일반 변형을 사용합니다. 이 축이 과거 모든 관측에서 미소비였다고 주장하지 않습니다. 실제 입력의 신원과 신규성은 알려진 입력 digest 제외 및 첫 실제 평가 기록으로 판정합니다.

## 경량 실행과 비용

전체 archive는 host에서 기존 `KnowledgeArchive.from_snapshot` 규칙으로 검증합니다. compiler가 실제 Source 관측에서 레시피를 재보정해 동등성을 확인하므로, 임의 counts를 넣고 파일 해시만 다시 계산한 레시피를 승인하지 않습니다. 실행 가이드는 원본 archive digest·의미 버전·승인 recipe·공개 입력 계약·반대 증거 상태·compiler 버전과 host 승인 영수증에 연결됩니다. 예상 digest는 실행 가이드와 별도로 보관합니다.

현재 실제 Source 가이드는 canonical 3,448바이트, 원본 archive는 72,801,555바이트입니다. 최초 정식 컴파일 측정은 16.9067524초이며 연구 성능 수치가 아닙니다. D 가이드에는 archive 원본·모든 중복 증거·Oracle 출력·비공개 원시 입력·최종 평가 라벨·개인 경로·임의 코드 문자열을 넣지 않습니다. C의 단순 재생·일반 변형 기준선에는 같은 기존 실패 입력을 별도 bounded 요청으로 전달합니다. 이 요청은 D 가이드와 구분하며 Oracle 출력·라벨·전체 archive를 포함하지 않습니다. 가이드 자체 1MiB, C 입력을 포함한 전체 요청 8,000,000바이트를 넘으면 실패 처리하며 한도를 올리지 않습니다.

실제 동결 비교의 알려진 입력 digest 424개를 포함한 최대 요청은 33,899바이트였습니다. 모든 run에서 가이드가 유지되었고 원본 archive의 해시도 보존했습니다. 이 측정은 subprocess 실행 경로의 증거이며 Docker CI의 실행 증거와 구분합니다.

worker에는 생성에 필요한 검토된 최소 모듈만 복사합니다. host 기준 후보 역시 평가자 process 내부에서 만들지 않고 같은 모듈 집합의 별도 최소 process에서 생성합니다. 같은 seed·Python/Hypothesis 버전·모듈 문맥·입력 계약을 사용하여 그 기준 후보와 실제 worker 후보를 비교하고 plan 이후 변경·학습·파라미터 교체를 차단합니다. `subprocess`는 host의 논리적 경계이며 OS 격리가 아닙니다. Docker의 실제 파일 접근·network·코드 쓰기·동결 검증은 이 경량 가이드로 수행하고 별도 영수증을 남깁니다. 전체 70MB archive의 Docker 검증으로 표현하지 않습니다.

### 숫자 상수 문맥의 영향과 수정

최종 Source 검증 전에 host/worker 후보 불일치를 조사했습니다. Hypothesis 6.170.11의 native float Strategy가 `sys.modules`에 있는 모듈의 AST에서 숫자 상수를 수집하는 경로가 있어 평가자와 최소 worker가 다른 상수 문맥을 갖게 됩니다. 공개 상수 `0.01`을 가진 로컬 모듈 하나를 import하는 대조에서도 후보 차이를 확인했습니다. 이 원인 대조의 Source·Oracle 호출은 0회이며 실제 결함 발견·Source 성과에 포함하지 않습니다.

수정은 Hypothesis 내부를 패치하거나 evaluator의 상수를 worker에 복사하는 방식이 아닙니다. A·B·C·D 모두 검토된 동일한 허용 모듈만 복사한 새 생성 process에서 시작하고 평가자·Oracle·대상·대형 archive 모듈을 import하지 않습니다. A·B에는 D의 Source 보정 레시피를 전송하지 않습니다. C에는 같은 기존 실패 입력만 전달하여 기준선의 재생·변형 자료를 맞추며 Oracle 출력·라벨은 제외합니다. D에는 원시 실패 입력 없는 경량 recipe만 전달합니다. 같은 최소 코드에 포함된 공개 숫자 상수의 native 활용은 모든 방법이 공유하며 A에도 이 라이브러리 동작이 적용될 수 있음을 인정합니다.

따라서 결정적 재생의 확인 조건은 seed 단독이 아니라 고정된 Python·Hypothesis 버전, 복사한 모듈 집합과 바이트, 입력 계약 및 모든 전략 파라미터입니다. 다른 버전·import 문맥에서도 후보가 일치한다고 확대하지 않습니다. 각 방법의 독립 생성 process 시작·직렬화·요청·응답 비용을 측정하며, D의 host 기준 대조를 추가로 실행한 비용도 포함합니다. 이 수정과 관련 검사는 최종 개발 배치 전 코드·계약 동결에 반영하며 비교 결과를 본 뒤 정책을 조정하지 않습니다.

후보 생성·직렬화·worker·Source·Oracle·축소·재현 비용과 최초 새 실패까지의 시간/실제 호출을 구분합니다. 수집·학습·컴파일의 측정 준비 비용을 포함하고 archive 재사용 시의 추가 비용도 기록합니다. 최초 역사적 수집비용은 `UNKNOWN`이며 0으로 가정하지 않습니다. 새 실패 입력이 여러 개여도 같은 계산 경로이면 기전 1개입니다.

## 실행 경로

아래 명령은 PR #8의 연구 checkout 또는 별도로 설치한 후보 wheel에만 해당합니다. 출력 파일이 이미 있으면 새로운 폴더를 사용합니다. 동봉 기능 예제는 사용자에게 제공된 공개 진단을 사용하는 작은 archive이며 비공개 전체 자료를 배포한 것이 아닙니다.

```powershell
python -m pip install ".[qa,solver]"
python -m tomolab numerical-demo --workspace results/r2-functional --budget 16 --size 4 --max-examples 128 --output results/r2-demo.json
python -m tomolab numerical-prepare --archive results/r2-functional/archive.json --output results/r2-prepared.json
python -m tomolab numerical-compile --archive results/r2-functional/archive.json --recipe results/r2-prepared.json --output results/r2-compiled.json
```

`numerical-compile`의 단일 JSON 출력에서 실행 가이드·승인 영수증·별도 예상 digest 파일을 새 폴더로 꺼냅니다. 다음 명령은 실행 코드를 생성하지 않고 검증된 JSON 구성요소만 저장합니다.

```powershell
python -c "import json,pathlib; p=pathlib.Path('results/r2-recompiled'); p.mkdir(); v=json.loads(pathlib.Path('results/r2-compiled.json').read_text(encoding='utf-8')); (p/'guide.json').write_text(json.dumps(v['artifact']),encoding='utf-8'); (p/'approval.json').write_text(json.dumps(v['approval_receipt']),encoding='utf-8'); (p/'guide.sha256').write_text(v['artifact']['artifact_digest']+'\n',encoding='ascii')"
python -m tomolab numerical-inspect --guide results/r2-recompiled/guide.json --approval results/r2-recompiled/approval.json --expected-digest-file results/r2-recompiled/guide.sha256 --output results/r2-inspect.json
python -m tomolab numerical-run --guide results/r2-recompiled/guide.json --approval results/r2-recompiled/approval.json --expected-digest-file results/r2-recompiled/guide.sha256 --method D --allow-local-execution --budget 16 --size 4 --max-examples 128 --output results/r2-run.json
python -m tomolab numerical-compare --guide results/r2-recompiled/guide.json --approval results/r2-recompiled/approval.json --expected-digest-file results/r2-recompiled/guide.sha256 --replays results/r2-functional/replays.json --allow-local-execution --budget 16 --size 4 --max-examples 128 --output results/r2-comparison.json
```

이 명령의 비교는 공개 기능 예제 검사입니다. 최종 개발 배치 성과로 계산하지 않습니다. 검토된 실제 개발 입력 목록은 `--known-inputs`로 받아 Generator에는 제외 digest만 전달합니다. `--replays`의 같은 실패 자료는 C 기준선에만 bounded 입력으로 전달하며 Oracle 출력·라벨은 보내지 않습니다. A·B에는 D recipe를 전송하지 않고 D에는 원시 실패 입력을 전송하지 않습니다. `numerical-demo`에서 `--workspace`를 생략하면 동봉된 실제 Source 가이드를 재사용하여 비공개 archive 없이 기능 실행 경로를 확인합니다.

후보 wheel을 별도 환경에 설치할 때는 build한 정확한 미발행 파일을 지정합니다. 다음 경로의 wheel이 존재하는지 먼저 확인합니다. 공개 PyPI 버전을 교체하거나 같은 버전으로 재게시하는 명령이 아닙니다.

```powershell
python -m build
python -m twine check dist/*
python scripts/check-public-scope.py
python scripts/check-wheel.py
python scripts/check-wheel.py --qa
python -m venv results/r2-installed-env
results/r2-installed-env/Scripts/python.exe -m pip install "dist/antemortem_structural_lab-0.8.0a1-py3-none-any.whl[qa,solver]"
results/r2-installed-env/Scripts/python.exe -m pip check
results/r2-installed-env/Scripts/python.exe -m tomolab numerical-demo --budget 16 --size 4 --max-examples 128 --output results/r2-installed-demo.json
```

Linux 환경에서는 venv의 `Scripts/python.exe` 대신 `bin/python`을 사용합니다. 이 문서의 실행 명령은 최종 설치 검증 영수증으로 확인하기 전 통과로 보고하지 않습니다.

## 최종 개발 비교 결과

| 방법 | 고유 새 유효 입력 | 확인한 고유 새 실패 입력 | 재현 기전(신규) | Source/Oracle 호출 | 측정 준비 1회 포함 비용(초) |
|---|---:|---:|---:|---|---|
| A | 94 | 0 | 0 (0) | 96 / 96 | 2.83759 |
| B | 92 | 15 | 1 (0) | 144 / 144 | 2.95153 |
| C | 77 | 24 | 1 (0) | 212 / 212 | 3.37563 |
| D | 93 | 44 | 1 (0) | 203 / 203 | 23.54118 |

표의 입력 수는 **동결 known 집합에 포함되지 않은 생성 입력을 각 방법 안에서 seed 간 union한 수**입니다. 방법 간 동일 입력은 각 방법의 독립 비교에 그대로 포함하므로 이 열을 합쳐 전 배치의 실제 첫 평가 수로 사용하지 않습니다. C의 seed별 확인 실패 합계는 26개이나 고유 입력은 24개입니다. B·C·D의 방법별 실패 수 합계 83개도 방법 간 중복 1개를 포함하며 전 배치 고유 확인 실패는 82개입니다. 전 배치에서 방법 간 중복과 축소를 고려한 실제 첫 유효 입력 평가는 357개였으며, 실행 순서에 따라 A/B/C/D에 94/95/78/90개로 귀속됩니다. 이 사후 중복 집계는 생성이나 기본 방법 비교에 피드백하지 않았습니다.

실제 Source 호출과 Oracle 호출은 각각 655회, 합계 1,310 primitive 호출입니다. C의 알려진 입력 replay는 45쌍이며 새 입력 탐색으로 세지 않습니다. domain 거절은 A/B/C/D에서 54/2/15/24회, Oracle 오류·Target 오류·재현 불일치는 모두 0회입니다. 입력이 여러 개 나와도 확인된 경로는 `CONSTANT_CENTERING_ROUNDOFF_MISCLASSIFIES_DEGENERACY` 1개이며 신규 기전은 0개입니다.

추가 가치 판정은 **`NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR`**입니다. 사전 기준은 B·C 각각보다 확인된 새 실패 입력이 많으면서 측정한 준비 포함 전체 비용이 더 크지 않은 것입니다. D는 B 15개·C 24개보다 많은 새 실패 입력 44개를 만들었지만 비용이 두 기준선보다 커 B·C에 대한 종합 기준을 모두 충족하지 못했습니다. A보다 발견이 많다는 사실을 가이드의 독립적인 추가 가치로 승격하지 않습니다. 이는 기능이 새 입력을 생성하지 못했다는 뜻이 아니라, 이 개발 배치와 고정 비용 기준에서 종합 이득을 입증하지 못했다는 뜻입니다.

### 비용과 최초 새 실패

현재 실행 비용과 한 번의 측정 준비 비용은 다음과 같습니다. D의 host 기준 후보 대조도 실제 실행 비용에 포함했습니다. 생성·Oracle·재현·축소의 세부 phase 중 일부는 포함 관계이므로 별도 열을 단순 합산하지 않습니다.

| 방법 | 현재 실행(초) | 한 번의 측정 준비(초) | 합계(초) |
|---|---:|---:|---:|
| A | 2.83759 | 0 | 2.83759 |
| B | 2.95153 | 0 | 2.95153 |
| C | 3.09285 | 0.28278 | 3.37563 |
| D | 6.63443 | 16.90675 | 23.54118 |

준비 완료 archive를 재사용한 이 비교의 D 추가 실행 비용은 6.63443초였습니다. 역사적 최초 수집비용은 `UNKNOWN`이며 위 표는 수집부터 전체 연구 이력까지의 총비용을 측정한 것이 아닙니다. 측정하지 못한 비용을 0으로 간주하거나 경제적 ROI를 주장하지 않습니다.

| 방법 | seed 13·47·89의 최초 새 실패까지 primitive 호출 수 | 같은 seed의 준비 포함 cold 시간(초) |
|---|---|---|
| A | 미검출 / 미검출 / 미검출 | 미검출 / 미검출 / 미검출 |
| B | 미검출 / 8 / 44 | 미검출 / 1.00652 / 0.94980 |
| C | 38 / 36 / 38 | 1.21206 / 1.20927 / 1.20829 |
| D | 24 / 14 / 6 | 19.12815 / 19.10664 / 19.04518 |

cold 시간은 영수증에 기록된 준비 포함 정의를 따릅니다. 표의 세 cold 시간을 합쳐 한 번만 수행한 준비비를 세 번 발생한 실제 총비용으로 계산하지 않습니다. 단일 Source·작은 고정 배치·정해진 실행 순서의 관측이며 통계적·보편적 우월성을 입증하지 않습니다.

### 실제 반례 축소 결과

실제 최초 실패에서 시작한 `INITIAL_WITNESS_TRANSFORMS` 8개 run은 native 탐색·축소를 완료했고 결과를 각각 두 번 재현했습니다. 축소 predicate 호출은 총 40회, 별도 축소 결과 재현은 16쌍이었으며 위 655쌍에 이미 포함되어 있습니다. 모든 결과가 `initial_witness_preserved=true`였으므로 **더 작은 새 반례를 얻은 건수는 0개**입니다. 제한된 변형 전략에서 native 절차가 완료된 사실과 실제 축소 개선·전역 최소성은 다릅니다. 축소 품질 향상을 입증했다고 주장하지 않습니다.

### 제품 회귀와 남은 검증

전체 회귀는 **669개 통과, 실패·오류·skip 0, pytest suite 125.859초**입니다. 이 실행의 근거는 `E8-R2-regression-frozen-candidate.xml`이며 이전 실행 파일과 시간을 섞지 않습니다. R1 기존 40개 검사 파일과 main의 PyPI 검사 19개를 보호하고 기존 R1 573개 검사를 함께 실행했습니다. 단순 과거 합계만 인용한 것이 아니라 보존 파일과 현재 수집된 검사를 대조했습니다. 후보 wheel 설치·README 명령·Docker CI는 아직 `PENDING`이며 실행 후 별도 영수증으로 갱신합니다.

## 분리한 상태와 발행 제한

```text
SOURCE_REPRODUCTION: PASS_FIXED_REVISION
NUMERICAL_GUIDANCE_IMPLEMENTATION: PASS
COMPACT_WORKER_EXECUTION: SUBPROCESS_PASS_DOCKER_CI_PENDING
SOURCE_VALIDATION: COMPLETE
ADDED_VALUE_OVER_STRONG_BASELINES: NOT_ESTABLISHED_NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR
INDEPENDENT_CORROBORATION: NOT_AVAILABLE
EXTERNAL_GENERALIZATION: NOT_ESTABLISHED
PUBLICATION: DRAFT_PR_ONLY_ALLOW_RELEASE_FALSE
```

R1의 의미·반증·readiness·소비 이력과 main PyPI 경로를 보존했습니다. 전체 회귀와 Source 개발 비교의 완료는 독립 C·Target·외적 일반화·발행 승인을 뜻하지 않습니다. 독립 C·적격 미소비 Target과 발행 readiness가 없어 PR #8은 draft이며 `allow_release=false`입니다. main 병합·새 tag·GitHub Release·PyPI upload는 실행하지 않습니다. PyPI 최초 게시 성공을 이 연구 PR의 발행 승인으로 해석하지 않습니다. 원시 비공개 실패·Oracle 정답·연구 ZIP·Drive 정본을 공개하지 않습니다.
