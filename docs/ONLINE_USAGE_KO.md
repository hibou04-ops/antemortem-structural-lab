# 온라인 탐색과 Source 변형 정책

타깃 내부에서는 실행 반응에 적응하고, 타깃 사이에서는 Source에서 학습한 변형 정책을 제한적으로 재사용한다. 두 효과는 별도로 평가한다.

이 기능은 E8-R4를 부모로 하는 **미발행 0.8.0a1 후보**에 있다. 공개 PyPI `0.7.0a1`에는 없다. 기존 E8 권한·readiness·`allow_release=false`는 그대로 유지한다. 새 프로파일은 `EXPERIMENTAL_PROBE`이며 타깃 내부 피드백만 허용한다. FINAL·공개 발행·타깃 간 온라인 상태 전달 권한을 부여하지 않는다.

## 설치와 지원 범위

후보 wheel을 별도 환경에 설치한다. 아래 wheel 파일은 이 브랜치에서 `python -m build`로 만들거나 별도로 제공된 미발행 파일을 사용한다.

```powershell
python -m venv online-env
online-env/Scripts/Activate.ps1
python -m pip install "./dist/antemortem_structural_lab-0.8.0a1-py3-none-any.whl[qa]"
python -m tomolab online-run --help
python -m tomolab online-learn --help
python -m tomolab online-demo --help
```

기존 패키지 Python 메타데이터는 `>=3.11`이다. CI 범위는 Python 3.11·3.12·3.13이며, 등록 비교 환경과 Hypothesis 버전은 [고정 설정](ONLINE_PROFILE.json)에 기록한다. 다른 버전의 결과를 추정하지 않는다.

입력은 하나의 JSON 값이다. 지원 kind는 `int`, `float`, `sequence_int`, `sequence_float`, `text`, `mapping`, `state_trace`, `graph`다. 계약은 수치 범위·크기·문자/행동 집합·지원 전제조건을 제한한다. 지원하지 않는 중첩 타입이나 전제조건은 거절한다. `examples/online/contract.json`은 작은 정수열 예제다.

Target과 Oracle는 동기 Python 함수로 입력 하나를 받는다. Target은 생산 함수 또는 검토된 얇은 adapter이고 Oracle는 사용자가 승인한 계약 모델이다. 두 함수에 입력의 별도 복사본을 전달한다. 기본 비교는 반환 타입·값과 명시적 예외 정책을 보존한다. 허용오차·NaN 동등성·기대 예외는 공개 비교 계약에 명시해야 한다. 알 수 없는 출력과 미등록 Oracle 예외는 정상 반증으로 학습하지 않는다.

```python
from tomolab.discovery.online_engine import run_online

result = run_online(implementation, reference, contract,
                    method="C", seed=7, budget=48, shrink_budget=8)
```

라이브러리 호출도 신뢰한 로컬 코드를 실행한다. OS sandbox나 호출 중단을 강제하는 보안 경계가 아니다. 순수 함수 또는 전체 trace를 받을 때마다 상태를 새로 만드는 adapter를 사용한다. 전역·closure·외부 객체 상태를 자동 reset하지 않는다. 함수 간 정책 상태는 재사용하지 않는다.

## 실제 사용 경로

새 디렉터리와 영수증을 사용한다. 기존 파일은 덮어쓰지 않는다. 아래 Source/Target은 **의도적으로 결함을 넣은 공개 기능 예제**이며 실제 프로젝트 결함 발견 자료가 아니다.

```powershell
$OnlineExamples = (python -c "from tomolab.cli import EXAMPLES; print(EXAMPLES / 'online')").Trim()
$OnlineWork = Join-Path (Get-Location) 'online-example'
New-Item -ItemType Directory -Path $OnlineWork

python -m tomolab online-run "$OnlineExamples/source.py" --oracle-file "$OnlineExamples/oracle.py" --contract "$OnlineExamples/contract.json" --method B --budget 32 --shrink-budget 6 --seed 7 --usage-ledger "$OnlineWork/usage.jsonl" --allow-local-execution --output "$OnlineWork/source.json"

python -m tomolab online-learn --observations "$OnlineWork/source.json" --mold "$OnlineWork/mold.json" --output "$OnlineWork/learning.json"

$OnlineDigest = (Get-Content "$OnlineWork/learning.json" -Raw | ConvertFrom-Json).mold_digest
python -m tomolab online-run "$OnlineExamples/target.py" --oracle-file "$OnlineExamples/oracle.py" --contract "$OnlineExamples/contract.json" --method D --mold "$OnlineWork/mold.json" --expected-digest $OnlineDigest --budget 32 --shrink-budget 6 --seed 7 --usage-ledger "$OnlineWork/usage.jsonl" --allow-local-execution --output "$OnlineWork/target.json"
```

C는 Mold 없이 같은 온라인 엔진을 실행한다. 승인된 Source 입력만 담은 JSON 배열을 `--replays`로 줄 수 있다. 같은 Target을 여러 방법·seed로 비교할 때는 공통 평가 러너에 한 배치로 등록한다. CLI의 단일 실행 장부에서 이미 소비한 정체성을 새 미관측 평가로 다시 등록하지 않는다. 이 장부는 고정된 협력적 로컬 authority이며 전역 소비 등록소가 아니다.

```powershell
python -m tomolab online-run YOUR_TARGET.py --oracle-file YOUR_ORACLE.py --contract YOUR_CONTRACT.json --method C --replays APPROVED_SOURCE_INPUTS.json --budget 48 --shrink-budget 8 --usage-ledger NEW_USAGE.jsonl --allow-local-execution --output NEW_RESULT.json
```

`online-demo --method D`는 Source 실행·Mold 저장·별도 작성 Target 적용을 한 번에 연결한다. `--workspace`, `--usage-ledger`, `--output`에는 새 경로를 준다. 비교 연구 배치를 재실행하는 명령은 아니다.

## 구조 관측과 온라인 적응

`--mode structural`은 Target의 공개 AST에서 분기·비교·리터럴·반복·호출명·변수 읽기·대입 위치를 수집하고, 원래 함수를 한 번 실행하며 root 함수의 line signature를 기록한다. 비교식이나 iterator를 다시 평가하지 않는다. 사용자 `__lt__`, 단락 평가, 예외 순서를 바꾸는 AST 삽입은 하지 않는다. branch distance는 지원되는 기본 수치 입력과 공개 리터럴 사이의 제한된 거리이며 실패 확률이 아니다. helper 내부 의미나 임의 Python 전체를 분석하지 않는다.

`--mode black_box`는 명시적인 구조 미관측 실행이다. 네이티브 함수·동적 객체·지원하지 않는 구문은 `UNSUPPORTED`/`UNKNOWN` 또는 부분 관측으로 남긴다. fallback을 구조 분석 성공으로 계산하지 않는다.

정책은 `PASS`, `FAILURE`, `INVALID_INPUT`, `EXECUTION_ERROR`, `ORACLE_ERROR`, `UNKNOWN`, 경로·거리·예외 종류 등 제한된 CAST 피드백만 받는다. Oracle 원시 출력·참조 구현·평가자 전용 반례는 전달하지 않는다. 같은 초기 상태에서도 피드백이 다르면 다음 편집이 달라지는 통합 검사를 제공한다.

생성기는 R3의 검토된 disposable process loader를 재사용한 별도 프로세스에서 동작한다. 매 run에 공개 모듈 여섯 개만 복사하고 Hypothesis를 새로 시작한다. Target·Oracle 모듈과 원시 결과·출력 hash는 복사하지 않는다. Host는 요청 입력을 실제 평가하고 제한된 피드백과 같은 입력의 재현 일치 여부만 반환한다. 이 분리는 Hypothesis의 로컬 모듈 상수 수집에서 Oracle가 섞이는 것을 막기 위한 것이다. 기존 Docker 회귀를 E9의 OS 격리 증거로 확대하지 않는다.

세 번의 같은 실제 불일치로 반례를 확인한다. 축소는 native Hypothesis `find`와 제한된 공통 삭제/편집을 재사용한다. 예산 소진을 정상 라벨로 꾸미지 않는다. 결과는 예산과 편집 집합 안의 축소이며 전역 최소성·인과적 유일성은 주장하지 않는다. 정상 짝이 없으면 쌍 학습만 `UNAVAILABLE`로 남긴다.

## Source에서 무엇을 학습하는가

삭제·복제·동일화·부호/인접값·순서·키/trace/간선 편집은 모두 `COMMON_PRIOR`다. 모든 온라인 방법에 같은 편집 언어를 제공한다. Source의 실제 정상/실패 관측에서 기존 편집 한 개 또는 두 개가 정상→실패 차이를 재현하는지 검사하고, 관측 지원·반증으로 선택 점수와 구조 전제조건을 정한다.

실제로 배출된 규칙에 따라 `SOURCE_LEARNED_SELECTION`, `SOURCE_LEARNED_COMPOSITION`, `SOURCE_LEARNED_APPLICABILITY`를 구분한다. Source의 정확한 숫자·변수명·Target ID를 실행 조건으로 저장하지 않는다. 새 메커니즘을 발명했거나 완전한 CEGIS 합성을 수행했다고 표현하지 않는다. 규칙은 기존 `EMPIRICAL_SEARCH_GUIDANCE` 의미와 `UNKNOWN` 경계를 유지한다. 이 프로파일은 Z3 의미를 임의 Python에 확장하지 않으며 Solver 호출은 0으로 계측한다.

Mold는 데이터 전용 JSON이고 최대 10KiB다. 제한에 걸린 규칙은 사전 정한 순위로 제외하고 제외 수를 기록한다. digest는 무결성 연결이며 실행 권한 자체가 아니다. 전체 역사 archive는 후보 생성마다 복사하거나 읽지 않는다.

## 비교와 비용

| 방법 | 구성 |
|---|---|
| E9_A | native Hypothesis `@given` + 공개 경로/거리 `target`, 공통 확인·축소 |
| E9_B | 같은 native 기반 + 공통 온라인 MRI–CAST 편집 정책 |
| E9_C | B + Source 반례 재생·일반 변형 |
| E9_D | C + 학습된 Source 편집·적용 정책 |

C/D의 스케줄러·총 호출 예산은 같다. 재생 최대 20%, 구조 슬롯 최대 30%를 호출 단위로 제한하고 남은 발견 예산은 기본 탐색에 둔다. 확인 호출도 원래 슬롯에 청구한다. 무효·중복·적용 불가 가이드는 기본 탐색으로 예산을 반환한다. 이 배분은 성능 보장이 아니다. D는 실험 옵션이며 테스트 통과만으로 기본값으로 승격하지 않는다.

`database=None`, seed, native 생성/target 단계, 축소 단계와 explicit target-local 정책 상태를 영수증에 기록한다. 직접 작성한 편집 루프를 순수 Hypothesis라고 부르지 않는다. state trace는 native list Strategy로 생성하고 호출마다 전체 trace를 재생한다. `RuleBasedStateMachine` 통합을 제공하는 것은 아니다. [공식 Hypothesis API](https://hypothesis.readthedocs.io/en/latest/reference/api.html), [stateful API](https://hypothesis.readthedocs.io/en/latest/stateful.html)를 검토했다. HypoFuzz/Pynguin은 운영 범위가 달라 이번에 설치·실행·성능 비교하지 않았다.

호출 수는 실제 Target/Oracle 진입 기준이며 최초 확인에는 재현을 포함한다. 미검출 시간은 `null`로 남긴다. 생성·매칭·계측·Target·Oracle·재현·축소와 전체 wall을 계측하되 중첩된 시간을 더하지 않는다. tracing 시간은 Target 구간에 포함된다. Source 수집·학습비, 프로세스 준비·직렬화·영수증 비용도 별도로 보고한다. 시간 상한은 호출 사이에서 확인하는 협력적 상한이다.

[고정 평가 설정](ONLINE_PROFILE.json), [전체 비교 결과](ONLINE_RESULTS.json), [한국어 보고](ONLINE_REPORT_KO.md)에서 탐지·미검출·부정적 전이·원가를 함께 확인한다. 작성한 기능 문제와 실제 프로젝트 독립 전이는 구분하며, 기존 R2/R3/R4의 부정적 결과·소비 이력은 변경하지 않는다.
