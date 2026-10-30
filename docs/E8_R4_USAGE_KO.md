# E8-R4: 동결 Source 가이드의 CORR 개발 적용

**Source에서 작동한 가이드를 다른 구현에 적용하는 검사와, 그 가이드가 다른 구현에서도 유용하다는 결론은 다릅니다.** 이 기능은 미발행 연구 후보 `0.8.0a1`에 있습니다. 공개 PyPI `0.7.0a1`에는 R1·R2·R3·R4가 없으며 기존 파일을 변경하거나 재업로드하지 않습니다.

## 실제 구현·계약

정식 CORR 실행은 CPython **3.12.10**의 `statistics.correlation`과 SciPy **1.18.1**의 `scipy.stats.pearsonr`(NumPy **2.5.3**)을 고정합니다. 설치된 함수·모듈·핵심 바이너리·배포 RECORD를 검토하고 공식 고정 태그의 함수 AST와 대조했습니다. SciPy 1.18.1 HTML API 문서는 확인할 수 없어 다른 버전의 페이지를 동일 버전처럼 사용하지 않고 [v1.18.1 공식 소스·docstring](https://github.com/scipy/scipy/blob/v1.18.1/scipy/stats/_stats_py.py)을 기준으로 했습니다. [CPython v3.12.10 소스](https://github.com/python/cpython/blob/v3.12.10/Lib/statistics.py)와 설치 코드도 대조했습니다.

Source의 Python 합산·중심화, 표준 라이브러리의 `fsum`/`sumprod` 경로, SciPy의 NumPy 배열 평균·norm 경로를 구분합니다. 동일한 correlation helper를 호출하는 wrapper로 세지 않습니다. CPython runtime 공유는 존재합니다. Oracle는 기존 정확 binary-float 입력의 Fraction/Decimal 수학 helper **한 계보**를 두 대상에 재사용하며 대상 API를 호출하지 않습니다. 독립 Oracle가 여러 개라는 뜻은 아닙니다.

공통 domain은 기존 유한 float `[-1,1]`, 동길이 **3~6**, 정확 상수 허용, 비상수 exact centered sum squares `1e-6` 이상입니다. 새 후보는 R3와 같은 길이 **4/5/6**에서 생성합니다. METHOD_C의 기존 Source 반례 재생은 길이 3을 포함하는 공통 domain에서 별도 phase로 실행합니다. 모든 방법에 같은 계약이 적용됩니다. 거의 상수인 domain 밖 입력을 몰래 추가하지 않습니다.

어댑터는 실제 함수를 호출하고 실제 Python function entry를 확인한 **뒤** 결과를 해석합니다. 입력이 상수라는 이유로 대상 호출을 생략하지 않습니다.

- `statistics.correlation`: 정확 상수에서 문서화된 `StatisticsError`는 `UNDEFINED_AS_DOCUMENTED`입니다. 비상수에서 같은 예외가 나오면 정상 퇴화로 숨기지 않습니다.
- SciPy: 정확 상수의 문서화된 `ConstantInputWarning`과 NaN 조합은 정상 퇴화가 될 수 있습니다. NaN은 유한 JSON에서 `kind=NAN`으로 기록하며 0으로 바꾸지 않습니다.
- 상수에서 유한값이 반환되면 `DEFINED` 상태를 그대로 보존하고 정확 Oracle의 undefined와 비교해 위반을 확인합니다. clipping·출력 대체는 하지 않습니다.
- 비상수 수치 비교는 기존 abs `1e-10` / rel `1e-8`, 정확한 0·bool·None 정책을 유지합니다. 문서화되지 않은 비유한값·예외, 비교 불가, 환경·Oracle 오류를 구분합니다. 경고만으로 결함을 세지 않습니다.
- 최초 불일치와 2회 별도 동일 재현 후의 확인을 구분합니다. 축소 witness도 실제 관측과 두 재현의 의미가 같아야 합니다.

원시 결과·경고·예외·Oracle 값은 평가자 측 로컬 영수증에만 남습니다. Generator에는 보내지 않습니다.

## Source·CORR·FINAL_TARGET

`SOURCE`는 기존 고정 omega-lock 함수, `CORR`는 이번 별도 구현의 개발 검증, `FINAL_TARGET`은 아직 개발에 사용하지 않은 최종 대상입니다. **METHOD_C**는 반례 재생 방법이며 CORR 단계와 다른 개념입니다.

Source 가이드 `c5ac5b4d86a45eb4498af7123eeb928e3974165aa73f4b8202015f0de95a98ed`의 `SOURCE_DEVELOPMENT_ONLY`와 `transfer_authorized=false`를 그대로 유지합니다. CORR permit은 특정 구현·어댑터·Oracle·두 입력 계약·자원 예산·candidate plan·host authority에 연결한 **로컬 개발 실행 승인**입니다. 가이드가 유효하다는 인증서가 아닙니다. FINAL·발행·Generator feedback은 항상 false입니다.

같은 고정 host `UsageLedger`에 CORR START를 기록하면 기존 FINAL readiness와 claim이 그 lineage 토큰의 재사용을 차단합니다. 함수 이름·버전·호스트 경로만 바꿔 미소비로 등록하지 않습니다. 이 장부는 협력하는 동일 권한 root의 기록이며 전역 서버·OS 격리·적대적 host 방어가 아닙니다. 이번 구현은 CORR에서 소비됐으므로 이후 미소비 FINAL로 취급하지 않습니다. 기존 Source archive·readiness·release eligibility를 자동 수정하지 않습니다.

## 설치와 실제 CLI

Python 3.12 이상에서 후보 wheel과 선택 의존성을 별도 환경에 설치합니다. SciPy·NumPy는 `[corr]`에 정확한 버전을 지정했으며 기존 `[qa]`·Source 환경을 업그레이드하지 않습니다. 로컬 검사는 이미 설치된 승인 분포의 바이트를 확인해 재사용할 수 있고, CI는 정상 공개 인덱스로 설치합니다.

```powershell
python -m pip install "./dist/antemortem_structural_lab-0.8.0a1-py3-none-any.whl[qa,solver,corr]"
python -m tomolab corroboration-inspect --help
python -m tomolab corroboration-plan --help
python -m tomolab corroboration-approve --help
python -m tomolab corroboration-run --help
python -m tomolab corroboration-demo --help

# 승인된 공개 가이드를 사용한 기능 예제. 새 workspace와 output 경로가 필요합니다.
python -m tomolab corroboration-demo --implementation python-statistics-correlation --method D --workspace corr-statistics-demo --seed 7 --size 3 --max-examples 128 --budget 12 --shrink-budget 0 --allow-local-execution --output corr-statistics.json
python -m tomolab corroboration-demo --implementation scipy-stats-pearsonr --method D --workspace corr-scipy-demo --seed 7 --size 3 --max-examples 128 --budget 12 --shrink-budget 0 --allow-local-execution --output corr-scipy.json

# A/B에는 가이드·반례 자료를 제공하지 않습니다.
python -m tomolab corroboration-plan --method B --seed 7 --size 3 --max-examples 128 --output corr-B-plan.json
```

실제 분리 경로는 `corroboration-inspect` → `corroboration-plan` → `corroboration-approve` → `corroboration-run`입니다. approve는 검토한 identity와 별도 현재 host 승인 상태를 새 파일로 작성하는 명시적 host 작업입니다. 해시만으로 스스로 권한을 얻지 않습니다. run은 `--allow-local-execution`, 승인 state, permit, 같은 authority의 사용 장부를 요구합니다. CLI는 최종 평가를 우회하는 `force` 옵션이나 임의 코드·import path를 받지 않습니다. output과 `.io.json`은 기록한 실제 bytes의 SHA와 write/flush 비용을 연결합니다.

`corroboration-demo`와 설치 검사는 공개 기능 회귀이며 등록한 CORR 연구 배치를 반복 실행하지 않습니다. 위 명령의 설치·실행 검사는 `scripts/check-corroboration-wheel.py`에서 새 환경과 설치된 module origin으로 확인합니다.

## 고정 비교와 비용

A는 typed Strategy, B는 D와 같은 공개 수치 사전지식·전략 family, C는 D가 학습한 동일 Source 반례의 재생·원래 일반 변형, D는 수정하지 않은 Source 보정 가이드입니다. 모두 기존 runtime worker에서 1회 생성합니다. A/B에는 D의 archive·가이드·recipe를 주지 않고 C에만 원래 Source 입력을 제공합니다. 새로운 대상의 코드·위치·출력·정답은 어떤 Generator 요청에도 포함하지 않습니다.

모든 **48개 계획을 대상 수치 호출 전에 동결**합니다. 이는 `Hypothesis-strategy-plan` 비교이며 완전한 적응형 Hypothesis PBT 전체보다 우월하다는 주장이 아닙니다. 별도 audit는 기존 공개 회귀·CI에 유지합니다. Generator 최소 module 5개와 Source·Oracle·R3 runtime/응답 검증은 바이트 보존합니다. 역할별 에이전트는 같은 작업공간·도구를 공유하며 역할 분리를 접근 권한 격리라고 주장하지 않습니다.

주지표는 `DETECTION_BREADTH`와 `FIXED_BUDGET_DISCOVERY`입니다. 최초 확인 시간·호출, Prepared·Cold 비용, 입력 수는 따로 보고합니다. 미발견의 최초 시간은 null이며 성공 시간으로 평균하지 않습니다. 기전 수와 입력 수·계약 category 수도 구분합니다.

Prepared는 해당 plan 생성·Source guide load/검증·Target import·어댑터·정규화·Oracle·확인 재현·축소·영수증 기록을 포함하고 공통 setup은 명시적으로 배분합니다. 선지출 plan 비용+run 최초 확인 시각은 비용 합산 지연이며 연속 wall clock이 아닙니다. 실제 전역 최초 관측과 별도 기록합니다. parent stopwatch는 fresh child의 시작·import·최종 private/public JSON fsync·종료까지 측정합니다. parent 영수증 자신의 쓰기는 별도입니다.

R4는 가이드를 재보정·컴파일하지 않습니다. Cold에는 기록된 R3의 준비 비용을 재사용한 시나리오를 따로 표시하며 두 구현×D 6회, 총 12회 사용에 공유합니다. 이를 이번 R4에서 새로 측정한 준비 비용이라고 하지 않습니다. 과거 최초 Source 수집 비용은 `UNKNOWN`이며 0이 아닙니다.

실제 발견·미발견·B/C 대비 이득과 손실은 `E8_R4_RESULTS.json`과 최종 보고에 기록합니다. 기존 R2·R3의 부정적 추가 가치 판정은 그대로입니다. CORR 결과가 긍정적이더라도 qualified 지식·세 번째 미관측 구현의 최종 전이·통계적 일반 우월성·발행으로 승격하지 않습니다. PR #8은 draft·`allow_release=false`, main 병합·새 tag·GitHub Release·PyPI upload·Drive 쓰기는 모두 0회입니다.
