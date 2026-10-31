# Changelog

## 0.8.0a1 — Experimental product release

- Default online search is A (native Hypothesis with shared public priors). B, explicit Source replay C, and experimental learned guidance D remain opt-in. A/B demos perform no Source collection or learning.
- Added source/Oracle/contract-bound online replay, actionable signature errors, replay provenance, a bundled product example, and English/Korean product guides. Existing explicit C/D scripts retain their arguments; D emits an experimental warning.
- Product publication has its own explicit authorization and actual CI/install/artifact checks. Historical research authorization, frozen results, consumed evidence and negative-transfer conclusions remain unchanged.
- One manual Trusted Publisher workflow creates or verifies an annotated tag, builds the final wheel/sdist once, validates those exact files, stages a Draft Release, publishes the same files to PyPI, then verifies public installations and GitHub downloads before completion. Ordinary CI never uploads packages.
- This release does not establish D superiority, automatic Oracle construction, arbitrary Python verification, or external generalization. See the [migration guide](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/MIGRATION_0_8.md).

## E9-R1 미발행 후보 — C/D fallback 정합성과 역사적 프로젝트 평가

- C/D 공통 기본 선택·공통 RNG를 보존하고 적용 불가·거절·중복 Source 제안은 C로 rollback한다. 손상 Mold는 별도 오류다.
- 실제 3개 프로젝트의 Source·buggy/fixed revision·라이선스·계약 Oracle를 기존 공통 러너·사용 장부에 연결했다. 원본 함수의 AST/root coverage와 wrapper를 구별한다.
- 고정된 OCI 경계 확인, 설치 wheel의 역사 사례 CLI, Source-only 예산 preflight와 수동 1회 연구 실행을 분리했다. 원시 기록은 공개 업로드 전에 암호화한다.
- E9의 원래 360회 결과는 고정 revision으로 검증하며 새 결과로 덮어쓰지 않는다. 배포·merge·tag·PyPI 업로드는 허용하지 않는다.
- 실제384회 비교에서 D는 구현 전이의 C 대비 탐지·호출 이득이 없었고 적격 EMPTY LOMO에서 음의 전이가 관측됐다. A/B/C/D와 미검출·적용비·Source 준비비를 [별도 보고](docs/HISTORICAL_REPORT_KO.md)하며 사후 조정하지 않는다.

## E9 미발행 연구 후보 — 온라인 탐색과 제한된 Source 전이

- 공통 온라인 MRI–CAST와 native Hypothesis 생성·축소를 CLI에 연결하고 C/D의 차이를 Source 학습 provider로 제한합니다.
- 정상/실패 차분의 기존 typed 편집 선택·합성·적용조건을 empirical Mold에 기록합니다. 다중 축의 작성 기능 비교와 실제 프로젝트 독립성의 한계는 [보고](docs/ONLINE_REPORT_KO.md)에 분리합니다.
- 기존 E8/R1/R2/R3/R4 증거·readiness·PyPI0.7.0a1을 보존합니다. 이번에는 새 Release·태그·업로드·main 병합이 없습니다.


## E8-R4 — 미발행 독립 구현 CORR 개발 검사

- 실제 `statistics.correlation`·SciPy `pearsonr` 호출 후 반환값·문서화된 예외·경고·NaN을 정규화하고 기존 정확 수학 Oracle와 비교하는 고정 어댑터를 추가했습니다.
- Source-only 가이드를 변경하지 않는 CORR 전용 host 승인과 기존 사용 장부의 개발 소비 예약을 연결했습니다. FINAL·발행·Generator feedback은 허용하지 않습니다.
- 48개 계획의 결과 전 동결, 고정 자원 비교, 실제 함수 진입·재현·축소·전체 child 과정·영수증 비용 계측과 CLI·설치 검사를 추가했습니다.
- 기존 R3 runtime·audit·후보 응답 검증·worker 5파일·Source/Oracle·720개 검사 계약과 PyPI 수동 경로를 보존했습니다. 구현 적용과 B/C 대비 추가 가치·최종 일반화는 별도 판정합니다.

## E8-R3 — 미발행 실행 비용 개선

- 명시적 runtime의 주 생성 1회·기준 생성 0회와 D audit의 주 생성 1회·기준 생성 1회를 분리했습니다. 기존 D API 기본 감사 수준과 기존 worker 5개 파일의 바이트를 보존합니다.
- 실제 응답의 스키마·요청·후보 digest·domain·중복·제외·출처·입력 특징·동결 상태를 평가 전에 검증합니다. A/B/C도 같은 clean worker 경계를 사용하며 D guide를 요구하지 않습니다.
- 외부 현재 host 승인 상태에 연결한 경량 가이드의 별도 준비·원자적 저장·재사용과 CLI·직렬화·write/flush 계측을 추가했습니다. 전체 archive 검증·보정·컴파일은 준비 비용으로 기록합니다.
- 공개 비용 검증과 새 Source 개발 검증을 분리하고, R2 결과·Oracle·PyPI 수동 발행 경로·readiness를 유지합니다. 신규 배포를 허용하지 않습니다.

All versions are experimental. Versions v0.1.0 through v0.2.0 were retrospective imports of archived snapshots; those commit timestamps **do not** represent the dates when the experiments were originally performed. Later changes are developed in the public repository without rewriting historical tags.

## E8-R2 후속 작업 — 수치 입력 생성과 경량 실행 (미발행)

- main의 PyPI 수동 workflow·검증 스크립트·E7 파일 해시 고정을 보존하며 연구 PR #8을 통합합니다. 공개 `0.7.0a1`을 수정·재업로드하지 않으며 작업 버전 `0.8.0a1`은 미발행 후보입니다.
- R1 의미 분리·readiness·소비 이력을 재사용합니다. 실패 입력의 저장/재생과 수치 구조를 유지하는 새 입력 생성을 구분하는 typed `FailureGuidanceRecipe`를 추가했습니다.
- 고정된 `omega-lock` 과거 revision의 검토된 함수·타입과 기존 정확 입력 Oracle·FINITE_JSON 비교를 연결합니다. 원본 생산 코드와 허용오차·정확한 0·domain·예외 정책은 바꾸지 않습니다. 사용자 제공 진단은 개발 단서로 구분하고 현재 배포판의 문제로 확대하지 않습니다.
- native Hypothesis Strategy와 원본 반례에서 시작하는 bounded native shrinking을 추가했습니다. 상수축·값/길이·표현·부호/스케일·인접 float·순열/반복·정상 대조를 지원하며 정확 float 입력의 중복·알려진 입력·domain 거절을 분리합니다.
- B·D의 공개 수치 지식과 C·D의 실패 자료를 맞추고, D만 검증된 Source 실패·정상 관측으로 family 배정을 보정합니다. 공개 사전지식·보정·검증 결과의 출처를 별도로 기록합니다.
- 원본 72,801,555바이트 archive를 host에서 검증하고 canonical 3,448바이트 경량 가이드로 컴파일합니다. worker는 원시 정답·전체 journal·실행 코드 없이 host 승인 digest·의미 버전·범위·변조·전송 한도를 확인합니다. 전체 archive를 Docker에서 실행했다고 주장하지 않습니다.
- native float 생성이 import된 모듈의 숫자 상수 문맥에 영향을 받는 QA 원인을 확인하고 A·B·C·D의 생성을 동일한 최소 허용 모듈의 별도 process로 분리했습니다. A·B에는 D recipe를 전송하지 않고 C에만 같은 기존 실패 입력을 bounded 데이터로 전달합니다. Oracle 출력·라벨은 전송하지 않으며 Hypothesis 내부 패치는 하지 않습니다. 동일 seed만으로 재생을 보장하지 않고 runtime 버전·모듈 문맥·입력 계약을 함께 고정합니다.
- `numerical-prepare/compile/inspect/run/compare/demo`를 패키지 CLI에 연결하고 호출·최초 새 실패·생성/직렬화/worker/Oracle/축소/재현 및 준비 비용을 계측합니다. 전체 669개 회귀는 실패·오류·skip 0으로 통과했으며 R1 기존 검사 파일과 main PyPI 검사를 보존합니다. 새 환경의 실제 후보 wheel·README 경로 검사 20개(성공 18개·필수 차단 2개)가 통과했습니다. 로컬 QA 의존성 4개는 바이트 확인 후 기존 승인 배포판을 재사용했습니다. Docker·일반 index 설치·원격 CI 상태는 [현재 PR Checks](https://github.com/hibou04-ops/antemortem-structural-lab/pull/8/checks)에서 확인합니다.
- Source 동결 이후 Windows 설치 검사기의 UTF-8 명시와 Python 3.13 AST 출력 호환 처리를 추가했습니다. `ast.dump`의 지원 여부를 확인해 `show_empty=True`를 적용하고 기존 기대 해시 두 개·생산 함수는 유지합니다. 원 Source 157개와 기존 packaging 165개 manifest를 재작성하지 않으며, 현재 `check-e8r2-py313-qa-freeze.py`와 별도 167개 QA 동결이 설치 검사기·CI 진입점·AST 검사라는 세 파일의 정확히 제한된 변경만 검증합니다. Source 비교 배치는 재실행하지 않았습니다. [Python 3.13 공식 AST 문서](https://docs.python.org/3.13/library/ast.html#ast.dump).
- 한 번의 동결 Source 비교에서 A/B/C/D 고유 새 실패 입력 0/15/24/44개를 확인했습니다. C의 seed별 합계 26개와 고유 입력 24개를 구분합니다. 모두 같은 기존 기전이며 신규 기전은 0개입니다. 측정 준비 1회 포함 비용은 2.83759/2.95153/3.37563/23.54118초로 D가 사전 비용 기준을 충족하지 못해 `NO_ADDITIONAL_VALUE_OVER_DOMAIN_PRIOR`입니다. 결과 후 재실행·재보정은 하지 않았습니다. 역사적 수집비용은 `UNKNOWN`입니다. [결과 JSON](docs/E8_R2_RESULTS.json) · [R2 보고서](docs/E8_R2_REPORT.md).
- 독립 C·미소비 Target 부재와 `allow_release=false`를 유지합니다. draft PR만 갱신하며 main 병합·새 tag·GitHub Release·PyPI upload는 실행하지 않습니다. 기능 구현을 외적 일반화나 보편적 성능 우위의 증거로 사용하지 않습니다.

## E8-R1 후속 작업 — 의미별 주장과 Source 검증 (미발행)

- 기존 완전 분류식·반증을 보존하면서 충분조건·필요조건·경험적 가이드를 명시적 의미 버전·ID·snapshot으로 구분하고 엔진의 앞단 제거부터 archive·계획·CLI까지 연결했습니다.
- 실제 기존288표현의 FP_ONLY54/FP_AND_FN234를 재현했습니다. 기존 모든 표현은 FP가 있어 충분조건으로 이름만 바꾸어도 반증됩니다. 제한된128복합을 더한416표현과1,664의미 주장을 독립 지식으로 과장하지 않습니다.
- UNKNOWN과 다른 실패 계열의 미관측을 음성 라벨로 바꾸지 않고, Source 상태·새 Source 검증·독립 C·Target·전이 상태를 분리합니다. C의 충돌 라벨도 원 Source를 오염시키지 않도록 검사했습니다.
- native 흐름과 guidance 예산을 분리하고, 경험적 후보는 별도 개발 비용·효용 검증 없이는 채택하지 않습니다. 직접 작성 예제와 `semantic-learn/inspect/plan/validate/run/demo`를 추가했습니다.
- 실제63MB archive의 복원·gate 프로파일에서 반복 deepcopy/snapshot 병목을 확인해 의미·전체 저널 재생·해시를 보존하는 경로만 최적화했습니다. stateless 범위와8MiB worker 전송 한계를 명시합니다.
- 새 Source 입력42개를126쌍으로 검증해 새 실패0개를 기록했습니다. A/B/C는40/40/41쌍에서 미검출, D는 기존 반례를3쌍으로 재현했습니다. C는새guided입력8개·중복1회·9.279995초의비용을기록했으나 경험적채택0개입니다. 순서·warmup 한계와 미검출을 보존하며 일반적 우열을 주장하지 않습니다.
- 실제 Source250쌍과 Oracle전용대조16회, 학습·추가검증·계획·효용기록 비용을 분리했습니다. 전체573개(기존506+신규67) 회귀는 실패·오류·skip0으로 통과했습니다. 최종 패키지·원격 CI는 [R1 보고서](docs/E8_R1_REPORT.md)의 root 갱신 대상으로 남깁니다. 독립 C·T 부재로 외적 전이·병합·공개 발행을 차단하고 기존 E8 문서·태그·main을 보존합니다.

## 0.8.0a1 작업 후보 — 개발 증거 연결과 평가 readiness (미발행)

- 생산 도구 이름과 무관하게 검토된 `DEVELOPMENT` 기록을 수용하는 공통 계약, 원본 결과·Oracle·출처·재현 결속, 중복 관측 구분과 오류 격리를 추가했습니다. 새 실행과 캐시 재사용을 구분합니다.
- 기본 Native Hypothesis 수집기는 기존 생성·축소를 재사용하고 실제 두 번의 재현과 Target·Oracle 호출 합계 상한을 적용합니다. 사전 승인한 `EXACT_CANONICAL_JSON` 비교만 지원하며 수치 허용오차·정상 예외 비교는 지원하지 않습니다.
- 기존 지식 엔진으로 실제 E7 v2 Source 관측 371개를 누락 없이 연결했습니다. 검증된 실패 입력 5개는 기존 1개 기전에 해당하며 새 블라인드 발견이 아닙니다. 후보 288개는 전부 `CONTRADICTED`, 살아 있는 구조적 가설·독립 C·qualified guidance는 모두 0개입니다.
- Source/C/Target 계약, 실제 guidance 변화, Oracle 검토와 사용 이력을 확인하는 `EvaluationReadiness` 및 호출 전 최종 실행 차단을 추가했습니다. 이름·경로·해시 변경만으로 독립성이나 새 Target을 인정하지 않습니다.
- `evidence-collect/import/inspect/learn/corroborate`, `readiness-check/demo`와 공개 기능 예제를 추가했습니다. 예제는 기능 검사이며 연구 성과에 포함하지 않습니다.
- 승인된 5개 저장소의 Git 이력 182개와 함수 후보 18개를 검토했으나 완전한 독립 S→C→T 연결을 확보하지 못했습니다. 새 생산 코드·Oracle 호출과 최종 A~D 비교는 0회입니다. 상태는 `NOT_EXECUTED_READINESS_BLOCKED`, 전이 가치는 `NOT_EXECUTED`입니다.
- 캐시 Source 전체 재구성은 262.921447초, 음성 메타데이터 readiness 진단은 약 2.544초였습니다. 최초 자료 수집 비용이나 A~D 성능 비교를 대신하지 않으며 자동 ROI 판정은 없습니다.
- 기존 E1~E7 문서·동결 자료를 보존합니다. 전체506개(기존409＋신규97) 검사가 82.569초에 통과했고 실패·skip0, 기존28개 검사 파일의 SHA가 유지됐습니다. 이후 비용 계측 보완 관련29개 검사도 통과했습니다. build·메타데이터·공개 범위, 설치 wheel 검사37개와 README 명령60개가 통과했습니다. CI는 draft PR 현재 head의 필수 검사를 참조합니다. 변경은 작업 브랜치와 draft PR로 보존하며 병합·태그·Release는 만들지 않습니다. [E8 개발 결과와 한계](docs/E8_DEVELOPMENT_REPORT.md).
## 배포 채널 추가 — 기존 `0.7.0a1`의 PyPI 최초 게시 경로

- 이미 공개한 E7 wheel·sdist를 태그·소스·SHA-256으로 고정하여 동일 파일로 최초 게시하는 수동 Trusted Publishing 경로를 추가합니다. 게시 성공과 공개 다운로드·설치는 workflow 실행 결과로 별도 확인합니다.
- PyPI 배포 이름 `antemortem-structural-lab`, import/CLI `tomolab`, 정확한 alpha 설치 버전과 기본·선택 의존성을 안내합니다. 현재 안내를 반영한 로컬 재빌드 파일은 기존 공개 자산을 대신하지 않습니다.
- 기존 E7 GitHub 자산의 검증과 새로운 PyPI 발행을 구분합니다. 기존 태그·동결 manifest·연구 결과를 재작성하거나 E7 Release를 다시 만들지 않습니다.
- E8-R1·C1 연구 PR과 연구 readiness 조건, 기존 다섯 PyPI 도구는 변경하지 않습니다. 배포 채널 추가는 새로운 연구 성능·일반화 검증이 아닙니다. [발행 절차와 파일 연결](docs/PYPI_PUBLISHING.md).

## v0.7.0a1 — Evidence-gated structural knowledge

- 기존 E5/E6 Version Space와 공통 Typed IR을 재사용해 가설·독립 개발 지지·반증·적용 범위와 출처를 보존합니다.
- 검토된 별도 구현의 contrastive evidence와 계약이 충족된 관계만 실제 후보 순서·incremental Z3 witness에 사용합니다. 자격 있는 지식이 없으면 native Hypothesis 경로를 실행합니다.
- append-only·idempotent 저장, 과거 상태 복귀 차단, 부모 해시와 전체 기록을 보존하는 명시적 개발 세대 재개, 내용·검증 버전에 묶인 검증 캐시를 추가했습니다.
- `knowledge-inspect/learn/update/plan/run/demo`, 전송 전·worker 검증, 실제 E7 Docker 접근 통제·설치된 wheel 검사를 추가했습니다.
- 기존322개 검사·E1~E6 동결 결과와 태그를 보존하며 실제 프로젝트의 새 독립 평가를 별도 사전 계약으로 수행합니다. [구현과 신뢰 계약](docs/E7_KNOWLEDGE.md) · [평가·한계](docs/E7_EVALUATION_REPORT.md).
- E5의 검증된 draft/source/hash 검사와 E6 현재 main 정책을 재사용합니다. 새 Draft 생성 후 성공한 빈 목록 조회만 유한 재확인하며 API/권한 오류는 재시도하지 않습니다.
- 개발 v1의 Oracle 오류와 과장된 발견 해석을 철회하고 원본127개 파일을 보존했습니다. 정확 산술 Oracle를 독립 검토한 v2 최종 비교72건은 54 COMPLETE·18 NOT_COMPARABLE, 필수 방법 오류·오탐·feedback0, 모든 방법 발견0·qualified0으로 연구 판정은 INCONCLUSIVE입니다. 이 결과를 성능 향상이나 일반화 성공으로 홍보하지 않습니다.

## v0.6.0a1 — Stateful structural mold and Hypothesis-first discovery

- 공개 EFSM 상태·행동·순서·전제조건·불변식과 첫 실패 전이를 E5의 공유 Version Space·반증 제거에 연결했습니다.
- Native RuleBasedStateMachine의 rule/precondition/invariant/Bundle, 동결 후 native shrinking, 실제 callback 계측·두 번 재실행을 통합했습니다.
- 첫 qualified evidence의 lazy pool/grammar 활성화, incremental Z3 witness·정규화 캐시, 중복 생성 방지와 비용 phase 계측을 추가했습니다.
- 이름·내부 표현이 다른 대상의 4-way 전이 gate와 frozen 계획, 전송 전 등록/feedback 차단 및 별도 E6 Docker 검사를 추가했습니다.
- `stateful-inspect/demo/run/plan`, 명시적 bounded 지원 범위, 새 독립 평가 계약·강한 기준선 비교·한국어 문서를 추가했습니다.
- 기존 250개 테스트·E1~E5 결과·태그·자료 경계를 보존합니다. 연구 결과와 일반화 범위는 [E6 평가](docs/E6_EVALUATION_REPORT.md)에 별도로 기록합니다.
- 새 독립 동결 최종84 records와 개발 모두 NO_IMPROVEMENT입니다. 12/13 개발 후보 반증·OUT_OF_GRAMMAR1건·PARTIAL 표현 해결·외부 실제 프로젝트 NOT_EXECUTED를 공개합니다. 실행 후 제품·계약·가설·설정은 변경하지 않았습니다.
- 배포는 검증된 E5 draft 목록/ID 조회·해시 검사 구현을 재사용하며 E6 현재 main만 annotated tag/prerelease로 공개합니다. PyPI는 게시하지 않습니다.

## v0.5.0a1 — Unified structural discovery engine

- 공개 typed AST guard를 실제 Version Space·Active Query에 연결하고 반증에 따라 다음 query가 바뀌는 통합 discovery 엔진을 추가했습니다.
- native Hypothesis 복합 Strategy·fresh 후보·축소, 실제 선택되는 Z3 witness, typed/role/graph/contract 전이와 counterevidence를 연결했습니다.
- int/finite float/str/list/tuple/dict 입력, bounded state trace, 명시적 예외 계약, 동결 snapshot과 실제 호출·시간·process tree 계측을 제공합니다.
- `discovery-inspect`, `discovery-demo`, `discovery-run`, `discovery-plan`, `analysis` extra와 dependency-only Docker 생성기 이미지를 추가했습니다.
- 기존 145개 포함 로컬 243 tests 통과; 기존 MRI·CAST·Claim·E4 API와 E1~E4 증거·태그를 보존했습니다.
- 개발 비교는 `NO_IMPROVEMENT`: E5/Hypothesis paired wall 중앙 비율 2.660 / 최초 발견 호출 비율 1.0. 외적 일반화는 미입증입니다.
- 최종 source·코드·계약·mold 동결, once-only 독립 평가, annotated tag와 검증된 draft 후 prerelease 공개를 강제합니다. 비공개 final source·원시 기록은 공개하지 않습니다.
- [E5 구현·평가·한계](docs/E5_INTEGRATION.md) · [릴리스 노트](docs/releases/v0.5.0a1.md).

## v0.4.0a1 — E4 Structural QA integration

- 기존 Mold·Version Space에 Hypothesis 생성·축소, 중복 평가 캐시와 실제 호출·다양성·시간 계측을 연결했습니다.
- AST 정수 관계식, enum/Z3 일관성, SAT witness 재검증, UNSAT core와 구조 증거 기반 가설 필터 API를 추가했습니다.
- Generator 전송 전 typed 검증·동결 후 feedback 차단을 강화하고 결정론적 Oracle과 주관적 평가를 분리했습니다.
- `pbt-demo`, `pbt-run`, `constraints-check`, `qa` extra, 별도 최종 검증·설치 검사를 추가했습니다.
- 기존76+신규69, 로컬 총145개 검사 통과.6개 OS/Python CI와 Docker 경계 검사가 릴리스 전제입니다.
- E1/E2/E3·기존 태그 보존. 공개 합성 검증은 블라인드가 아니며 외적 일반화·우위는 미입증입니다.
- [E4 구현·제한](docs/E4_IMPLEMENTATION.md) · [릴리스 노트](docs/releases/v0.4.0a1.md).

## v0.3.0a1 — Integrated Mold engine

- Added a bounded typed relation grammar, counterexample-guided version-space updates, disagreement queries and a diversity archive.
- Added explicit evidence, contradiction, provenance, competing-hypothesis and applicability records. Renamed roles can transfer for probing when declared contracts match; this does not prove bug recurrence.
- Added `mold-demo`, `mold-run` and frozen `mold-plan` commands; existing MRI, CAST, Claim-to-Witness and optional Jev paths remain available.
- Added a separate generator process with JSON-only communication and an optional restricted Docker generator. Host execution of targets and Oracles still requires trust.
- Added optional Z3 support alongside dependency-free bounded enumeration, subpackage-aware packaging, installed-wheel checks and version-independent release checks.
- Reworked the Korean user guide and aligned English documentation. Preserved E1/E2 `NO_IMPROVEMENT` conclusions; see [release validation](docs/RELEASE_VALIDATION.md) for E3's separate evidence and limits.
- No PyPI publication is implied. Private E1/E2 archives, hidden evaluation sources and raw research records are excluded from public artifacts.

## v0.2.0 — Phase C0

- Exact-template (six strings) claim-to-metamorphic-relation compilation.
- No-reference-function counterexample search/replay with relation and source hashes.
- CrossHair assert-based comparison fixture and additional 16 tests (45 total).
- Added explicit limitation: unproven original-claim/obligation semantic fidelity, no established SOTA advantage.
- Before first publication: bilingual README editing, UTF-8 test reading on Windows, installed-wheel example lookup and packaging, plus source/wheel CI checks. Probe and claim algorithms are unchanged.

## v0.1.1

- Direct TypeSafe Jev adapter, alongside Vercel pathway; separate authentication and no unrequested cross-provider paid failover.
- Mock transport/response validation and smoke-test script; 29 tests.

## v0.1.0

- Initial MRI/CAST cross-feedback laboratory, synthetic branch fixtures, reference-function comparison and replay; 21 tests.
