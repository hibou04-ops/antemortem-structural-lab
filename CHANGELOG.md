# Changelog

All versions are experimental. Versions v0.1.0 through v0.2.0 were retrospective imports of archived snapshots; those commit timestamps **do not** represent the dates when the experiments were originally performed. Later changes are developed in the public repository without rewriting historical tags.

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
