# Changelog

All versions are experimental. Versions v0.1.0 through v0.2.0 were retrospective imports of archived snapshots; those commit timestamps **do not** represent the dates when the experiments were originally performed. Later changes are developed in the public repository without rewriting historical tags.

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
