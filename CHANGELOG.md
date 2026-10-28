# Changelog

All versions are experimental. Versions v0.1.0 through v0.2.0 were retrospective imports of archived snapshots; those commit timestamps **do not** represent the dates when the experiments were originally performed. Later changes are developed in the public repository without rewriting historical tags.

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
